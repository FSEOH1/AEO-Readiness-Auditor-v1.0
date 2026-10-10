"""Streamlit front-end for the no-paid-API AEO/GEO site auditor."""
from __future__ import annotations
import io
import json
import time
from urllib.parse import urlparse

import pandas as pd
import requests
import streamlit as st

from crawler import DEFAULT_UA, CrawlError, discover_urls, fetch_html, normalize_url
from extractor import extract_page
from checks_content import run_content_checks
from checks_technical import run_technical_checks
from checks_schema import run_schema_checks
from scoring import enrich_and_score, executive_summary
import database

st.set_page_config(page_title="AEO/GEO Readiness Auditor", page_icon="🔎", layout="wide")
database.init_db()

st.title("🔎 AEO/GEO Readiness Auditor")
st.caption("Site-wide content, technical and structured-data auditing with transparent scoring and persistent audit history.")
st.info("This is a heuristic diagnostic tool. Scores are not industry standards and do not predict AI citations, search rankings, or indexing.")

with st.sidebar:
    st.header("Crawl settings")
    crawl_mode = st.selectbox("URL discovery", ["Sitemap + internal links", "Sitemap only"])
    max_pages = st.number_input("Maximum pages per run", min_value=1, max_value=1000, value=100, step=25)
    timeout = st.slider("Request timeout (seconds)", 5, 40, 15)
    delay = st.slider("Delay between requests (seconds)", 0.2, 3.0, 0.6, 0.1)
    obey_robots = st.checkbox("Respect robots.txt", value=True)
    user_agent = st.text_input("User-Agent", DEFAULT_UA)
    st.caption("Use only on sites you are authorised to audit. Crawl conservatively. Public cloud local storage may not be durable.")

tab_audit, tab_history, tab_method = st.tabs(["Run site audit", "Audit history", "Scoring & limitations"])

