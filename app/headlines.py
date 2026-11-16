"""Front-page selections from recent reporting and reviewed developing stories."""
import re
from datetime import UTC, datetime, timedelta

from app.coverage import public_article
from app.intelligence import story_identity
from app.selection import words
from app.sources import BY_ID
from app.story_coverage import coverage_match, headline

HEADLINE_HOURS = 72
LEADERSHIP = re.compile(r"\b(?:ceo|chief executive|successor|succession|leadership)\b", re.I)
CHANGE = re.compile(r"\b(?:resigns?|depart\w*|steps? down|appoint\w*|replac\w*|search|transition|succession|successor)\b", re.I)
IMPACT = re.compile(
    r"\b(?:breach|outage|antitrust|regulat\w*|ransomware|acqui\w*|merger|bankrupt\w*|"
    r"export (?:controls?|curbs?|ban)|sanctions?|layoffs?|zero.day|funding|raises|recall)\b", re.I
)
COMMERCE = re.compile(r"\b(?:black friday|coupon|buying guide|best deals|prime day|hands.on review)\b", re.I)
EARNINGS = re.compile(r"\b(?:Q[1-4]|first.quarter|second.quarter|third.quarter|fourth.quarter)\b.*\b(?:revenue|profit|loss|earnings)\b", re.I)

# Review each update against the links before changing the summary or extending its end date.
COVERAGE = ({
    "id": "nvidia-ceo-search",
    "topic": "Chips & leadership",
    "title": "Nvidia’s search for a permanent CEO",
    "updated_at": "2026-11-13T20:37:00+00:00",
    "expires_at": "2026-11-20T20:37:00+00:00",
    "query": "Nvidia",
    "summary": (
        "Nvidia named CFO Colette Kress interim CEO after Jensen Huang resigned. Analysts and investors have floated "
        "Palo Alto Networks CEO Nikesh Arora, along with names such as Tim Cook and Lisa Su. Reuters relayed a report "
        "about Arm CEO Rene Haas. On November 13, Nvidia said it had not formally engaged any candidates."
    ),
    "sources": (
        {"publisher": "NVIDIA Newsroom", "label": "Official transition announcement",
         "url": "https://nvidianews.nvidia.com/news/nvidia-announces-ceo-transition"},
        {"publisher": "CBS News", "label": "Analysts discuss Nikesh Arora and other names",
         "url": "https://www.cbsnews.com/news/jensen-huang-next-nvidia-ceo-candidates"},
        {"publisher": "Axios", "label": "Executives mentioned in the succession discussion",
         "url": "https://www.axios.com/2026/11/12/nvidia-next-ceo-jensen-huang-predictions"},
        {"publisher": "Reuters via Euronext", "label": "Reported approach to Arm CEO Rene Haas",
         "url": "https://live.euronext.com/en/financial-news/nvidia-approaches-arm-ceo-haas-employees-seek-huangs-return-reports-say"},
        {"publisher": "Bloomberg", "label": "Nvidia responds to speculation about candidates",
         "url": "https://news.bloomberglaw.com/artificial-intelligence/nvidia-says-speculation-on-new-ceo-candidates-is-premature"},
    ),
},)


def active_coverage(now):
    return [{key: value for key, value in item.items() if key != "expires_at"} for item in COVERAGE
            if datetime.fromisoformat(item["updated_at"]) <= now < datetime.fromisoformat(item["expires_at"])]


def headline_score(article, now):
    title = article["title"]
    published = datetime.fromisoformat(article["published_at"])
    age = (now - published).total_seconds() / 3600
    # Recent, material changes rank ahead of routine coverage. Older follow-ups lose weight.
    if LEADERSHIP.search(title) and CHANGE.search(title):
        impact = 18
    elif IMPACT.search(title):
        impact = 10
    else:
        impact = -12 if EARNINGS.search(title) else 0
    return impact + max(0, 24 - age / 2), published, article["id"]


def build_headlines(rows, *, now=None, limit=4):
    now = now or datetime.now(UTC)
    cutoff = now - timedelta(hours=HEADLINE_HOURS)
    eligible = []
    for article in rows:
        source = BY_ID.get(article.get("source_id"))
        if (not source or source.coverage != "reporting" or article.get("kind") not in {"news", "engineering"}
                or COMMERCE.search(article["title"])):
            continue
        if cutoff <= datetime.fromisoformat(article["published_at"]) <= now:
            eligible.append(article)

    eligible.sort(key=lambda article: headline_score(article, now), reverse=True)
    coverage = active_coverage(now)
    picked, publishers, used_regions, used_topics, seen_titles = [], set(), set(), set(), []
    links, headlines = set(), []
    for unique_topic, unique_region in ((True, True), (False, True), (False, False)):
        for candidate in eligible:
            if candidate["publisher"] in publishers:
                continue
            if any(item["query"].casefold() in candidate["title"].casefold() for item in coverage):
                continue
            article = public_article(candidate)
            region = article["region_id"]
            if (unique_topic and article["topic"] in used_topics) or (unique_region and region in used_regions):
                continue
            tokens = words(article["title"])
            if any(tokens and len(tokens & old) / len(tokens | old) >= .67 for old in seen_titles):
                continue
            identity = story_identity(article)
            candidate_headline = headline(article)
            if identity in links or any(coverage_match(candidate_headline, old) for old in headlines):
                continue
            picked.append(article)
            links.add(identity)
            headlines.append(candidate_headline)
            publishers.add(article["publisher"])
            used_topics.add(article["topic"])
            used_regions.add(region)
            seen_titles.append(tokens)
            if len(picked) == limit:
                return {"coverage": coverage, "articles": picked}
    return {"coverage": coverage, "articles": picked}
