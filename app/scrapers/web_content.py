"""Lightweight HTML conversion without document-processing models."""
import requests
from bs4 import BeautifulSoup
from markdownify import markdownify


def url_to_markdown(url: str) -> str | None:
    try:
        response = requests.get(url, timeout=15, headers={"User-Agent": "AI-Brief/1.0"})
        response.raise_for_status()
        soup = BeautifulSoup(response.content[:2_000_000], "html.parser")
        for element in soup(["script", "style", "nav", "footer", "header"]):
            element.decompose()
        return markdownify(str(soup.find("main") or soup.find("article") or soup))[:24000]
    except requests.RequestException:
        return None
