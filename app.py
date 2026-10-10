import json
import re
import time
from collections import Counter
from urllib.parse import urljoin, urlparse

import pandas as pd
import requests
import streamlit as st
from bs4 import BeautifulSoup

APP_VERSION = "1.0.0"
DEFAULT_UA = "AEOReadinessAuditor/1.0 (+website content audit; respectful crawl)"

st.set_page_config(page_title="AEO Readiness Auditor", page_icon="🔎", layout="wide")

st.title("🔎 AEO Readiness Auditor")
st.caption("A practical, API-free audit of on-page signals that can help content be accessible, understandable, and useful to answer engines.")
st.info(
    "This tool checks observable page-level signals. It does not predict or guarantee AI citations, "
    "Google rankings, rich results, or inclusion in any answer engine."
)

with st.sidebar:
    st.header("Audit settings")
    timeout = st.slider("Request timeout (seconds)", 5, 30, 15)
    max_internal = st.slider("Internal links to inspect", 0, 100, 25)
    user_agent = st.text_input("User-Agent", value=DEFAULT_UA)
    st.caption("Only audit sites you are authorized to access. Respect robots.txt, rate limits, and site terms.")

def normalize_url(raw):
    raw = (raw or "").strip()
    if not raw:
        return None
    if not re.match(r"^https?://", raw, flags=re.I):
        raw = "https://" + raw
    parsed = urlparse(raw)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return None
    return raw

def fetch_page(url, timeout, user_agent):
    headers = {"User-Agent": user_agent, "Accept": "text/html,application/xhtml+xml"}
    response = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
    response.raise_for_status()
    content_type = response.headers.get("Content-Type", "")
    if "html" not in content_type.lower() and not response.text.lstrip().lower().startswith(("<!doctype html", "<html")):
        raise ValueError(f"URL did not return an HTML page (Content-Type: {content_type or 'unknown'}).")
    return response

def meta_content(soup, name=None, prop=None):
    tag = None
    if name:
        tag = soup.find("meta", attrs={"name": re.compile(rf"^{re.escape(name)}$", re.I)})
    if prop and tag is None:
        tag = soup.find("meta", attrs={"property": re.compile(rf"^{re.escape(prop)}$", re.I)})
    return (tag.get("content") or "").strip() if tag else ""

def clean_text(node):
    return re.sub(r"\s+", " ", node.get_text(" ", strip=True)).strip() if node else ""

def jsonld_blocks(soup):
    parsed, errors = [], []
    for i, tag in enumerate(soup.find_all("script", attrs={"type": re.compile(r"application/ld\+json", re.I)}), 1):
        raw = tag.string or tag.get_text()
        if not raw.strip():
            errors.append(f"JSON-LD block {i}: empty script.")
            continue
        try:
            parsed.append(json.loads(raw))
        except Exception as exc:
            errors.append(f"JSON-LD block {i}: invalid JSON ({exc.__class__.__name__}).")
    return parsed, errors

def flatten_schema_types(value):
    found = []
    if isinstance(value, dict):
        t = value.get("@type")
        if isinstance(t, str):
            found.append(t)
        elif isinstance(t, list):
            found.extend([str(x) for x in t])
        for v in value.values():
            found.extend(flatten_schema_types(v))
    elif isinstance(value, list):
        for v in value:
            found.extend(flatten_schema_types(v))
    return found

