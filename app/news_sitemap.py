"""Bounded metadata discovery from explicitly reviewed publisher news sitemaps.

Never follows article links or arbitrary nested indexes. Only news entries with
a publisher-provided title and publication date are indexed; lastmod is not a
publication date. No article body is copied.
"""
import hashlib
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit
from xml.etree import ElementTree as ET

from app.sanitation import sanitize_text

SM = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
NEWS = "{http://www.google.com/schemas/sitemap-news/0.9}"


def parse_xml(body):
    if len(body) > 5_000_000 or b"<!DOCTYPE" in body.upper() or b"<!ENTITY" in body.upper():
        raise ValueError("Unsafe sitemap")
    return ET.fromstring(body)


def read_news_sitemap(source, fetch):
    from app.news import article_in_scope, canonical_url
    status = dict(source.public(), available=False, count=0)
    root = parse_xml(fetch(source.url))
    documents = [root]
    if root.tag == SM + "sitemapindex":
        documents = []
        seen = set()
        origin = urlsplit(source.url)
        for entry in root.findall(SM + "sitemap")[:100]:
            link = entry.findtext(SM + "loc", "")
            parsed = urlsplit(link)
            if (parsed.scheme != "https" or parsed.netloc != origin.netloc or parsed.query or parsed.fragment
                    or parsed.path not in source.sitemap_paths or link in seen):
                continue
            seen.add(link)
            documents.append(parse_xml(fetch(link)))
            if len(documents) == 4:
                break
        if not documents:
            raise ValueError("No reviewed child sitemap")
    items = {}
    observed = 0
    now = datetime.now(UTC)
    for document in documents:
        if document.tag != SM + "urlset":
            raise ValueError("Not a news sitemap")
        for entry in document.findall(SM + "url")[:2000]:
            observed += 1
            try:
                url = canonical_url(entry.findtext(SM + "loc", ""))
                if urlsplit(url).hostname.removeprefix("www.") not in {
                    host.removeprefix("www.") for host in source.hosts
                }:
                    continue
                title = sanitize_text(entry.findtext(NEWS + "news/" + NEWS + "title", ""), limit=500)
                date = entry.findtext(NEWS + "news/" + NEWS + "publication_date", "")
                published = datetime.fromisoformat(date.replace("Z", "+00:00"))
                if (not title or published.utcoffset() is None or published > now + timedelta(days=1)
                        or published < now - timedelta(days=90)):
                    continue
                keywords = entry.findtext(NEWS + "news/" + NEWS + "keywords", "")
                tags = [sanitize_text(value, limit=48) for value in keywords.split(",")[:12]]
                if not article_in_scope(source, urlsplit(url).path, title, tags):
                    continue
                ident = hashlib.sha256(url.encode()).hexdigest()[:20]
                items[ident] = dict(id=ident, url=url, title=title, description="", source=source.group,
                    source_id=source.id, publisher=source.label, kind=source.kind, category="News",
                    published_at=published.astimezone(UTC).isoformat(), tags=tags)
            except (ValueError, TypeError, AttributeError, OverflowError):
                continue
    return list(items.values()), dict(status, available=True, count=len(items), observed_entries=observed,
        rejected_entries=observed - len(items), latest_published_at=max(
            (item["published_at"] for item in items.values()), default=None))
