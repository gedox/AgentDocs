"""Generic provider for ordinary server-rendered HTML documentation sites."""

from __future__ import annotations

from typing import Optional

import requests

from ..convert import fetch_and_convert
from ..discover import DiscoveryResult, Page, discover


class GenericProvider:
    name = "generic"

    def __init__(self, start_url: str, session: requests.Session, timeout: float = 15.0):
        self.start_url = start_url
        self.session = session
        self.timeout = timeout

    @classmethod
    def detect(cls, start_url, final_url, html, session, timeout) -> Optional["GenericProvider"]:
        # The generic provider is the universal fallback; it always claims.
        return cls(start_url, session, timeout)

    def discover(self, prefix, max_pages, use_sitemap, use_crawl) -> DiscoveryResult:
        result = discover(
            self.start_url,
            prefix=prefix,
            timeout=self.timeout,
            max_pages=max_pages,
            use_sitemap=use_sitemap,
            use_crawl=use_crawl,
        )
        result.provider = self.name
        return result

    def fetch(self, page: Page) -> tuple[str, str] | None:
        return fetch_and_convert(self.session, page.content_url(), timeout=self.timeout)