def audit_page(url, timeout, user_agent, max_internal):
    response = fetch_page(url, timeout, user_agent)
    final_url = response.url
    soup = BeautifulSoup(response.text, "html.parser")

    for tag in soup(["script", "style", "noscript", "svg", "template"]):
        tag.decompose()

    title_tag = soup.title
    title = clean_text(title_tag)
    description = meta_content(soup, name="description")
    canonical_tag = soup.find("link", rel=lambda v: v and "canonical" in [x.lower() for x in (v if isinstance(v, list) else str(v).split())])
    canonical = (canonical_tag.get("href") or "").strip() if canonical_tag else ""
    robots_meta = meta_content(soup, name="robots")
    googlebot_meta = meta_content(soup, name="googlebot")
    viewport = meta_content(soup, name="viewport")
    lang = (soup.html.get("lang") or "").strip() if soup.html else ""

    h1s = [clean_text(x) for x in soup.find_all("h1") if clean_text(x)]
    headings = {f"h{i}": [clean_text(x) for x in soup.find_all(f"h{i}") if clean_text(x)] for i in range(1, 7)}
    body_text = clean_text(soup.body or soup)
    words = re.findall(r"\b[\w'-]+\b", body_text)
    word_count = len(words)

    # Identify answer-like blocks near the beginning of the main content.
    main = soup.find("main") or soup.find("article") or soup.body or soup
    main_text = clean_text(main)
    main_words = re.findall(r"\b[\w'-]+\b", main_text)
    opening_text = " ".join(main_words[:120])
    answer_first = len(main_words) >= 30 and bool(re.search(
        r"\b(is|are|means|refers to|helps|allows|provides|costs|requires|includes|works by|can be|typically|usually)\b",
        opening_text, re.I
    ))
    paragraphs = [clean_text(p) for p in main.find_all("p") if clean_text(p)]
    short_answer_paragraphs = [p for p in paragraphs if 20 <= len(re.findall(r"\b[\w'-]+\b", p)) <= 100]

    faq_terms = re.compile(r"\b(faqs|frequently asked questions|common questions)\b", re.I)
    faq_heading = any(faq_terms.search(clean_text(h)) for h in main.find_all(["h1", "h2", "h3", "h4"]))
    question_headings = [clean_text(h) for h in main.find_all(["h2", "h3", "h4"]) if clean_text(h).endswith("?")]
    q_marks = main_text.count("?")

    schemas, schema_errors = jsonld_blocks(BeautifulSoup(response.text, "html.parser"))
    schema_types = sorted(set(flatten_schema_types(schemas)))
    author_signals = []
    if soup.find(attrs={"rel": re.compile(r"\bauthor\b", re.I)}):
        author_signals.append("rel=author")
    if soup.find(attrs={"itemprop": re.compile(r"\bauthor\b", re.I)}):
        author_signals.append("itemprop=author")
    if soup.find("meta", attrs={"name": re.compile(r"author", re.I)}):
        author_signals.append("author meta")
    if any(re.search(r"\bby\s+[A-Z][a-z]+", p) for p in paragraphs[:12]):
        author_signals.append("possible byline in early paragraphs")
    author_schema = "Person" in schema_types or "Organization" in schema_types

    images = (soup.find_all("img"))
    images_missing_alt = [img for img in images if not img.has_attr("alt") or not str(img.get("alt", "")).strip()]
    links = soup.find_all("a", href=True)
    parsed_host = urlparse(final_url).netloc.lower()
    internal, external, broken_href = [], [], []
    for a in links:
        href = (a.get("href") or "").strip()
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        absolute = urljoin(final_url, href)
        p = urlparse(absolute)
        if p.scheme not in ("http", "https"):
            continue
        if p.netloc.lower() == parsed_host:
            internal.append({"anchor": clean_text(a)[:160], "url": absolute})
        else:
            external.append({"anchor": clean_text(a)[:160], "url": absolute})

    main_landmarks = sum(1 for x in soup.find_all(["main", "article", "nav", "header", "footer"]))
    tables = len(soup.find_all("table"))
    lists = len(soup.find_all(["ul", "ol"]))
    visible_text = main_text

    checks = []
    def add(category, name, status, points, max_points, evidence, recommendation):
        checks.append({
            "Category": category, "Check": name, "Status": status,
            "Score": points, "Max score": max_points,
            "Evidence": evidence, "Recommendation": recommendation
        })

    add("Metadata", "Title tag", "Pass" if 20 <= len(title) <= 65 else ("Warning" if title else "Fail"),
        5 if 20 <= len(title) <= 65 else (2 if title else 0), 5,
        f"{len(title)} characters: {title[:180] or 'Missing'}",
        "Write a unique, descriptive title that clearly identifies the page topic; use length as a diagnostic, not a rigid ranking rule.")
    add("Metadata", "Meta description", "Pass" if 120 <= len(description) <= 170 else ("Warning" if description else "Fail"),
        4 if 120 <= len(description) <= 170 else (2 if description else 0), 4,
        f"{len(description)} characters: {description[:220] or 'Missing'}",
        "Add a concise, page-specific summary that accurately describes the content.")
    add("Structure", "Single clear H1", "Pass" if len(h1s) == 1 else ("Warning" if h1s else "Fail"),
        5 if len(h1s) == 1 else (2 if len(h1s) > 1 else 0), 5,
        "; ".join(h1s[:3]) if h1s else "No H1 found",
        "Use a clear main heading aligned with the page's purpose. Multiple H1s are not automatically a penalty, but clarity matters.")
    heading_hierarchy = bool(headings["h2"]) and (not headings["h3"] or bool(headings["h2"]))
    add("Structure", "Descriptive subheadings", "Pass" if len(headings["h2"]) >= 2 else ("Warning" if headings["h2"] else "Fail"),
        4 if len(headings["h2"]) >= 2 else (2 if headings["h2"] else 0), 4,
        f"{len(headings['h2'])} H2s, {len(headings['h3'])} H3s",
        "Break complex content into logical sections with descriptive headings that reflect the questions readers have.")
    add("Content", "Useful content depth", "Pass" if word_count >= 500 else ("Warning" if word_count >= 200 else "Fail"),
        5 if word_count >= 500 else (3 if word_count >= 200 else 1), 5,
        f"Approximately {word_count} visible words on the page",
        "Check whether the page fully answers its intended query. Word count alone does not determine quality; short pages can be sufficient.")
    add("Content", "Answer-first opening signal", "Pass" if answer_first else "Review",
        5 if answer_first else 2, 5,
        opening_text[:350] or "No readable opening text found",
        "Consider answering the primary question directly near the start, then add evidence, context, steps, and caveats.")
    add("Content", "Scannable answer blocks", "Pass" if short_answer_paragraphs else "Review",
        4 if short_answer_paragraphs else 2, 4,
        f"{len(short_answer_paragraphs)} paragraphs in the 20–100 word range",
        "Use concise, self-contained paragraphs where appropriate. Do not shorten content artificially if a longer explanation is clearer.")
    faq_score = 4 if faq_heading or question_headings else (2 if q_marks >= 3 else 0)
    add("Content", "Question coverage / FAQ signals", "Pass" if faq_heading or question_headings else ("Review" if q_marks >= 3 else "Fail"),
        faq_score, 4,
        f"FAQ heading: {'yes' if faq_heading else 'no'}; question headings: {len(question_headings)}; question marks: {q_marks}",
        "Address relevant user questions in headings or a clearly organised Q&A section when it helps the page. FAQ markup is not required.")
    add("Trust", "Author / attribution signals", "Pass" if author_signals or author_schema else "Review",
        4 if author_signals or author_schema else 1, 4,
        ", ".join(author_signals) + ("; Person/Organization schema present" if author_schema else "") or "No obvious author signals detected in fetched HTML",
        "For topics where expertise matters, provide accurate author or organization information and appropriate editorial review details.")
    add("Structured data", "Valid JSON-LD syntax", "Pass" if schemas and not schema_errors else ("Warning" if schema_errors else "Review"),
        5 if schemas and not schema_errors else (1 if schema_errors else 2), 5,
        f"{len(schemas)} parsed JSON-LD block(s); {len(schema_errors)} syntax error(s)",
        "Validate JSON-LD syntax and test relevant types with official validators. This check does not validate every Schema.org property.")
    add("Structured data", "Descriptive schema types", "Pass" if schema_types else "Review",
        4 if schema_types else 1, 4,
        ", ".join(schema_types) if schema_types else "No schema types detected",
        "Use only schema types that accurately represent visible page content, such as Organization, Article, Product, or BreadcrumbList where appropriate.")
    add("Crawlability", "Canonical URL", "Pass" if canonical else "Review",
        4 if canonical else 1, 4,
        canonical or "No canonical link detected",
        "Confirm the canonical points to the preferred URL and is consistent with redirects, sitemap URLs, and internal links.")
    robots_value = (robots_meta + " " + googlebot_meta).lower()
    blocked = any(x in robots_value for x in ["noindex", "none"])
    add("Crawlability", "Robots meta directive", "Warning" if blocked else "Pass",
        0 if blocked else 4, 4,
        f"robots={robots_meta or 'not set'}; googlebot={googlebot_meta or 'not set'}",
        "Check that the page is intentionally indexable. This does not inspect robots.txt, HTTP headers, or search-engine access.")
    add("Accessibility", "Image alt coverage", "Pass" if not images_missing_alt else "Review",
        3 if not images_missing_alt else max(0, round(3 * (len(images)-len(images_missing_alt))/max(1,len(images)))), 3,
        f"{len(images_missing_alt)} of {len(images)} images missing or using empty alt text",
        "Write meaningful alt text for informative images and empty alt text for purely decorative images.")
    add("Technical", "Language and viewport", "Pass" if lang and viewport else "Review",
        3 if lang and viewport else (2 if lang or viewport else 0), 3,
        f"html lang={lang or 'missing'}; viewport={'present' if viewport else 'missing'}",
        "Declare the primary page language and a responsive viewport. These checks are basic diagnostics, not a full accessibility audit.")
    add("Structure", "Semantic landmarks", "Pass" if main_landmarks >= 2 else "Review",
        3 if main_landmarks >= 2 else 1, 3,
        f"{main_landmarks} main/article/nav/header/footer landmark element(s)",
        "Use semantic HTML landmarks where appropriate to make page structure clearer for assistive technology and parsers.")

    max_score = sum(c["Max score"] for c in checks)
    score = sum(c["Score"] for c in checks)
    pct = round(100 * score / max_score) if max_score else 0

    report = {
        "url": url, "final_url": final_url, "status_code": response.status_code,
        "title": title, "title_length": len(title), "meta_description": description,
        "meta_description_length": len(description), "canonical": canonical,
        "language": lang, "robots_meta": robots_meta, "googlebot_meta": googlebot_meta,
        "h1": h1s, "headings": headings, "word_count": word_count,
        "answer_first_signal": answer_first, "question_headings": question_headings,
        "faq_heading": faq_heading, "schema_types": schema_types, "schema_errors": schema_errors,
        "author_signals": author_signals, "image_count": len(images),
        "images_missing_alt": len(images_missing_alt), "internal_links": internal,
        "external_links": external, "body_text": body_text,
        "checks": checks, "score": pct, "score_points": score, "max_score": max_score,
        "response_bytes": len(response.content)
    }
    if max_internal:
        report["internal_link_sample"] = internal[:max_internal]
    else:
        report["internal_link_sample"] = []
    return report

