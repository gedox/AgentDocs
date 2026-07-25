"""The Provider interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

import requests

from ..discover import DiscoveryResult, Page


class Provider(ABC):
    """Base class for documentation providers.

    Subclasses implement :meth:`detect` (cheap classification from an
    already-fetched start page), :meth:`discover` (enumerate pages), and
    :meth:`fetch` (retrieve one page as ``(title, markdown)``).
    """

    #: Human-readable name, shown to the user.
    name: str = "generic"

    def __init__(self, start_url: str, session: requests.Session, timeout: float = 15.0):
        self.start_url = start_url
        self.session = session
        self.timeout = timeout

    @classmethod
    @abstractmethod
    def detect(
        cls,
        start_url: str,
        final_url: str,
        html: str,
        session: requests.Session,
        timeout: float,
    ) -> Optional["Provider"]:
        """Return an instance if this provider can handle the site, else None."""

    @abstractmethod
    def discover(
        self, prefix: str | None, max_pages: int, use_sitemap: bool, use_crawl: bool
    ) -> DiscoveryResult:
        """Enumerate the site's pages."""

    @abstractmethod
    def fetch(self, page: Page) -> tuple[str, str] | None:
        """Return ``(title, markdown)`` for *page*, or None on failure."""
