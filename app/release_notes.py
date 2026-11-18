"""Index dated updates from reviewed, publisher-provided Markdown changelogs."""
from datetime import UTC, datetime, timedelta
import hashlib
import re

from app.sanitation import sanitize_story_excerpt, sanitize_text

DATED = re.compile(r"^#{2,3} ([A-Za-z]+ \d{1,2}, \d{4})\s*$", re.M)


def read_release_notes(source, fetch):
    text = fetch(source.url).decode("utf-8")
    if len(text) > 1_000_000 or "<html" in text[:500].casefold():
        raise ValueError("Expected a bounded Markdown changelog")
    headings = list(DATED.finditer(text))[:120]
    now = datetime.now(UTC)
    rows = []
    for index, heading in enumerate(headings):
        published = datetime.strptime(heading[1], "%B %d, %Y").replace(tzinfo=UTC)
        if not now - timedelta(days=90) <= published <= now:
            continue
        end = headings[index + 1].start() if index + 1 < len(headings) else len(text)
        section = text[heading.end():end]
        bullets = re.split(r"(?m)^\* ", section)[1:]
        for bullet in bullets[:12]:
            # Display one short publisher excerpt and link to the complete dated section.
            clean = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", bullet.split("\n\n", 1)[0])
            clean = sanitize_text(clean.replace("`", "").replace("**", ""), limit=2000)
            if not clean:
                continue
            summary = sanitize_story_excerpt(clean, source.group, video_fallback=False)
            title = f"{source.label}: {clean.split('. ', 1)[0][:160]}"
            anchor = heading[1].lower().replace(",", "").replace(" ", "-")
            url = source.url.removesuffix(".md") + "#" + anchor
            ident = hashlib.sha256(f"{source.id}:{heading[1]}:{clean[:120]}".encode()).hexdigest()[:20]
            rows.append(dict(id=ident, title=title, description=summary, url=url, source=source.group,
                source_id=source.id, publisher=source.label, kind=source.kind, category="News",
                published_at=published.isoformat(), publication_date_precision="day"))
    if not headings:
        raise ValueError("No dated changelog sections")
    return rows, dict(source.public(), available=True, count=len(rows), observed_entries=len(rows), rejected_entries=0)