def score_label(score):
    if score >= 85:
        return "Strong observable signals"
    if score >= 70:
        return "Good foundation; improvements remain"
    if score >= 50:
        return "Several areas need review"
    return "Significant issues to investigate"

def build_csv(report):
    return pd.DataFrame(report["checks"]).to_csv(index=False).encode("utf-8")

def make_text_report(report):
    lines = [
        "AEO READINESS AUDIT",
        f"Audited URL: {report['url']}",
        f"Final URL: {report['final_url']}",
        f"HTTP status: {report['status_code']}",
        f"Signal score: {report['score']}/100 ({score_label(report['score'])})",
        "",
        "IMPORTANT: This is a heuristic checklist of observable page signals, not a prediction of AI citations or search rankings.",
        "",
        f"Title: {report['title']}",
        f"Meta description: {report['meta_description']}",
        f"Canonical: {report['canonical'] or 'Not detected'}",
        f"Word count: {report['word_count']}",
        f"Schema types: {', '.join(report['schema_types']) or 'None detected'}",
        f"Schema syntax errors: {len(report['schema_errors'])}",
        "",
        "CHECKS"
    ]
    for c in report["checks"]:
        lines.append(f"- [{c['Status']}] {c['Check']} ({c['Score']}/{c['Max score']}): {c['Evidence']}")
        lines.append(f"  Recommendation: {c['Recommendation']}")
    if report["schema_errors"]:
        lines += ["", "JSON-LD ERRORS"] + [f"- {x}" for x in report["schema_errors"]]
    lines += ["", "H1"] + [f"- {x}" for x in report["h1"]]
    lines += ["", "H2"] + [f"- {x}" for x in report["headings"]["h2"]]
    return "\n".join(lines)

