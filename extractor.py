"""Extract readable page data from fetched HTML."""
from __future__ import annotations
import json
import re
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup


def clean_text(node):
    return re.sub(r"\s+", " ", node.get_text(" ", strip=True)).strip() if node else ""


def meta_content(soup, name=None, prop=None):
    tag = None
    if name:
        tag = soup.find("meta", attrs={"name": re.compile(rf"^{re.escape(name)}$", re.I)})
    if prop and tag is None:
        tag = soup.find("meta", attrs={"property": re.compile(rf"^{re.escape(prop)}$", re.I)})
    return (tag.get("content") or "").strip() if tag else ""


def extract_page(response):
    original_soup = BeautifulSoup(response.text, "html.parser")
    soup = BeautifulSoup(response.text, "html.parser")
    title = clean_text(soup.title)
    description = meta_content(soup, name="description")
    canonical_tag = soup.find("link", rel=lambda v: v and "canonical" in [x.lower() for x in (v if isinstance(v, list) else str(v).split())])
    canonical = urljoin(response.url, canonical_tag.get("href", "").strip()) if canonical_tag and canonical_tag.get("href") else ""
    robots = " ".join(filter(None, [meta_content(soup, name="robots"), meta_content(soup, name="googlebot")]))
    language = (soup.html.get("lang") or "").strip() if soup.html else ""
    viewport = meta_content(soup, name="viewport")
    h1 = [clean_text(x) for x in soup.find_all("h1") if clean_text(x)]
    headings = {f"h{i}": [clean_text(x) for x in soup.find_all(f"h{i}") if clean_text(x)] for i in range(1, 7)}

    main = soup.find("main") or soup.find("article") or soup.body or soup
    main_text = clean_text(main)
    all_text_soup = BeautifulSoup(response.text, "html.parser")
    for tag in all_text_soup(["script", "style", "noscript", "svg", "template"]):
        tag.decompose()
    body_text = clean_text(all_text_soup.body or all_text_soup)
    paragraphs = [clean_text(p) for p in main.find_all("p") if clean_text(p)]
    question_headings = [clean_text(h) for h in main.find_all(["h2", "h3", "h4"]) if clean_text(h).endswith("?")]
    images = soup.find_all("img")
    missing_alt = [img for img in images if not img.has_attr("alt") or not str(img.get("alt", "")).strip()]
    links = []
    host = (urlparse(response.url).hostname or "").lower()
    for a in soup.find_all("a", href=True):
        href = a.get("href", "").strip()
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        absolute = urljoin(response.url, href)
        parsed = urlparse(absolute)
        if parsed.scheme not in {"http", "https"}:
            continue
        links.append({
            "anchor": clean_text(a)[:200],
            "url": absolute,
            "internal": (parsed.hostname or "").lower() == host,
            "rel": " ".join(a.get("rel", [])) if isinstance(a.get("rel"), list) else str(a.get("rel", "")),
        })

    schemas, schema_errors = [], []
    for idx, tag in enumerate(original_soup.find_all("script", attrs={"type": re.compile(r"application/ld\+json", re.I)}), 1):
        raw = tag.string or tag.get_text()
        try:
            schemas.append(json.loads(raw))
        except Exception as exc:
            schema_errors.append({"block": idx, "error": f"Invalid JSON ({exc.__class__.__name__})"})
    schema_types = []
    def walk(value):
        if isinstance(value, dict):
            t = value.get("@type")
            if isinstance(t, str): schema_types.append(t)
            elif isinstance(t, list): schema_types.extend(map(str, t))
            for child in value.values(): walk(child)
        elif isinstance(value, list):
            for child in value: walk(child)
    for schema in schemas:
        walk(schema)

    author_signals = []
    if original_soup.find(attrs={"rel": re.compile(r"\bauthor\b", re.I)}): author_signals.append("rel=author")
    if original_soup.find(attrs={"itemprop": re.compile(r"\bauthor\b", re.I)}): author_signals.append("itemprop=author")
    if original_soup.find("meta", attrs={"name": re.compile(r"author", re.I)}): author_signals.append("author meta")
    if "Person" in schema_types: author_signals.append("Person schema")

    return {
        "requested_url": getattr(response, "requested_url", response.url),
        "url": response.url,
        "status_code": response.status_code,
        "content_type": response.headers.get("Content-Type", ""),
        "title": title, "description": description, "canonical": canonical,
        "robots_meta": robots, "language": language, "viewport": viewport,
        "h1": h1, "headings": headings, "body_text": body_text, "main_text": main_text,
        "word_count": len(re.findall(r"\b[\w'-]+\b", body_text)),
        "paragraphs": paragraphs, "question_headings": question_headings,
        "images_count": len(images), "images_missing_alt": len(missing_alt),
        "links": links, "schemas": schemas, "schema_types": sorted(set(schema_types)),
        "schema_errors": schema_errors, "author_signals": author_signals,
        "meta_og_title": meta_content(original_soup, prop="og:title"),
        "meta_og_description": meta_content(original_soup, prop="og:description"),
        "meta_og_url": meta_content(original_soup, prop="og:url"),
    }
