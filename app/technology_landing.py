"""Public, source-linked landing pages for the reviewed technology catalog."""

from datetime import datetime
from html import escape
from string import Template
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy.exc import SQLAlchemyError

from app import technology
from app.brand import NAME, PUBLIC_SITE
from app.launch_store import get_store

router = APIRouter(include_in_schema=False)
DIRECTORY = "/technologies"
BRIEF = "/?view=briefing#daily-delivery"
GUIDES = {
    "kubernetes": (
        "Kubernetes releases, upgrades and security advisories",
        "Check new Kubernetes releases and advisories together. For an upgrade, start with release notes and removed APIs, then check the advisory’s affected version range against your cluster.",
    ),
    "postgresql": (
        "PostgreSQL releases and security updates",
        "Follow PostgreSQL release announcements and reporting. When a fix is announced, identify your major version first and check which minor release contains the fix.",
    ),
    "nodejs": (
        "Node.js releases and security updates",
        "Track Node.js releases, LTS updates and security announcements. Check which release line your deployment uses before choosing a runtime update.",
    ),
    "rust": (
        "Rust releases and compiler updates",
        "Follow Rust releases and reporting about the compiler, Cargo and the standard library. Read the release notes before changing your project’s minimum supported Rust version.",
    ),
    "google-cloud": (
        "Google Cloud outages and service updates",
        "Follow Google Cloud incidents and related reporting. Open the provider status entry to verify which service, region and time window are affected.",
    ),
    "openai": (
        "OpenAI news and API updates",
        "Track OpenAI product announcements and independent reporting. For an integration change, check the original announcement for model availability, API changes and rollout details.",
    ),
}
REFERENCES = {
    "kubernetes": (
        "Deprecated API migration guide",
        "https://kubernetes.io/docs/reference/using-api/deprecation-guide/",
    ),
    "postgresql": (
        "PostgreSQL versioning policy",
        "https://www.postgresql.org/support/versioning/",
    ),
    "nodejs": (
        "Node.js release and support schedule",
        "https://nodejs.org/en/about/previous-releases",
    ),
    "rust": ("Rust release notes", "https://doc.rust-lang.org/releases.html"),
    "google-cloud": ("Google Cloud Service Health", "https://status.cloud.google.com/"),
    "openai": (
        "OpenAI API changelog",
        "https://developers.openai.com/api/docs/changelog",
    ),
}

PAGE = Template("""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>$title · Informa AI</title>
  <meta name="description" content="$description" />
  <link rel="canonical" href="$canonical" />
  <meta property="og:type" content="website" />
  <meta property="og:site_name" content="Informa AI" />
  <meta property="og:title" content="$title · Informa AI" />
  <meta property="og:description" content="$description" />
  <meta property="og:url" content="$canonical" />
  <meta property="og:image" content="$image" />
  <meta name="twitter:card" content="summary_large_image" />
  <link rel="icon" href="/informa-ai-icon.png" type="image/png" />
  <link rel="stylesheet" href="/styles.css" />
  <link rel="stylesheet" href="/foundations.css" />
  <link rel="stylesheet" href="/research.css" />
  <script src="/theme.js"></script>
  <script defer src="/analytics.js"></script>
</head>
<body>
  <a class="skip" href="#technology-main">Skip to content</a>
  <header class="site-header">
    <div class="wrap topbar">
      <a class="brand" href="/"><img class="brand-icon" src="/informa-ai-icon.png" width="32" height="32" alt="" /><span class="brand-name">Informa AI</span></a>
      <nav class="site-nav" aria-label="Main navigation"><a href="/#reading-room">Reading Room</a><a href="/technologies">Technologies</a><a href="/sources.html">Sources</a></nav>
    </div>
  </header>
  <main class="wrap research-main" id="technology-main">
    $breadcrumb
    <header class="research-header">
      <h1 id="technology-title">$title</h1>
      <p>$description</p>
      <p><a href="$brief">Get the free daily tech brief ↗</a></p>
    </header>
    $content
  </main>
  <footer class="wrap site-footer"><a href="/about.html">About</a> · <a href="/trust.html">Source standards</a> · <a href="/privacy.html">Privacy &amp; controls</a></footer>
</body>
</html>
""")