st.markdown("### Run an audit")
url_input = st.text_input("Page URL", placeholder="https://example.com/page-to-audit")
audit_clicked = st.button("Run AEO audit", type="primary", use_container_width=False)

if audit_clicked:
    normalized = normalize_url(url_input)
    if not normalized:
        st.error("Enter a valid website URL, including a domain.")
    else:
        with st.spinner("Fetching and analysing the page..."):
            try:
                report = audit_page(normalized, timeout, user_agent, max_internal)
                st.session_state["aeo_report"] = report
            except requests.exceptions.SSLError:
                st.error("TLS/SSL verification failed. Check the URL and certificate. The auditor does not disable certificate verification.")
            except requests.exceptions.Timeout:
                st.error("The page request timed out. Try again or increase the timeout.")
            except requests.exceptions.RequestException as exc:
                st.error(f"Could not fetch the page: {exc.__class__.__name__}: {exc}")
            except Exception as exc:
                st.error(f"Audit failed: {exc.__class__.__name__}: {exc}")

report = st.session_state.get("aeo_report")
if report:
    st.markdown("---")
    st.subheader("Audit summary")
    st.caption(f"Requested: {report['url']}  •  Final URL: {report['final_url']}  •  HTTP {report['status_code']}")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("AEO signal score", f"{report['score']}/100")
    c2.metric("Visible words", f"{report['word_count']:,}")
    c3.metric("Schema types", len(report["schema_types"]))
    c4.metric("Images missing alt", report["images_missing_alt"])
    st.progress(report["score"] / 100)
    st.write(f"**Interpretation:** {score_label(report['score'])}")
    st.caption("The score is a transparent, rule-based checklist score. It is not an industry standard or a model of how AI systems rank or cite pages.")

    checks_df = pd.DataFrame(report["checks"])
    tab1, tab2, tab3, tab4 = st.tabs(["Checks & fixes", "Content structure", "Schema", "Links"])
    with tab1:
        filter_status = st.multiselect("Filter checks by status", sorted(checks_df["Status"].unique()), default=sorted(checks_df["Status"].unique()))
        shown = checks_df[checks_df["Status"].isin(filter_status)].copy()
        st.dataframe(shown, use_container_width=True, hide_index=True)
    with tab2:
        st.markdown("**Title**")
        st.write(report["title"] or "No title found")
        st.markdown("**Meta description**")
        st.write(report["meta_description"] or "No meta description found")
        st.markdown("**H1 headings**")
        st.write(report["h1"] or ["No H1 detected"])
        st.markdown("**H2 headings**")
        st.write(report["headings"]["h2"] or ["No H2 headings detected"])
        st.markdown("**Question headings**")
        st.write(report["question_headings"] or ["No question-form H2/H3/H4 headings detected"])
        st.markdown("**Opening text sample**")
        st.write(" ".join(report["body_text"].split()[:120]) or "No visible text extracted")
    with tab3:
        st.write("Detected schema types:", report["schema_types"] or "None")
        if report["schema_errors"]:
            st.error("JSON-LD syntax issues detected")
            for err in report["schema_errors"]:
                st.write(f"- {err}")
        elif report["schema_types"]:
            st.success("JSON-LD blocks were parsed as JSON. Property-level schema validity was not fully tested.")
        else:
            st.info("No JSON-LD schema detected in the fetched HTML.")
        st.caption("This auditor checks JSON syntax and detects @type values. For full structured-data validation, use Schema.org and Google Rich Results testing tools.")
    with tab4:
        st.metric("Internal links detected", len(report["internal_links"]))
        st.metric("External links detected", len(report["external_links"]))
        link_df = pd.DataFrame(report["internal_link_sample"])
        if not link_df.empty:
            st.dataframe(link_df, use_container_width=True, hide_index=True)
        else:
            st.write("No internal links in the selected sample.")
    st.markdown("### Export")
    e1, e2, e3 = st.columns(3)
    e1.download_button("Download checks CSV", data=build_csv(report), file_name="aeo_audit_checks.csv", mime="text/csv")
    e2.download_button("Download text report", data=make_text_report(report).encode("utf-8"), file_name="aeo_audit_report.txt", mime="text/plain")
    e3.download_button("Download JSON", data=json.dumps({k:v for k,v in report.items() if k not in ("body_text",)}, indent=2, ensure_ascii=False).encode("utf-8"), file_name="aeo_audit_report.json", mime="application/json")

st.markdown("---")
st.markdown("### What this tool does not do")
st.markdown(
    "- It audits the HTML returned to the HTTP client; JavaScript-rendered content may be missing.\n"
    "- It does not check the site's robots.txt, HTTP `X-Robots-Tag`, live indexing status, Core Web Vitals, or actual AI citation probability.\n"
    "- It does not crawl an entire site. Run it per URL, or extend it with a sitemap/crawl module.\n"
    "- A missing signal is a prompt for human review, not automatically an SEO defect."
)
st.caption(f"AEO Readiness Auditor v{APP_VERSION} • No paid APIs required")
