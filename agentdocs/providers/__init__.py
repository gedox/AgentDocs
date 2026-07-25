"""Provider selection.

A *provider* knows how to (a) enumerate the pages of a particular kind of
documentation site and (b) fetch each page's content as Markdown. The generic
provider handles ordinary HTML sites; specialised providers handle sites whose
content is loaded by JavaScript (and therefore invisible to a plain HTTP GET).
"""

from __future__ import annotations

import requests

from .base import Provider
from .generic import GenericProvider
from .obsidian import ObsidianPublishProvider

# Order matters: the first provider that claims a URL wins.
_PROVIDERS: list[type[Provider]] = [
    ObsidianPublishProvider,
    GenericProvider,  # fallback — always claims.
]


def select_provider(start_url: str, session: requests.Session, timeout: float = 15.0) -> Provider:
    """Fetch the start URL once and hand it to each provider to inspect."""
    try:
        resp = session.get(start_url, timeout=timeout, allow_redirects=True)
        html = resp.text if "html" in resp.headers.get("Content-Type", "").lower() else ""
        final_url = str(resp.url)
    except requests.RequestException:
        html, final_url = "", start_url

    for provider_cls in _PROVIDERS:
        provider = provider_cls.detect(start_url, final_url, html, session, timeout)
        if provider is not None:
            return provider
    return GenericProvider(start_url, session, timeout)  # unreachable in practice


__all__ = ["Provider", "GenericProvider", "ObsidianPublishProvider", "select_provider"]
