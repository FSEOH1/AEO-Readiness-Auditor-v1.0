# AEO Readiness Auditor

A Streamlit app that audits a single web page for observable AEO-related content, structure, metadata, crawlability, attribution, and structured-data signals. It does not require paid APIs.

## Features
- Title and meta-description checks
- H1/H2 and heading structure checks
- Approximate visible word count
- Heuristic answer-first opening check
- Question headings and FAQ signals
- Author/attribution signals
- JSON-LD syntax parsing and schema type detection
- Canonical and robots meta checks
- Image alt coverage
- Basic language, viewport, semantic landmark checks
- Internal/external link inventory
- CSV, JSON, and text report exports

## Run locally
Python 3.10+ is recommended.

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

## Deploy to Streamlit Community Cloud
1. Create a GitHub repository.
2. Upload `app.py`, `requirements.txt`, and this README.
3. In Streamlit Community Cloud, create an app from that repository and choose `app.py`.
4. Deploy. No API secrets are needed.

## Notes and limitations
- This is a heuristic checklist, not a ranking factor model or AI citation predictor.
- It reads the HTML returned to `requests`; JavaScript-rendered content may not be present.
- It audits one URL per run and does not currently crawl a sitemap or follow links.
- It does not test robots.txt, `X-Robots-Tag`, Google indexing, Core Web Vitals, or every Schema.org property.
- Only audit pages you are authorized to access. Respect website terms, robots directives, and rate limits.
- A score of 100 is not a guarantee of AEO/GEO visibility.
