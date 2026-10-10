"""Technical checks based on the fetched response and extracted HTML."""
from urllib.parse import urlparse


def run_technical_checks(page):
    title, desc = page.get("title", ""), page.get("description", "")
    robots = (page.get("robots_meta") or "").lower()
    blocked = any(token in robots.split(",") or token in robots.split() for token in ["noindex", "none"])
    h1 = page.get("h1", [])
    headings = page.get("headings", {})
    canonical = page.get("canonical", "")
    final_host = (urlparse(page.get("url", "")).hostname or "").lower()
    canonical_host = (urlparse(canonical).hostname or "").lower() if canonical else ""
    internal = [x for x in page.get("links", []) if x["internal"]]
    external = [x for x in page.get("links", []) if not x["internal"]]
    image_total = page.get("images_count", 0)
    missing_alt = page.get("images_missing_alt", 0)
    return [
        {"category":"Metadata","check":"Title tag","status":"Pass" if 20 <= len(title) <= 65 else ("Fail" if not title else "Review"),
         "evidence":f"{len(title)} characters: {title[:200] or 'missing'}",
         "recommendation":"Use a unique, descriptive title. Character length is a diagnostic, not a strict ranking rule.",
         "severity":"high" if not title else ("low" if len(title) < 20 or len(title) > 65 else "info"), "confidence":"high"},
        {"category":"Metadata","check":"Meta description","status":"Pass" if 120 <= len(desc) <= 170 else ("Fail" if not desc else "Review"),
         "evidence":f"{len(desc)} characters: {desc[:220] or 'missing'}",
         "recommendation":"Write a unique, accurate summary that helps users understand the page.",
         "severity":"medium" if not desc else ("low" if len(desc) < 120 or len(desc) > 170 else "info"), "confidence":"high"},
        {"category":"Structure","check":"Main H1","status":"Pass" if len(h1) == 1 else ("Fail" if not h1 else "Review"),
         "evidence":" | ".join(h1[:5]) or "No H1 detected",
         "recommendation":"Provide a clear primary heading. Multiple H1s are not automatically a search penalty; inspect clarity and template consistency.",
         "severity":"medium" if not h1 else ("low" if len(h1) > 1 else "info"), "confidence":"high"},
        {"category":"Structure","check":"Descriptive H2 structure","status":"Pass" if len(headings.get("h2", [])) >= 2 else "Review",
         "evidence":f"{len(headings.get('h2', []))} H2 heading(s)",
         "recommendation":"Use descriptive sections when they improve readability and coverage; not every page needs multiple H2s.",
         "severity":"low" if len(headings.get("h2", [])) < 2 else "info", "confidence":"high"},
        {"category":"Indexability","check":"Robots meta directive","status":"Warning" if blocked else "Pass",
         "evidence":page.get("robots_meta") or "No robots/googlebot meta directive detected",
         "recommendation":"Confirm noindex is intentional. This check does not inspect X-Robots-Tag headers, robots.txt, or search engine indexing status.",
         "severity":"high" if blocked else "info", "confidence":"medium"},
        {"category":"Canonical","check":"Canonical URL present","status":"Pass" if canonical else "Review",
         "evidence":canonical or "No canonical link detected",
         "recommendation":"Check the preferred URL against redirects, internal links and sitemap URLs. A canonical is not mandatory in every scenario.",
         "severity":"medium" if not canonical else "info", "confidence":"high"},
        {"category":"Canonical","check":"Canonical host consistency","status":"Pass" if canonical and canonical_host == final_host else ("Review" if canonical else "Not assessed"),
         "evidence":f"Page host={final_host or 'unknown'}; canonical host={canonical_host or 'missing'}",
         "recommendation":"Investigate cross-host canonicals unless the cross-domain relationship is intentional.",
         "severity":"medium" if canonical and canonical_host != final_host else "info", "confidence":"medium"},
        {"category":"Accessibility","check":"Image alt attributes","status":"Pass" if missing_alt == 0 else "Review",
         "evidence":f"{missing_alt} of {image_total} images missing/empty alt attributes",
         "recommendation":"Use meaningful alt text for informative images and empty alt attributes for decorative images.",
         "severity":"low" if missing_alt else "info", "confidence":"high"},
        {"category":"Technical","check":"Language declaration","status":"Pass" if page.get("language") else "Review",
         "evidence":page.get("language") or "html lang attribute missing",
         "recommendation":"Set the correct primary language on the HTML element.",
         "severity":"low" if not page.get("language") else "info", "confidence":"high"},
        {"category":"Technical","check":"Responsive viewport","status":"Pass" if page.get("viewport") else "Review",
         "evidence":page.get("viewport") or "Viewport meta tag missing",
         "recommendation":"Confirm responsive layout and viewport configuration.",
         "severity":"low" if not page.get("viewport") else "info", "confidence":"high"},
        {"category":"Internal linking","check":"Internal links present","status":"Pass" if internal else "Review",
         "evidence":f"{len(internal)} internal link(s), {len(external)} external link(s) found in fetched HTML",
         "recommendation":"Link relevant pages with descriptive anchors where useful. This is not an orphan-page test; it examines one page at a time.",
         "severity":"low" if not internal else "info", "confidence":"high"},
    ]