with tab_audit:
    st.subheader("Website and sitemap")
    root_url_input = st.text_input("Website URL", placeholder="https://example.com")
    sitemap_input = st.text_input("Sitemap URL (optional)", placeholder="https://example.com/sitemap.xml")
    notes = st.text_input("Audit notes (optional)", placeholder="Client, project, release or comparison notes")
    run = st.button("Discover URLs and run audit", type="primary")
    if run:
        try:
            root_url = normalize_url(root_url_input)
            parsed_root = urlparse(root_url)
            if not parsed_root.hostname:
                raise CrawlError("A valid website hostname is required.")
            sitemap_url = normalize_url(sitemap_input) if sitemap_input.strip() else None
            progress = st.progress(0, text="Discovering URLs...")
            status = st.empty()
            def crawl_progress(done, total):
                progress.progress(min(1.0, done / max(1, total)), text=f"Discovering internal links: {done}/{total}")
            urls, warnings = discover_urls(
                root_url, sitemap_url=sitemap_url, mode=crawl_mode, max_pages=int(max_pages),
                timeout=timeout, delay=delay, user_agent=user_agent, obey_robots=obey_robots,
                progress_callback=crawl_progress
            )
            st.session_state["last_discovered_urls"] = urls
            if not urls:
                st.error("No URLs were discovered. Check the sitemap URL, site access, robots.txt and crawl settings.")
            else:
                results = []
                crawl_progress(0, len(urls))
                for idx, url in enumerate(urls, 1):
                    status.write(f"Auditing {idx}/{len(urls)}: {url}")
                    try:
                        response = fetch_html(url, timeout=timeout, user_agent=user_agent, delay=delay, obey_robots=obey_robots)
                        page = extract_page(response)
                        findings = run_content_checks(page) + run_technical_checks(page) + run_schema_checks(page)
                        findings, score_info = enrich_and_score(findings)
                        results.append({
                            **page, "findings": findings, "score": score_info["score"],
                            "score_label": score_info["label"], "score_info": score_info
                        })
                    except Exception as exc:
                        results.append({
                            "requested_url": url, "url": url, "status_code": None,
                            "title": "", "word_count": 0, "score": 0, "score_label": "Fetch failed",
                            "findings": [{
                                "category":"Fetch", "check":"Page fetch failed", "status":"Fail",
                                "evidence":f"{exc.__class__.__name__}: {str(exc)[:300]}",
                                "recommendation":"Check URL availability, TLS, robots.txt, redirects, server rules and whether the page returns HTML.",
                                "severity":"high", "confidence":"high", "priority":"P1",
                                "score_awarded":0, "score_possible":0
                            }]
                        })
                    crawl_progress(idx, len(urls))
                audit_id = database.save_audit(root_url, len(urls), results, notes)
                st.session_state["last_results"] = results
                st.session_state["last_audit_id"] = audit_id
                st.session_state["last_root_url"] = root_url
                st.session_state["last_warnings"] = warnings
                status.success(f"Audit #{audit_id} completed: {len(results)} URLs processed.")
                progress.progress(1.0, text="Audit complete")
        except Exception as exc:
            st.error(f"Could not start audit: {exc.__class__.__name__}: {exc}")

    if st.session_state.get("last_warnings"):
        with st.expander("Crawl warnings"):
            for warning in st.session_state["last_warnings"][:200]:
                st.write("- " + warning)
    if st.session_state.get("last_discovered_urls"):
        with st.expander(f"Discovered URLs ({len(st.session_state['last_discovered_urls'])})"):
            st.dataframe(pd.DataFrame({"URL": st.session_state["last_discovered_urls"]}), use_container_width=True, hide_index=True)

    results = st.session_state.get("last_results", [])
    if results:
        st.markdown("---")
        st.subheader(f"Audit results · Run #{st.session_state.get('last_audit_id')}")
        successful = [r for r in results if r.get("status_code") is not None]
        avg_score = round(sum(r.get("score", 0) for r in successful) / len(successful), 1) if successful else 0
        failures = len(results) - len(successful)
        all_findings = [f for r in results for f in r.get("findings", [])]
        summary = executive_summary(all_findings)
        c1,c2,c3,c4 = st.columns(4)
        c1.metric("Pages processed", len(results))
        c2.metric("Average signal score", f"{avg_score}/100")
        c3.metric("Fetch failures", failures)
        c4.metric("P1 findings", summary["p1"])
        st.caption("Average score includes only successfully fetched pages; failed fetches are reported separately.")
        page_rows = []
        for r in results:
            page_rows.append({
                "URL": r.get("url", ""), "HTTP status": r.get("status_code"),
                "Score": r.get("score"), "Title": r.get("title", ""),
                "Words": r.get("word_count", 0),
                "Findings needing review": sum(1 for f in r.get("findings", []) if f.get("status","").lower() in {"fail","warning","review"}),
                "Schema types": ", ".join(r.get("schema_types", []))
            })
        page_df = pd.DataFrame(page_rows)
        st.markdown("#### Page inventory")
        st.dataframe(page_df, use_container_width=True, hide_index=True)
        st.markdown("#### Prioritised findings")
        finding_rows = []
        for r in results:
            for f in r.get("findings", []):
                if f.get("status", "").lower() in {"fail","warning","review"}:
                    finding_rows.append({"Priority":f.get("priority"),"URL":r.get("url"),"Category":f.get("category"),
                        "Check":f.get("check"),"Status":f.get("status"),"Evidence":f.get("evidence"),
                        "Recommendation":f.get("recommendation"),"Confidence":f.get("confidence")})
        findings_df = pd.DataFrame(finding_rows)
        if not findings_df.empty:
            priority_filter = st.multiselect("Filter priorities", ["P1","P2","P3"], default=["P1","P2","P3"])
            st.dataframe(findings_df[findings_df["Priority"].isin(priority_filter)], use_container_width=True, hide_index=True)
        else:
            st.success("No checks marked for review by this heuristic ruleset.")
        pages_csv = page_df.to_csv(index=False).encode("utf-8")
        findings_csv = findings_df.to_csv(index=False).encode("utf-8")
        json_payload = json.dumps(results, ensure_ascii=False, indent=2)
        xlsx_buffer = io.BytesIO()
        try:
            with pd.ExcelWriter(xlsx_buffer, engine="openpyxl") as writer:
                page_df.to_excel(writer, sheet_name="Pages", index=False)
                findings_df.to_excel(writer, sheet_name="Findings", index=False)
                pd.DataFrame([{"Audit ID":st.session_state.get("last_audit_id"),"Root URL":st.session_state.get("last_root_url"),
                               "Notes":notes,"Average score":avg_score,"Pages processed":len(results)}]).to_excel(writer, sheet_name="Summary", index=False)
            xlsx_data = xlsx_buffer.getvalue()
        except Exception:
            xlsx_data = None
        d1,d2,d3,d4 = st.columns(4)
        d1.download_button("Download pages CSV", pages_csv, "aeo_pages.csv", "text/csv")
        d2.download_button("Download findings CSV", findings_csv, "aeo_findings.csv", "text/csv")
        d3.download_button("Download results JSON", json_payload.encode("utf-8"), "aeo_results.json", "application/json")
        if xlsx_data:
            d4.download_button("Download Excel workbook", xlsx_data, "aeo_audit.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

with tab_history:
    st.subheader("Saved audit history")
    audits = database.list_audits(limit=100)
    if not audits:
        st.info("No saved audits yet. Run a site audit to create the first history record.")
    else:
        history_df = pd.DataFrame(audits)
        st.dataframe(history_df, use_container_width=True, hide_index=True)
        ids = [row["id"] for row in audits]
        chosen_id = st.selectbox("View audit ID", ids)
        audit, pages, findings = database.get_audit(int(chosen_id))
        if audit:
            st.write(f"**Root URL:** {audit['root_url']}")
            st.write(f"**Started:** {audit['started_at']} · **Pages succeeded:** {audit['pages_succeeded']}/{audit['pages_requested']} · **Average score:** {audit['score_average']}")
            if pages:
                st.dataframe(pd.DataFrame([{k:p[k] for k in ["url","final_url","status_code","score","title","word_count"]} for p in pages]), use_container_width=True, hide_index=True)
            if findings:
                st.dataframe(pd.DataFrame(findings), use_container_width=True, hide_index=True)
            if st.button("Export selected historical audit as JSON"):
                payload = {"audit":audit,"pages":[{**p,"result_json":json.loads(p["result_json"])} for p in pages],"findings":findings}
                st.download_button("Download historical JSON", json.dumps(payload, indent=2, ensure_ascii=False).encode(), f"aeo_audit_{chosen_id}.json", "application/json")

with tab_method:
    st.subheader("How scoring works")
    st.write("The score is a transparent checklist score over observed signals. It is not a ranking factor model and does not predict citations.")
    st.markdown("""
    - **Pass:** the expected observable signal was found.
    - **Review:** a human should decide whether the signal is needed or missing.
    - **Warning:** a potentially important issue needs review.
    - **Fail:** a specific check failed, such as a fetch failure or malformed JSON-LD.
    - **P1/P2/P3:** rule-based prioritisation based on configured severity, not measured business impact.

    Scores are starting heuristics. Tune them for page type and validate findings before treating them as defects.
    """)
    st.subheader("Current limitations")
    st.markdown("""
    - HTML is fetched without a browser engine; JavaScript-rendered content may be missed.
    - The crawler does not measure Core Web Vitals, Google indexing status, or actual AI-platform citations.
    - Robots.txt parsing is best-effort; confirm site policy and permissions before crawling.
    - Link discovery is same-host only; subdomains are treated as separate hosts.
    - SQLite is suitable for a prototype, but Community Cloud local storage may reset. Use persistent managed storage for dependable long-term history.
    - JSON-LD parsing is not full Schema.org or Google rich-result validation.
    - Scores do not guarantee AEO/GEO performance.
    """)
    st.subheader("Safe use")
    st.write("The crawler blocks non-public resolved IP addresses and revalidates redirect destinations. This is best-effort SSRF protection, not a substitute for infrastructure-level egress controls. Use conservative crawl limits and audit only sites you are authorised to test.")
