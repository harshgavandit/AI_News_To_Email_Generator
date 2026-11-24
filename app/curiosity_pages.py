"""Shareable, server-rendered pages for single Curiosity Cards, and a sitemap of reviewed cards.

Each card gets a stable URL (/cards/<id>) whose HTML already contains the title, summary, reviewed breakdown
and source link, plus Open Graph and JSON-LD metadata. Links shared in chat apps and search results then show
the story itself without running JavaScript. Every value is HTML-escaped; nothing is fetched from publishers.
"""
from html import escape
import json
from typing import Annotated

from fastapi import APIRouter, Path, Request
from fastapi.responses import HTMLResponse, Response

from app.brand import PUBLIC_SITE
from app.curiosity import CURATED_CURIOSITY, FORMATS, PROBLEM_LABELS, THEME_LABELS
from app.curiosity_api import CARD_ID, find_card

router = APIRouter()

STYLESHEETS = ("styles.css", "launch.css", "workspace.css", "foundations.css", "polish.css", "curiosity-page.css",
               "system.css", "command.css", "orbital.css", "signature.css")


def card_url(ident):
    return f"{PUBLIC_SITE}/cards/{ident}"


def _safe_http(url):
    return url if isinstance(url, str) and url.startswith("https://") else ""


def _json_ld(card, url):
    data = {
        "@context": "https://schema.org", "@type": "Article", "headline": card.get("title", "")[:200],
        "description": card.get("summary", "")[:500], "url": url, "mainEntityOfPage": url,
        "isBasedOn": _safe_http(card.get("url")), "publisher": {"@type": "Organization", "name": "Informa AI"},
        "about": [THEME_LABELS.get(theme, theme) for theme in card.get("themes") or []],
    }
    if card.get("published_at"):
        data["datePublished"] = str(card["published_at"])[:10]
    if card.get("author"):
        data["author"] = [{"@type": "Person", "name": name.strip()} for name in str(card["author"]).split("·") if name.strip()]
    # No "<", ">" or "&" reaches the script element, so card text can never close it or open a comment.
    return json.dumps(data, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def _head(title, description, url, *, card=None, robots="index, follow"):
    tags = [
        '<meta charset="utf-8" />', '<meta name="viewport" content="width=device-width,initial-scale=1" />',
        '<meta name="theme-color" content="#f3f7fc" />', f'<meta name="robots" content="{robots}" />',
        f"<title>{escape(title)}</title>", f'<meta name="description" content="{escape(description, quote=True)}" />',
        f'<link rel="canonical" href="{escape(url, quote=True)}" />',
        '<meta property="og:site_name" content="Informa AI" />', '<meta property="og:type" content="article" />',
        f'<meta property="og:title" content="{escape(title, quote=True)}" />',
        f'<meta property="og:description" content="{escape(description, quote=True)}" />',
        f'<meta property="og:url" content="{escape(url, quote=True)}" />',
        f'<meta property="og:image" content="{PUBLIC_SITE}/edition-city.jpg" />',
        '<meta name="twitter:card" content="summary_large_image" />',
        '<script defer src="/analytics.js"></script>', '<link rel="icon" href="/informa-ai-icon.png" type="image/png" />',
        '<script src="/theme.js"></script>',
        *(f'<link rel="stylesheet" href="/{sheet}" />' for sheet in STYLESHEETS),
        '<script type="module" src="/curiosity-card.js"></script>',
        '<script defer src="/system.js"></script>', '<script defer src="/ambient.js"></script>',
    ]
    if card:
        tags.append(f'<script type="application/ld+json">{_json_ld(card, url)}</script>')
    return "\n    ".join(tags)


HEADER = """<a class="skip" href="#card">Skip to the story</a>
    <header class="site-header">
      <div class="topbar wrap">
        <a class="brand" href="/" aria-label="Informa AI home"><img class="brand-icon" src="/informa-ai-icon.png" width="32" height="32" alt="" /><span class="brand-name">Informa AI</span></a>
        <nav class="site-nav" aria-label="Main navigation">
          <a href="/#reading-room">Reading Room</a>
          <a href="/curiosity.html" aria-current="page">Curiosity Cards</a>
          <a href="/research.html">Research Desk</a>
          <a href="/sources.html">Sources</a>
        </nav>
        <div class="site-tools"><a class="button primary" href="/#composer">Build a brief</a></div>
      </div>
    </header>"""

FOOTER = """<footer class="site-footer wrap">
      <div class="footer-brand-col"><a class="footer-brand" href="/">Informa AI</a></div>
      <nav class="footer-nav" aria-label="Footer">
        <a href="/curiosity.html">Curiosity Cards</a><a href="/research.html">Research Desk</a>
        <a href="/sources.html">Source Directory</a><a href="/privacy.html">Privacy &amp; controls</a><a href="/trust.html">Source standards</a>
      </nav>
    </footer>"""


def render_card_page(card):
    ident = card["id"]
    url = card_url(ident)
    title = f"{card.get('title', 'Curiosity Card')} · {card.get('company') or card.get('publisher') or 'Engineering'} | Curiosity Cards"
    description = card.get("summary") or card.get("description") or "An engineering story from Curiosity Cards."
    source = _safe_http(card.get("url"))
    labels = [FORMATS.get(card.get("format"), ""), *(THEME_LABELS.get(theme, "") for theme in (card.get("themes") or [])[:2]),
              *(PROBLEM_LABELS.get(problem, "") for problem in (card.get("problems") or [])[:1])]
    meta = "".join(f'<li>{escape(label)}</li>' for label in labels if label)
    byline = " · ".join(part for part in (card.get("author"), card.get("publisher_detail") or card.get("publisher")) if part)
    breakdown = card.get("breakdown") if isinstance(card.get("breakdown"), dict) else None
    rows = ""
    if breakdown and all(breakdown.get(key) for key in ("problem", "approach", "result")):
        rows = '<dl class="curiosity-breakdown">' + "".join(
            f'<div class="curiosity-breakdown-row curiosity-breakdown-{key}"><dt>{label}</dt><dd>{escape(breakdown[key])}</dd></div>'
            for key, label in (("problem", "The problem"), ("approach", "What they did"), ("result", "The result"))) + "</dl>"
    why = f'<p class="curiosity-why"><strong>Why read it </strong>{escape(card["why_read"])}</p>' if card.get("why_read") else ""
    question = f'<p class="curiosity-question"><span>Answers </span>{escape(card["question"])}</p>' if card.get("question") else ""
    related = "".join(
        f'<li><a class="curiosity-related-link" href="/cards/{escape(item["id"], quote=True)}" data-related="{escape(item["id"], quote=True)}">'
        f'{escape(item["title"])}</a><span class="curiosity-related-company"> · {escape(item.get("company") or "")}</span></li>'
        for item in card.get("related") or [] if isinstance(item, dict) and item.get("id") and item.get("title"))
    related_block = (f'<div class="curiosity-related"><p class="curiosity-related-label">Read next</p>'
                     f'<ul class="curiosity-related-list">{related}</ul></div>') if related else ""
    minutes = card.get("read_minutes") if isinstance(card.get("read_minutes"), int) else None
    date = str(card.get("published_at") or card.get("year") or "")[:10]
    read_link = (f'<a class="button primary" href="{escape(source, quote=True)}" target="_blank" rel="noopener noreferrer" '
                 f'data-card-source>Read at {escape(card.get("publisher") or "the original source")} ↗</a>') if source else ""
    return f"""<!doctype html>
<html lang="en">
  <head>
    {_head(title, description[:300], url, card=card)}
  </head>
  <body>
    {HEADER}
    <main class="wrap curiosity-page curiosity-card-page" id="card" data-card-id="{escape(ident, quote=True)}">
      <nav class="curiosity-card-crumbs" aria-label="Breadcrumb"><a href="/curiosity.html">Curiosity Cards</a><span aria-hidden="true"> / </span><span>{escape(card.get('company') or 'Story')}</span></nav>
      <article class="curiosity-card curiosity-card-feature" data-curiosity-id="{escape(ident, quote=True)}">
        <div class="curiosity-card-top"><span class="curiosity-company">{escape(card.get('company') or card.get('publisher') or 'Technology')}</span>{f'<time class="curiosity-year" datetime="{escape(date, quote=True)}">{escape(date)}</time>' if date else ''}</div>
        {f'<ul class="curiosity-card-labels">{meta}</ul>' if meta else ''}
        <h1 class="curiosity-card-title">{escape(card.get('title', ''))}</h1>
        {question}
        {f'<p class="curiosity-byline">{escape(byline)}</p>' if byline else ''}
        <p class="curiosity-summary">{escape(description)}</p>
        {rows}
        {why}
        {related_block}
        <div class="curiosity-card-footer">
          {f'<span class="curiosity-reading-time">{minutes} min read</span>' if minutes else ''}
          <div class="curiosity-card-share">{read_link}<button type="button" class="button secondary" data-card-share hidden>Share</button></div>
        </div>
        <p class="curiosity-card-status small" role="status" aria-live="polite"></p>
      </article>
      <p class="curiosity-card-note small">Summarised from the original source by Informa AI. The full story, and every claim in it, belongs to the publisher.</p>
      <p><a class="text-button" href="/curiosity.html">Explore all Curiosity Cards →</a></p>
    </main>
    {FOOTER}
  </body>
</html>
"""


def render_missing_page(ident):
    return f"""<!doctype html>
<html lang="en">
  <head>
    {_head("Story not found | Curiosity Cards", "This Curiosity Card is no longer in the collection.", card_url(ident), robots="noindex")}
  </head>
  <body>
    {HEADER}
    <main class="wrap curiosity-page curiosity-card-page" id="card">
      <h1>That story has left the collection</h1>
      <p>Curiosity Cards whose source pages move or close are removed. Browse the rest of the collection instead.</p>
      <p><a class="button primary" href="/curiosity.html">Explore Curiosity Cards</a></p>
    </main>
    {FOOTER}
  </body>
</html>
"""


@router.get("/cards/{card_id}", response_class=HTMLResponse, include_in_schema=False)
def card_page(card_id: Annotated[str, Path(max_length=96, pattern=CARD_ID)]):
    card = find_card(card_id)
    if not card:
        return HTMLResponse(render_missing_page(card_id), status_code=404, headers={"Cache-Control": "public, max-age=300"})
    return HTMLResponse(render_card_page(card), headers={"Cache-Control": "public, max-age=600, stale-while-revalidate=3600"})


@router.get("/sitemap-cards.xml", include_in_schema=False)
def cards_sitemap(request: Request):
    """Reviewed cards only: their summaries were written by an editor from the source."""
    urls = "".join(f"<url><loc>{escape(card_url(seed['id']))}</loc></url>" for seed in CURATED_CURIOSITY)
    body = f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>\n'
    return Response(body, media_type="application/xml", headers={"Cache-Control": "public, max-age=86400"})