def _page(path, title, description, content, *, technology_label=None):
    trail = [(NAME, "/"), ("Technologies", DIRECTORY)]
    if technology_label:
        trail.append((technology_label, path))
    items = []
    for position, (label, href) in enumerate(trail, 1):
        items.append(
            '<span itemprop="itemListElement" itemscope itemtype="https://schema.org/ListItem">'
            f'<a itemprop="item" href="{escape(href)}"><span itemprop="name">{escape(label)}</span></a>'
            f'<meta itemprop="position" content="{position}" /></span>'
        )
    breadcrumb = (
        '<nav aria-label="Breadcrumb" itemscope itemtype="https://schema.org/BreadcrumbList">'
        + ' <span aria-hidden="true">/</span> '.join(items)
        + "</nav>"
    )
    return HTMLResponse(
        PAGE.substitute(
            title=escape(title),
            description=escape(description),
            canonical=escape(PUBLIC_SITE + path),
            image=escape(PUBLIC_SITE + "/edition-city.jpg"),
            brief=escape(BRIEF),
            breadcrumb=breadcrumb,
            content=content,
        ),
        headers={
            "Cache-Control": "public, max-age=60",
            "Vercel-CDN-Cache-Control": "public, s-maxage=300, stale-while-revalidate=900",
        },
    )


def _directory_links(current=None):
    return "".join(
        f'<li><a href="{DIRECTORY}/{slug}">{escape(title)}</a></li>'
        for slug, (title, _) in GUIDES.items()
        if slug != current
    )


@router.get(DIRECTORY)
def directory():
    return _page(
        DIRECTORY,
        "Technology trackers",
        "Find release notes, security advisories, service incidents and reporting by technology. Each tracker links to its original sources.",
        f'<section class="research-panel"><h2>Browse by technology</h2><ul>{_directory_links()}</ul>'
        '<p><a href="/technology.html">Browse the full technology catalog</a></p></section>',
    )


def _archive(slug):
    try:
        store = get_store()
        if store:
            return technology.eligible_rows(store, slug, 720, limit=8)
    except SQLAlchemyError:
        return None
    return None


def _source_links(records):
    links = []
    for record in records or ():
        url = urlsplit(record["url"])
        if url.scheme not in {"https", "http"} or not url.hostname:
            continue
        stamp = datetime.fromisoformat(record["published_at"])
        links.append(
            f'<li><p><a href="{escape(record["url"])}">{escape(record["title"])}</a><br />'
            f'<span class="research-meta">{escape(record["publisher"])} · '
            f'<time datetime="{stamp.date().isoformat()}">{stamp:%d %b %Y}</time></span></p></li>'
        )
    return (
        "<ol>" + "".join(links) + "</ol>"
        if links
        else "<p>No recent records are available in this view. Use the official site or explore the wider timeline.</p>"
    )


@router.get(DIRECTORY + "/{slug}")
def tracker(slug: str):
    if slug not in GUIDES:
        raise HTTPException(404, "Technology tracker not found.")
    title, description = GUIDES[slug]
    entity = technology.TECHNOLOGIES[slug]
    label, reference = REFERENCES[slug]
    content = (
        f'<section class="research-panel"><h2>Recent source links</h2>{_source_links(_archive(slug))}'
        f'<p><a class="button primary" href="/technology.html?tech={slug}">Open the full timeline</a> '
        f'<a href="{escape(reference)}">{escape(label)} ↗</a></p></section>'
        f'<section class="research-panel"><h2>More technology trackers</h2><ul>{_directory_links(slug)}</ul></section>'
    )
    return _page(
        f"{DIRECTORY}/{slug}", title, description, content, technology_label=entity.name
    )
