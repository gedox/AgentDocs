"""Provider for Obsidian Publish sites (help.obsidian.md and any publish.obsidian.md site).

These sites render entirely in JavaScript, so a plain HTTP GET returns only a
loader shell. However, they expose a small, stable JSON API:

* ``/options/<uid>`` — site config, including ``navigationOrdering`` (the exact
  sidebar order) and ``siteName``.
* ``/cache/<uid>``   — an object keyed by every file path in the vault; keys
  ending in ``.md`` are the documentation pages.
* ``/access/<uid>/<path>`` — the raw Markdown source of a single note.

Pulling the raw Markdown means AI agents get the original source — frontmatter,
wiki-links and all — rather than a lossy HTML-to-Markdown conversion.
"""

from __future__ import annotations

import json
import re
from typing import Optional
from urllib.parse import quote, urlparse

import requests

from ..discover import DiscoveryResult, Page

_SITEINFO_RE = re.compile(r"window\.siteInfo\s*=\s*(\{.*?\})\s*;", re.DOTALL)


def _safe_relpath(note_path: str) -> str:
    """Make a vault path safe as a local file path while staying readable."""
    illegal = '<>:"|?*'
    cleaned = "".join("-" if c in illegal else c for c in note_path)
    return cleaned


class ObsidianPublishProvider:
    name = "obsidian-publish"

    def __init__(self, start_url, session, timeout, uid, host, origin):
        self.start_url = start_url
        self.session = session
        self.timeout = timeout
        self.uid = uid
        self.host = host
        self.origin = origin  # public origin, e.g. https://help.obsidian.md

    # ------------------------------------------------------------------ #
    @classmethod
    def detect(cls, start_url, final_url, html, session, timeout) -> Optional["ObsidianPublishProvider"]:
        if not html or "publish.obsidian.md" not in html:
            return None
        match = _SITEINFO_RE.search(html)
        if not match:
            return None
        try:
            info = json.loads(match.group(1))
        except json.JSONDecodeError:
            return None
        uid = info.get("uid")
        host = info.get("host")
        if not uid or not host:
            return None
        # Base public links on the URL the user actually typed: following the
        # redirect can drop a path segment (help.obsidian.md -> obsidian.md).
        parsed = urlparse(start_url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        return cls(start_url, session, timeout, uid, host, origin)

    # ------------------------------------------------------------------ #
    def _api(self, kind: str) -> dict:
        url = f"https://{self.host}/{kind}/{self.uid}"
        resp = self.session.get(url, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    def _public_url(self, note_path: str, permalink: str = "") -> str:
        # An explicit permalink (from the note's frontmatter) is the canonical
        # public URL; otherwise fall back to the vault path minus the extension.
        path = permalink or (note_path[:-3] if note_path.lower().endswith(".md") else note_path)
        encoded = "/".join(quote(seg) for seg in path.strip("/").split("/"))
        return f"{self.origin}/{encoded}"

    def discover(self, prefix, max_pages, use_sitemap, use_crawl) -> DiscoveryResult:
        options: dict = {}
        try:
            options = self._api("options")
        except requests.RequestException:
            pass
        cache = self._api("cache")

        md_paths = [k for k in cache if k.lower().endswith(".md")]

        # Order pages by the site's own navigation ordering, then the rest.
        ordering = [p for p in options.get("navigationOrdering", []) if p.lower().endswith(".md")]
        rank = {p: i for i, p in enumerate(ordering)}
        md_paths.sort(key=lambda p: (rank.get(p, len(rank)), p.lower()))

        # Optional path-prefix filter (relative to the vault root).
        prefix_path = ""
        if prefix:
            pre = urlparse(prefix).path.strip("/")
            if pre and urlparse(prefix).netloc == urlparse(self.origin).netloc:
                prefix_path = pre.lower()

        pages: list[Page] = []
        for path in md_paths:
            if prefix_path and not path.lower().startswith(prefix_path):
                continue
            fetch_url = f"https://{self.host}/access/{self.uid}/" + quote(path)
            title = path.rsplit("/", 1)[-1][:-3]  # filename without .md
            meta = cache.get(path) or {}
            permalink = ""
            if isinstance(meta, dict):
                permalink = (meta.get("frontmatter") or {}).get("permalink", "") or ""
            pages.append(
                Page(
                    url=self._public_url(path, permalink),
                    title=title,
                    source=self.name,
                    fetch_url=fetch_url,
                    relpath=_safe_relpath(path),
                    is_markdown=True,
                )
            )
            if len(pages) >= max_pages:
                break

        return DiscoveryResult(
            start_url=self.start_url,
            prefix=prefix or self.start_url,
            pages=pages,
            provider=self.name,
            site_name=options.get("siteName", ""),
        )

    # ------------------------------------------------------------------ #
    def fetch(self, page: Page) -> tuple[str, str] | None:
        try:
            resp = self.session.get(page.content_url(), timeout=self.timeout)
        except requests.RequestException:
            return None
        if resp.status_code != 200:
            return None
        body = resp.text
        title = page.title or (page.relpath.rsplit("/", 1)[-1].removesuffix(".md"))
        header = f"<!-- AgentDocs source: {page.url} -->\n\n"
        return title, header + body.strip() + "\n"
