"""Discover the set of documentation pages reachable from a start URL.

Two complementary strategies are used and merged:

1. ``sitemap.xml`` (via ``robots.txt`` or common locations) — the most
   reliable way to enumerate every page a site publishes.
2. A breadth-first crawl of in-page links, restricted to the same host and
   under the start URL's path prefix — this captures sidebar/nav trees even
   when a site has no sitemap.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Iterable
from urllib.parse import urlparse
from xml.etree import ElementTree

import requests
from bs4 import BeautifulSoup

from .utils import (
    absolutize,
    is_page_link,
    normalize_url,
    same_site,
    under_prefix,
)

DEFAULT_HEADERS = {
    "User-Agent": "AgentDocs/0.1 (+https://github.com/; documentation archiver)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


@dataclass
class Page:
    """A single discovered page.

    ``url`` is the human-facing page URL (used for display and the index).
    ``fetch_url`` is where content is actually retrieved from — usually the
    same, but providers like Obsidian Publish point it at a raw-content
    endpoint. ``relpath`` lets a provider override the output path; when empty
    the CLI derives one from the URL.
    """

    url: str
    title: str = ""
    source: str = "crawl"  # "sitemap", "crawl", or a provider name
    fetch_url: str = ""
    relpath: str = ""
    is_markdown: bool = False  # True when fetch_url returns raw Markdown

    def content_url(self) -> str:
        return self.fetch_url or self.url


@dataclass
class DiscoveryResult:
    start_url: str
    prefix: str
    pages: list[Page] = field(default_factory=list)
    provider: str = "generic"
    site_name: str = ""


def _get(session: requests.Session, url: str, timeout: float) -> requests.Response | None:
    try:
        resp = session.get(url, timeout=timeout, allow_redirects=True)
        if resp.status_code == 200:
            return resp
    except requests.RequestException:
        return None
    return None


# --------------------------------------------------------------------------- #
# Sitemap discovery
# --------------------------------------------------------------------------- #
def _sitemap_candidates(base: str) -> list[str]:
    parsed = urlparse(base)
    root = f"{parsed.scheme}://{parsed.netloc}"
    return [
        f"{root}/sitemap.xml",
        f"{root}/sitemap_index.xml",
        f"{root}/sitemap-index.xml",
    ]


def _sitemaps_from_robots(session: requests.Session, base: str, timeout: float) -> list[str]:
    parsed = urlparse(base)
    robots = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    resp = _get(session, robots, timeout)
    if not resp:
        return []
    found = []
    for line in resp.text.splitlines():
        if line.lower().startswith("sitemap:"):
            found.append(line.split(":", 1)[1].strip())
    return found


def _parse_sitemap(text: str) -> tuple[list[str], list[str]]:
    """Return (page_urls, nested_sitemap_urls) from a sitemap document."""
    pages: list[str] = []
    nested: list[str] = []
    try:
        root = ElementTree.fromstring(text.encode("utf-8"))
    except ElementTree.ParseError:
        return pages, nested

    def _localname(tag: str) -> str:
        return tag.rsplit("}", 1)[-1]

    tag = _localname(root.tag)
    for loc in root.iter():
        if _localname(loc.tag) != "loc" or not (loc.text and loc.text.strip()):
            continue
        url = loc.text.strip()
        if tag == "sitemapindex":
            nested.append(url)
        else:
            pages.append(url)
    return pages, nested


def discover_from_sitemap(
    session: requests.Session, start_url: str, prefix: str, timeout: float, max_sitemaps: int = 25
) -> list[Page]:
    seeds = _sitemaps_from_robots(session, start_url, timeout) + _sitemap_candidates(start_url)
    seen_maps: set[str] = set()
    queue = deque(seeds)
    page_urls: set[str] = set()

    while queue and len(seen_maps) < max_sitemaps:
        sm = queue.popleft()
        if sm in seen_maps:
            continue
        seen_maps.add(sm)
        resp = _get(session, sm, timeout)
        if not resp:
            continue
        pages, nested = _parse_sitemap(resp.text)
        for n in nested:
            if n not in seen_maps:
                queue.append(n)
        page_urls.update(pages)

    result = []
    for u in page_urls:
        if is_page_link(u) and under_prefix(u, prefix):
            result.append(Page(url=normalize_url(u), source="sitemap"))
    return result


# --------------------------------------------------------------------------- #
# Link crawl
# --------------------------------------------------------------------------- #
def _extract_links(html: str, page_url: str) -> Iterable[str]:
    soup = BeautifulSoup(html, "lxml")
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        yield absolutize(href, page_url)


def _page_title(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    if soup.title and soup.title.string:
        return soup.title.string.strip()
    h1 = soup.find("h1")
    if h1:
        return h1.get_text(strip=True)
    return ""


def discover_from_crawl(
    session: requests.Session,
    start_url: str,
    prefix: str,
    timeout: float,
    max_pages: int,
    known_titles: dict[str, str] | None = None,
) -> list[Page]:
    known_titles = known_titles if known_titles is not None else {}
    start = normalize_url(start_url)
    seen: set[str] = {start}
    order: list[str] = [start]
    queue: deque[str] = deque([start])

    while queue and len(order) < max_pages:
        current = queue.popleft()
        resp = _get(session, current, timeout)
        if not resp or "html" not in resp.headers.get("Content-Type", "").lower():
            continue
        known_titles.setdefault(current, _page_title(resp.text))
        for link in _extract_links(resp.text, current):
            norm = normalize_url(link)
            if norm in seen:
                continue
            if not (is_page_link(norm) and same_site(norm, start) and under_prefix(norm, prefix)):
                continue
            seen.add(norm)
            order.append(norm)
            queue.append(norm)

    return [Page(url=u, title=known_titles.get(u, ""), source="crawl") for u in order]


# --------------------------------------------------------------------------- #
# Public entry point
# --------------------------------------------------------------------------- #
def discover(
    start_url: str,
    prefix: str | None = None,
    timeout: float = 15.0,
    max_pages: int = 500,
    use_sitemap: bool = True,
    use_crawl: bool = True,
) -> DiscoveryResult:
    start_url = normalize_url(start_url)
    prefix = normalize_url(prefix) if prefix else start_url

    session = requests.Session()
    session.headers.update(DEFAULT_HEADERS)

    by_url: dict[str, Page] = {}

    if use_sitemap:
        for p in discover_from_sitemap(session, start_url, prefix, timeout):
            by_url[p.url] = p

    if use_crawl:
        titles: dict[str, str] = {}
        for p in discover_from_crawl(session, start_url, prefix, timeout, max_pages, titles):
            existing = by_url.get(p.url)
            if existing:
                if not existing.title and p.title:
                    existing.title = p.title
            else:
                by_url[p.url] = p

    pages = sorted(by_url.values(), key=lambda p: p.url)[:max_pages]
    return DiscoveryResult(start_url=start_url, prefix=prefix, pages=pages)
