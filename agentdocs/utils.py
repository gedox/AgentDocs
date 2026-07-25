"""Small URL and filesystem helpers shared across AgentDocs."""

from __future__ import annotations

import re
from urllib.parse import urldefrag, urljoin, urlparse, urlunparse


def normalize_url(url: str) -> str:
    """Canonicalize a URL for de-duplication.

    Drops the fragment, lower-cases the scheme/host, and removes a trailing
    slash (except for the root path) so that ``/a`` and ``/a/`` collapse
    together.
    """
    url, _ = urldefrag(url)
    parts = urlparse(url)
    scheme = parts.scheme.lower()
    netloc = parts.netloc.lower()
    path = parts.path or "/"
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")
    # Query is preserved: some docs sites route pages via ?page=.
    return urlunparse((scheme, netloc, path, "", parts.query, ""))


def same_site(url: str, base: str) -> bool:
    """True when *url* lives on the same host as *base*."""
    return urlparse(url).netloc.lower() == urlparse(base).netloc.lower()


def under_prefix(url: str, prefix: str) -> bool:
    """True when *url*'s path starts with *prefix*'s path (same host)."""
    if not same_site(url, prefix):
        return False
    p_url = urlparse(url).path.rstrip("/") or "/"
    p_pre = urlparse(prefix).path.rstrip("/") or "/"
    if p_pre == "/":
        return True
    return p_url == p_pre or p_url.startswith(p_pre + "/")


def absolutize(href: str, base_url: str) -> str:
    """Resolve a possibly-relative *href* against *base_url*."""
    return urljoin(base_url, href)


def is_page_link(url: str) -> bool:
    """Filter out obvious non-HTML assets and non-navigable schemes."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return False
    path = parsed.path.lower()
    bad_ext = (
        ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".ico",
        ".pdf", ".zip", ".gz", ".tar", ".mp4", ".mp3", ".woff", ".woff2",
        ".ttf", ".eot", ".css", ".js", ".json", ".xml", ".rss", ".atom",
    )
    return not path.endswith(bad_ext)


_slug_re = re.compile(r"[^a-z0-9._-]+")


def slugify(text: str, fallback: str = "index") -> str:
    """Turn arbitrary text into a safe file/dir name."""
    text = (text or "").strip().lower()
    text = text.replace(" ", "-")
    text = _slug_re.sub("-", text).strip("-.")
    return text or fallback


def url_to_relpath(url: str, prefix: str) -> str:
    """Map a page URL to a relative Markdown path mirroring the site tree.

    ``https://help.obsidian.md/plugins/graph`` under prefix ``/`` becomes
    ``plugins/graph.md``. The prefix's own path is stripped so output is not
    nested under redundant folders.
    """
    parsed = urlparse(url)
    path = parsed.path

    pre_path = urlparse(prefix).path.rstrip("/")
    if pre_path and path.startswith(pre_path):
        path = path[len(pre_path):]
    path = path.strip("/")

    if not path:
        rel = "index"
    else:
        segments = [slugify(s) for s in path.split("/") if s]
        rel = "/".join(segments) if segments else "index"

    if parsed.query:
        rel = f"{rel}-{slugify(parsed.query)}"

    return rel + ".md"
