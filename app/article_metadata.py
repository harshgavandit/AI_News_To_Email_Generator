"""Bounded, untrusted publisher metadata shared by every storage mode.

Links are displayed, never fetched. Public API article bodies are not a licence
to republish full articles, so the reader uses only short supplied excerpts.
"""
import ipaddress
import hashlib
import json
from urllib.parse import urlsplit

from app.sanitation import sanitize_text

IMAGE_HOSTS = ("i.ytimg.com", "media.dev.to", "media2.dev.to", "cdn.hashnode.com",
               "images.unsplash.com", "techcrunch.com", "theverge.com", "arstechnica.com",
               "cdn.arstechnica.net", "media.wired.com", "cdn.vox-cdn.com", "platform.theverge.com")
METADATA_FIELDS = ("author", "author_url", "tags", "original_url", "discussion_url", "thumbnail_url", "points", "comments_count",
                   "reading_time_minutes", "references")


def public_link(value):
    if not isinstance(value, str) or len(value) > 2048 or any(c.isspace() or ord(c) < 32 for c in value) or "\\" in value:
        return ""
    try:
        parts = urlsplit(value)
        host = (parts.hostname or "").rstrip(".")
        if (parts.scheme != "https" or parts.username or parts.password or parts.port not in (None, 443)
                or not host.isascii() or "." not in host or host.endswith((".local", ".internal", ".localhost"))):
            return ""
        try:
            if not ipaddress.ip_address(host).is_global:
                return ""
        except ValueError:
            pass
        return value
    except ValueError:
        return ""


def safe_thumbnail(value):
    value = public_link(value)
    host = urlsplit(value).hostname or ""
    return value if host in IMAGE_HOSTS else ""


def metadata_for(article):
    """Use a small allowlist; never persist arbitrary upstream objects or HTML."""
    metadata = {}
    author = sanitize_text(article.get("author"), limit=140)
    if author:
        metadata["author"] = author
    tags = article.get("tags")
    if isinstance(tags, (tuple, list)):
        cleaned = [sanitize_text(tag, limit=48).casefold() for tag in tags[:12] if isinstance(tag, str)]
        metadata["tags"] = list(dict.fromkeys(tag for tag in cleaned if tag))
    for field in ("original_url", "discussion_url", "author_url"):
        if url := public_link(article.get(field)):
            metadata[field] = url
    references = article.get("references")
    if isinstance(references, (tuple, list)):
        links = []
        budget = 3500
        for reference in references[:8]:
            if not isinstance(reference, dict) or not (url := public_link(reference.get("url"))):
                continue
            label = sanitize_text(reference.get("label"), limit=100) or urlsplit(url).hostname
            if len(url) + len(label) > budget:
                continue
            if url not in {item["url"] for item in links}:
                links.append({"url": url, "label": label})
                budget -= len(url) + len(label)
        if links:
            metadata["references"] = links
    if thumbnail := safe_thumbnail(article.get("thumbnail_url")):
        metadata["thumbnail_url"] = thumbnail
    for field in ("points", "comments_count", "reading_time_minutes"):
        count = article.get(field)
        if type(count) is int and 0 <= count <= 10_000_000:
            metadata[field] = count
    return metadata


def restore_metadata(article):
    result = dict(article)
    payload = result.pop("metadata_json", None)
    if isinstance(payload, str) and len(payload) <= 12000:
        try:
            metadata = json.loads(payload)
            if isinstance(metadata, dict):
                result.update(metadata_for(metadata))
        except (ValueError, TypeError):
            pass
    # Reapply the allowlist to metadata carried in direct-feed and legacy rows.
    clean = metadata_for(result)
    for field in METADATA_FIELDS:
        result.pop(field, None)
    result.update(clean)
    result.pop("full_text", None)
    return result


def author_identity(article):
    """Profiles identify API authors; RSS names are scoped to their reviewed feed."""
    author = sanitize_text(article.get("author"), 140)
    if not author:
        return ""
    profile = public_link(article.get("author_url"))
    identity = profile.rstrip("/").casefold() if profile else ":".join([
        str(article.get("source_id") or article.get("source") or ""), author.casefold()])
    return "author-" + hashlib.sha256(identity.encode()).hexdigest()[:32]
