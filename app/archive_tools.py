"""Shared archive reads for MCP and internal research. No outbound I/O."""

from urllib.parse import quote

from app.brand import PUBLIC_SITE
from app.coverage import public_article
from app.launch_store import Store


def story_url(ident: str) -> str:
    return f"{PUBLIC_SITE}/?article={quote(ident, safe='')}#reading-room"


def search_news(
    store: Store,
    *,
    query: str,
    topic: str,
    region: str = "",
    days: int,
    limit: int,
    excerpts_only: bool = False,
) -> list[dict]:
    page = store.page(
        hours=days * 24,
        query=query,
        source="all",
        kind="all",
        publisher="",
        topic=topic,
        region=region,
        sort="relevance",
        limit=limit,
        cursor=None,
        language="en" if excerpts_only else "",
        archive_only=excerpts_only,
    )
    return [public_article(row) for row in page["articles"]]
