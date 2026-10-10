# AEO/GEO Readiness Auditor — Site-wide Edition

A modular Streamlit application for site-wide AEO/GEO-related content and technical checks. It uses no paid external APIs.

## Modules
- `crawler.py`: XML sitemap parsing, internal link discovery, request pacing, robots.txt checks, response size limits, redirect validation and best-effort SSRF protection.
- `extractor.py`: HTML, headings, text, links, metadata, author signals and JSON-LD extraction.
- `checks_content.py`: answer-first signals, question coverage, concise paragraphs, source/freshness wording and repeated paragraphs.
- `checks_technical.py`: titles, descriptions, headings, robots meta, canonicals, image alt, language, viewport and link signals.
- `checks_schema.py`: JSON-LD syntax parsing and basic schema type checks.
- `scoring.py`: transparent score, priorities and summary counts.
- `database.py`: SQLite audit history, page results and issue records.
- `app.py`: Streamlit UI, crawl controls, results, history and CSV/JSON/Excel exports.

## Run locally
Python 3.10+ recommended.

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

## Deploy on Streamlit Community Cloud
1. Create a GitHub repository.
2. Upload all `.py` files, `requirements.txt`, and `README.md` to the repository root.
3. In Streamlit Community Cloud, create an app from the repository and set `app.py` as the entry point.
4. Deploy. No API secrets are required.

## Responsible use
- Audit only websites you own or are authorised to test.
- Keep the page limit modest and delay between requests.
- Respect site terms and robots.txt.
- The crawler uses best-effort SSRF protection; infrastructure-level egress controls are still recommended for a public deployment.
- Community Cloud local SQLite storage may not be durable across restarts/redeploys. For reliable historical tracking, configure a persistent managed database.

## Limitations
- Fetches server-returned HTML; does not execute JavaScript.
- No Core Web Vitals, search engine index-status, or live AI citation measurement.
- JSON-LD validation is syntax/basic-type checking, not a complete Schema.org validator.
- Scoring is heuristic and does not predict rankings or AI citations.
