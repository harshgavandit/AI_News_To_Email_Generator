"""Lightweight HTML conversion without document-processing models."""
from urllib.parse import urlsplit

import httpx
from bs4 import BeautifulSoup
from markdownify import markdownify

from app.news import canonical_url, fetch_bytes


def url_to_markdown(url: str, *, allowed_hosts: frozenset[str]) -> str | None:
    try:
        safe_url = canonical_url(url)
        if urlsplit(safe_url).hostname not in allowed_hosts:
            return None
        soup = BeautifulSoup(fetch_bytes(safe_url)[:2_000_000], "html.parser")
        for element in soup(["script", "style", "nav", "footer", "header"]):
            element.decompose()
        return markdownify(str(soup.find("main") or soup.find("article") or soup))[:24000]
    except (ValueError, httpx.HTTPError, OSError, TimeoutError):
        return None
