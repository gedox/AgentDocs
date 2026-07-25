"""Fetch a page and convert its main content to clean Markdown."""

from __future__ import annotations

import re

import requests
from bs4 import BeautifulSoup, Tag
from markdownify import markdownify as md

from .discover import DEFAULT_HEADERS

# Elements that are chrome, not content.
_STRIP_TAGS = ["script", "style", "noscript", "svg", "form", "iframe"]
_STRIP_ROLES = {"navigation", "banner", "contentinfo", "search", "complementary"}
# Candidate containers for the primary article, best first.
_CONTENT_SELECTORS = [
    "main article",
    "article",
    "main",
    '[role="main"]',
    ".markdown",
    ".theme-doc-markdown",
    ".content",
    "#content",
    ".doc-content",
]


def _clean_dom(root: Tag) -> None:
    for tag in root.find_all(_STRIP_TAGS):
        tag.decompose()
    for tag in root.find_all(attrs={"role": True}):
        if tag.get("role") in _STRIP_ROLES:
            tag.decompose()
    for tag in root.find_all(["nav", "header", "footer", "aside"]):
        tag.decompose()


def _pick_content(soup: BeautifulSoup) -> Tag:
    for selector in _CONTENT_SELECTORS:
        node = soup.select_one(selector)
        if node and node.get_text(strip=True):
            return node
    # Fallback: the <body>, or the densest <div>.
    body = soup.body or soup
    candidates = body.find_all("div")
    if candidates:
        best = max(candidates, key=lambda d: len(d.get_text(strip=True)))
        if len(best.get_text(strip=True)) > len(body.get_text(strip=True)) * 0.5:
            return best
    return body


def _extract_title(soup: BeautifulSoup, content: Tag) -> str:
    h1 = content.find("h1") or soup.find("h1")
    if h1:
        return h1.get_text(strip=True)
    if soup.title and soup.title.string:
        return soup.title.string.strip()
    return ""


def html_to_markdown(html: str, source_url: str) -> tuple[str, str]:
    """Return ``(title, markdown)`` for a page's HTML."""
    soup = BeautifulSoup(html, "lxml")
    content = _pick_content(soup)
    title = _extract_title(soup, content)
    _clean_dom(content)

    body_md = md(
        str(content),
        heading_style="ATX",
        bullets="-",
    ).strip()

    # Drop empty-text links such as header "permalink" anchors: [](#foo ...).
    body_md = re.sub(r"\[\]\([^)]*\)", "", body_md)

    # Collapse runs of blank lines.
    lines: list[str] = []
    blank = 0
    for line in body_md.splitlines():
        if line.strip():
            blank = 0
            lines.append(line.rstrip())
        else:
            blank += 1
            if blank <= 1:
                lines.append("")
    body_md = "\n".join(lines).strip()

    header = f"---\nsource: {source_url}\n---\n\n"
    if title and not body_md.lstrip().startswith("# "):
        header += f"# {title}\n\n"

    return title, header + body_md + "\n"


def fetch_and_convert(
    session: requests.Session, url: str, timeout: float = 15.0
) -> tuple[str, str] | None:
    """Download *url* and convert it. Returns ``(title, markdown)`` or None."""
    try:
        resp = session.get(url, timeout=timeout, allow_redirects=True)
    except requests.RequestException:
        return None
    if resp.status_code != 200 or "html" not in resp.headers.get("Content-Type", "").lower():
        return None
    return html_to_markdown(resp.text, url)


def make_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(DEFAULT_HEADERS)
    return session
