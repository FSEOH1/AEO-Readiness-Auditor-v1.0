"""Sitemap discovery, same-site crawling, safe fetching, and robots/rate-limit handling."""
from __future__ import annotations

import ipaddress
import socket
import time
import xml.etree.ElementTree as ET
from collections import deque
from urllib.parse import urljoin, urlparse, urldefrag
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

DEFAULT_UA = "AEO-GEO-Auditor/2.0 (+site audit; respectful crawler)"
MAX_SITEMAP_BYTES = 8 * 1024 * 1024
MAX_HTML_BYTES = 5 * 1024 * 1024


class CrawlError(Exception):
    pass


def normalize_url(url: str) -> str:
    url = (url or "").strip()
    if not url:
        raise CrawlError("Enter a URL.")
    if not url.lower().startswith(("http://", "https://")):
        url = "https://" + url
    p = urlparse(url)
    if p.scheme not in {"http", "https"} or not p.hostname:
        raise CrawlError("Only valid HTTP/HTTPS URLs are supported.")
    return url


def _public_host_check(url: str) -> None:
    """Best-effort SSRF protection: block non-public IPs and hostnames resolving to them."""
    p = urlparse(url)
    host = p.hostname
    if not host:
        raise CrawlError("URL has no hostname.")
    if host.lower() in {"localhost", "localhost.localdomain"} or host.endswith(".local"):
        raise CrawlError("Local hostnames are not allowed.")
    try:
        infos = socket.getaddrinfo(host, p.port or (443 if p.scheme == "https" else 80), type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise CrawlError(f"Hostname could not be resolved: {host}") from exc
    addresses = {info[4][0].split("%")[0] for info in infos}
    if not addresses:
        raise CrawlError("Hostname did not resolve.")
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if not ip.is_global:
            raise CrawlError("Private, loopback, link-local, and reserved network addresses are blocked.")


def _request(url: str, session: requests.Session, headers: dict, timeout: int, max_bytes: int):
    current = url
    for _ in range(6):
        _public_host_check(current)
        response = session.get(
            current, headers=headers, timeout=timeout, allow_redirects=False,
            stream=True
        )
        if response.is_redirect or response.is_permanent_redirect:
            location = response.headers.get("Location")
            response.close()
            if not location:
                raise CrawlError("Redirect response has no Location header.")
            current = urljoin(current, location)
            continue
        content = bytearray()
        for chunk in response.iter_content(chunk_size=65536):
            content.extend(chunk)
            if len(content) > max_bytes:
                response.close()
                raise CrawlError(f"Response exceeded the {max_bytes // (1024*1024)} MB size limit.")
        response._content = bytes(content)
        response._content_consumed = True
        return response
    raise CrawlError("Too many redirects.")


def get_robots_parser(base_url: str, session: requests.Session, headers: dict, timeout: int = 10):
    p = urlparse(base_url)
    robots_url = f"{p.scheme}://{p.netloc}/robots.txt"
    parser = RobotFileParser()
    parser.set_url(robots_url)
    try:
        response = _request(robots_url, session, headers, timeout, 512 * 1024)
        if response.status_code < 400:
            parser.parse(response.text.splitlines())
        else:
            # If robots.txt is unavailable, RobotFileParser's default permits crawling.
            parser.parse([])
    except Exception:
        parser.parse([])
    return parser


def _same_site(url: str, root_host: str) -> bool:
    return (urlparse(url).hostname or "").lower() == root_host.lower()


def parse_sitemap(sitemap_url: str, session: requests.Session, headers: dict, timeout: int = 15, delay: float = 0.3):
    """Return (page_urls, child_sitemaps, warnings). Handles sitemap index and urlset."""
    pages, children, warnings = [], [], []
    queue = deque([normalize_url(sitemap_url)])
    seen = set()
    while queue:
        current = queue.popleft()
        if current in seen:
            continue
        seen.add(current)
        if len(seen) > 100:
            warnings.append("Stopped after 100 sitemap files to limit unbounded sitemap-index expansion.")
            break
        try:
            _public_host_check(current)
            time.sleep(max(0, delay))
            response = _request(current, session, headers, timeout, MAX_SITEMAP_BYTES)
            response.raise_for_status()
            root = ET.fromstring(response.content)
            tag = root.tag.split("}")[-1].lower()
            locs = [e.text.strip() for e in root.iter() if e.tag.split("}")[-1].lower() == "loc" and e.text and e.text.strip()]
            if tag == "sitemapindex":
                children.extend(locs)
                queue.extend(locs)
            elif tag == "urlset":
                pages.extend(locs)
            else:
                warnings.append(f"Unrecognised XML root in {current}: {tag}")
        except Exception as exc:
            warnings.append(f"Could not parse {current}: {exc.__class__.__name__}: {exc}")
    return list(dict.fromkeys(pages)), list(dict.fromkeys(children)), warnings


def discover_urls(start_url: str, sitemap_url: str | None = None, mode: str = "Sitemap + internal links",
                  max_pages: int = 100, timeout: int = 15, delay: float = 0.5,
                  user_agent: str = DEFAULT_UA, obey_robots: bool = True,
                  progress_callback=None):
    start_url = normalize_url(start_url)
    _public_host_check(start_url)
    start = urlparse(start_url)
    origin = f"{start.scheme}://{start.netloc}"
    session = requests.Session()
    headers = {"User-Agent": user_agent, "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"}
    robots = get_robots_parser(origin, session, headers, timeout) if obey_robots else None
    if sitemap_url:
        sitemap = normalize_url(sitemap_url)
    else:
        sitemap = urljoin(origin, "/sitemap.xml")

    pages, child_maps, warnings = parse_sitemap(sitemap, session, headers, timeout, delay)
    same_pages = [u for u in pages if _same_site(u, start.netloc)]
    if mode == "Sitemap only":
        candidates = same_pages
    else:
        candidates = list(same_pages)
        candidates.insert(0, start_url)
        seen = set()
        queue = deque(candidates)
        candidates = []
        while queue and len(candidates) < max_pages:
            current = urldefrag(queue.popleft())[0]
            if current in seen or not _same_site(current, start.netloc):
                continue
            seen.add(current)
            if robots and not robots.can_fetch(user_agent, current):
                warnings.append(f"Robots.txt disallows crawl: {current}")
                continue
            candidates.append(current)
            try:
                time.sleep(max(0, delay))
                response = _request(current, session, headers, timeout, MAX_HTML_BYTES)
                if response.status_code >= 400 or "html" not in response.headers.get("Content-Type", "").lower():
                    continue
                soup = BeautifulSoup(response.text, "html.parser")
                for a in soup.find_all("a", href=True):
                    target = urldefrag(urljoin(response.url, a["href"].strip()))[0]
                    if target.startswith(("http://", "https://")) and _same_site(target, start.netloc) and target not in seen:
                        queue.append(target)
            except Exception as exc:
                warnings.append(f"Discovery fetch failed for {current}: {exc.__class__.__name__}")
            if progress_callback:
                progress_callback(len(candidates), max_pages)
        return list(dict.fromkeys(candidates))[:max_pages], warnings

    if robots:
        allowed = []
        for u in same_pages:
            if robots.can_fetch(user_agent, u):
                allowed.append(u)
            else:
                warnings.append(f"Robots.txt disallows crawl: {u}")
        same_pages = allowed
    return list(dict.fromkeys(same_pages))[:max_pages], warnings


def fetch_html(url: str, timeout: int = 15, user_agent: str = DEFAULT_UA,
               delay: float = 0.5, obey_robots: bool = True, session=None):
    """Fetch one URL safely, validating redirect destinations and enforcing response-size limits."""
    url = normalize_url(url)
    _public_host_check(url)
    session = session or requests.Session()
    headers = {"User-Agent": user_agent, "Accept": "text/html,application/xhtml+xml"}
    if obey_robots:
        robots = get_robots_parser(f"{urlparse(url).scheme}://{urlparse(url).netloc}", session, headers, timeout)
        if not robots.can_fetch(user_agent, url):
            raise CrawlError("robots.txt disallows this URL.")
    time.sleep(max(0, delay))
    response = _request(url, session, headers, timeout, MAX_HTML_BYTES)
    content_type = response.headers.get("Content-Type", "")
    if "html" not in content_type.lower() and not response.text.lstrip().lower().startswith(("<!doctype html", "<html")):
        raise CrawlError(f"URL did not return HTML (Content-Type: {content_type or 'unknown'}).")
    return response
