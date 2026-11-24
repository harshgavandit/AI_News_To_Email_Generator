"""Trackers: daily reference boards built from what the sweeps already stored.

- AI models: model launches named in official lab posts and reporting.
- Incidents: provider status pages and outage reporting.
- Security: advisories and exploited vulnerabilities, grouped by CVE.
- Releases: the latest version of each tracked open-source project.

Everything is detected from headlines and publisher excerpts, so each entry links to its sources and
the page says so. Nothing here calls a model.
"""
from datetime import UTC, datetime
import re

from fastapi import APIRouter, HTTPException, Query, Request, Response
from app.cache import Cache
from app.coverage import public_article
from app.feeds import latin_headline
from app.launch_store import articles, get_store
from app.sources import BY_ID

router = APIRouter()
_tracker_cache = Cache("trackers-v1")
TRACKER_TTL = 600

AI_LABS = ("openai-news", "anthropic-news", "anthropic-research", "google-deepmind", "google-gemini", "meta-ai",
           "mistral-news", "qwen-official", "hugging-face", "microsoft-research", "nvidia-ai-blog", "nvidia-newsroom",
           "aws-ml", "amazon-science", "ollama-blog")
MODEL = re.compile(
    r"\b(?:GPT-?\d+(?:\.\d+)?(?:[- ](?:mini|nano|pro|turbo|o))?|o[1-9](?:-(?:mini|pro))?|"
    r"Claude(?: (?:Opus|Sonnet|Haiku))? ?\d+(?:\.\d+)?(?: (?:Opus|Sonnet|Haiku))?|"
    r"Gemini(?: \d+(?:\.\d+)?)(?: (?:Pro|Flash|Ultra|Nano|Flash-Lite))?|Gemma ?\d+(?:\.\d+)?[a-z]?|"
    r"Llama ?\d+(?:\.\d+)?|Mistral (?:Large|Medium|Small)(?: \d+(?:\.\d+)?)?|Magistral|Codestral|Devstral|"
    r"Qwen ?\d+(?:\.\d+)?(?:-\w+)?|DeepSeek[- ](?:V|R)\d+(?:\.\d+)?|Grok ?\d+(?:\.\d+)?|Phi-?\d+(?:\.\d+)?|"
    r"Nemotron(?:[- ]\w+)?|Sora ?\d?|Veo ?\d+|Imagen ?\d+|Kimi K\d+(?:\.\d+)?|GLM-?\d+(?:\.\d+)?)\b")
# Lab model names change every few months, so besides the known families accept any capitalised name
# that carries a version or a parameter count ("Gemini 4 Neon", "Inkling 2 Mini", "DaisyRose-27B").
GENERIC_MODEL = re.compile(
    r"\b[A-Z][A-Za-z]+(?:[ -][A-Z][A-Za-z]+){0,2}[ -]v?\d+(?:\.\d+)?B?(?:[ -](?:[A-Z][a-z]+|Mini|Pro|Flash|Max|Lite|Ultra|Nano|Omni))?\b"
    r"|\b[A-Z][A-Za-z]+-\d+(?:\.\d+)?B\b")
NOT_IN_NAMES = {"that", "the", "a", "an", "with", "for", "and", "of", "to", "in", "on", "runs", "model", "models", "upgraded",
                "layers", "parameters", "version", "update", "ai"}
LAUNCH_VERBS = {"releases", "launches", "unveils", "debuts", "introduces", "ships", "announces", "introducing", "welcome", "meet"}
LEAD_WORDS = {"introducing", "welcome", "meet", "announcing", "presenting", "releases", "launches", "unveils", "debuts",
              "openai", "google", "anthropic", "meta", "microsoft", "nvidia", "amazon", "aws", "alibaba", "apple", "the", "new"}
OFFICIAL_LAUNCH = re.compile(r"^(?:Introducing|Welcome|Meet|Announcing|Presenting)\b|^[A-Z][^:]{1,40}\d[^:]{0,20}:|\b(?:is|are) (?:now )?(?:available|here|live)\b|"
                             r"\b(?:launch\w*|releas\w*|unveil\w*)\b", re.I)
MODEL_WORDS = re.compile(r"\b(?:models?|LLMs?|open[- ]weights?|parameters?|\d+(?:\.\d+)?B)\b", re.I)
LAUNCH = re.compile(r"\b(?:launch\w*|releas\w*|introduc\w*|unveil\w*|announc\w*|debut\w*|now available|open[- ]sourc\w*|"
                    r"ships?|rolls? out|available (?:in|on|today)|meet|new model|model card|preview|expands?|upgrades?)\b", re.I)
OUTAGE = re.compile(r"\b(?:outage|down|disruption|degraded|unavailable|incident|elevated error|latency|restored)\b", re.I)
SECURITY = re.compile(r"\b(?:CVE-\d{4}-\d{4,}|vulnerabilit\w*|zero[- ]day|exploit\w*|ransomware|breach|patch\w*|advisory)\b", re.I)
EXPLOITED = re.compile(r"\b(?:actively exploited|exploited in the wild|in-the-wild|zero[- ]day|known exploited|KEV)\b", re.I)
CVE = re.compile(r"\bCVE-\d{4}-\d{4,7}\b", re.I)
VERSION = re.compile(r"(?<![\w.])v?(\d{1,4})\.(\d{1,8})(?:\.(\d{1,5}))?(?:[-.+ ]?((?:rc|beta|alpha|preview|pre|dev|nightly|canary)[\w.]*))?",
                     re.I)
PRERELEASE_TAG = re.compile(r"(?:rc|beta|alpha|preview|nightly|canary|dev)\.?\d*$", re.I)
STATES = (("resolved", re.compile(r"\b(?:resolved|restored|recovered|completed)\b", re.I)),
          ("monitoring", re.compile(r"\bmonitoring\b", re.I)),
          ("identified", re.compile(r"\b(?:identified|mitigat\w*|fix(?:ing)? (?:is )?being)\b", re.I)),
          ("investigating", re.compile(r"\b(?:investigating|degraded|disruption|outage|elevated|unavailable|partial)\b", re.I)))
KINDS = {"ai-models": ("AI model releases", 30), "incidents": ("Tech incident board", 7),
         "security": ("Security advisories & exploited bugs", 14), "releases": ("Major software releases", 21)}
NOTICE = "Detected automatically from headlines and publisher excerpts. Open the sources to confirm details."


def archive():
    store = get_store()
    if not store:
        raise HTTPException(503, "Trackers are unavailable right now.")
    return store


def rows(store, days, *, coverage="", source_ids=(), topic="all", limit=600, now=None):
    statement = store.query(days * 24, coverage=coverage, topic=topic, now=now)
    if source_ids:
        statement = statement.where(articles.c.source_id.in_(source_ids))
    statement = statement.order_by(articles.c.published_at.desc(), articles.c.id).limit(limit)
    with store.engine.connect() as conn:
        found = [public_article(dict(row)) for row in conn.execute(statement).mappings()]
    return [row for row in found if latin_headline(row["title"])]


def link(row):
    source = BY_ID.get(row.get("source_id"))
    return {"id": row["id"], "title": row["title"], "url": row.get("original_url") or row["sourceUrl"],
            "publisher": row["sourceName"], "published_at": row["publishedAt"],
            "official": bool(source and source.coverage in {"publisher", "release", "status", "advisory"})}


def model_key(name):
    return re.sub(r"[\s_-]+", " ", name.casefold()).strip()


def generic_names(title):
    names = []
    for match in GENERIC_MODEL.finditer(title):
        words = match.group(0).split(" ")
        verbs = [index for index, word in enumerate(words[:-1]) if word.casefold() in LAUNCH_VERBS]
        if verbs:  # "Baseten Releases Bison-1" names Bison-1
            words = words[verbs[-1] + 1:]
        while len(words) > 1 and words[0].casefold() in LEAD_WORDS:
            words.pop(0)
        while len(words) > 1 and words[-1].casefold() in {"model", "models", "update"}:
            words.pop()
        name = " ".join(words)
        if NOT_IN_NAMES & {word.casefold() for word in re.split(r"[ -]", name)}:
            continue
        number = re.search(r"\d+", name)
        if number and not 1990 <= int(number.group(0)) <= 2100 and re.search(r"[A-Za-z]{2}", name):
            names.append(name)
    return names


def model_names(row, official):
    """Model names a headline announces, or [] when it is not a launch."""
    title = row["title"]
    known = [match.group(0) for match in MODEL.finditer(title)]
    if official:
        return list(dict.fromkeys(known + generic_names(title))) if OFFICIAL_LAUNCH.search(title) else []
    if not LAUNCH.search(title + " " + (row.get("cleanSummary") or "")[:200]):
        return []
    if known:  # keep only fuller forms of a known name ("GPT-6.2 Sol"), not other capitalised phrases
        generic = [name for name in generic_names(title) if any(model_key(name).startswith(model_key(base)) for base in known)]
    else:
        generic = generic_names(title) if MODEL_WORDS.search(title) else []
    return list(dict.fromkeys(known + generic))


def ai_models(store, days, now=None):
    official = rows(store, days, source_ids=AI_LABS, now=now)
    reporting = rows(store, days, coverage="reporting", topic="ai", now=now)
    official_ids = {row["id"] for row in official}
    groups = {}
    for row in [*official, *reporting]:
        names = model_names(row, row["id"] in official_ids)
        if not names:
            continue
        # One row can announce several models; group under each, most specific name first.
        for name in sorted(names, key=len, reverse=True):
            if any(model_key(other).startswith(model_key(name)) and other != name for other in names):
                continue  # "Gemini 4" when the headline also names "Gemini 4 Neon"
            add_model(groups, name, row)
    return finish_models(groups)


def add_model(groups, name, row):
    key = model_key(name)
    if key not in groups:  # "GPT-6.2" joins "GPT-6.2 Astra"; "Thinking Machines Inkling 2 Mini" joins "Inkling 2 Mini"
        key = next((existing for existing in groups if existing.startswith(key + " ") or key.endswith(" " + existing)
                    or existing.endswith(" " + key)), key)
    entry = groups.setdefault(key, {"name": name, "sources": [], "publishers": set(), "first_seen": row["publishedAt"]})
    if row["id"] in {item["id"] for item in entry["sources"]}:
        return
    entry["sources"].append(link(row))
    entry["publishers"].add(row.get("publisher_family") or row["sourceName"])
    entry["first_seen"] = min(entry["first_seen"], row["publishedAt"])


def finish_models(groups):
    items = []
    for entry in groups.values():
        sources = sorted(entry["sources"], key=lambda item: (not item["official"], item["published_at"]))
        items.append({"name": entry["name"], "first_seen": entry["first_seen"], "latest": max(item["published_at"] for item in sources),
                      "official": sources[0]["official"], "outlets": len(entry["publishers"]), "headline": sources[0],
                      "sources": sources[:5]})
    items.sort(key=lambda item: item["latest"], reverse=True)
    return items[:60]


def incident_state(text):
    return next((state for state, pattern in STATES if pattern.search(text)), "update")


def incidents(store, days, now=None):
    status = rows(store, days, coverage="status", now=now)
    providers = {}
    for row in status:
        provider = providers.setdefault(row["source_id"], {"provider": row["sourceName"].removesuffix(" Status"),
                                                           "source_id": row["source_id"], "updates": []})
        provider["updates"].append({**link(row), "state": incident_state(row["title"] + " " + (row.get("cleanSummary") or ""))})
    boards = sorted(providers.values(), key=lambda item: item["updates"][0]["published_at"], reverse=True)
    for board in boards:
        board["open"] = board["updates"][0]["state"] not in {"resolved", "update"}
        board["updates"] = board["updates"][:6]
    news = [link(row) for row in rows(store, min(days, 3), coverage="reporting", now=now)
            if OUTAGE.search(row["title"]) and (row.get("category") == "outages" or "outage" in row["title"].casefold())]
    return {"providers": boards, "reporting": news[:20]}


def security(store, days, now=None):
    advisories = rows(store, days, coverage="advisory", now=now)
    reporting = [row for row in rows(store, days, coverage="reporting", topic="security", now=now) if SECURITY.search(row["title"])]
    by_cve, other = {}, []
    advisory_ids = {row["id"] for row in advisories}
    for row in [*advisories, *reporting]:
        text = row["title"] + " " + (row.get("cleanSummary") or "")
        ids = list(dict.fromkeys(match.group(0).upper() for match in CVE.finditer(text)))
        exploited = bool(EXPLOITED.search(text))
        if not ids:
            if row["id"] in advisory_ids and SECURITY.search(row["title"]):
                other.append({**link(row), "exploited": exploited})
            continue
        for ident in ids[:3]:
            entry = by_cve.setdefault(ident, {"cve": ident, "exploited": False, "sources": [], "publishers": set(),
                                              "latest": row["publishedAt"]})
            entry["exploited"] |= exploited
            if row["id"] not in {item["id"] for item in entry["sources"]}:
                entry["sources"].append(link(row))
            entry["publishers"].add(row.get("publisher_family") or row["sourceName"])
            entry["latest"] = max(entry["latest"], row["publishedAt"])
    cves = [{"cve": entry["cve"], "exploited": entry["exploited"], "latest": entry["latest"], "outlets": len(entry["publishers"]),
             "headline": sorted(entry["sources"], key=lambda item: not item["official"])[0], "sources": entry["sources"][:5]}
            for entry in by_cve.values()]
    cves.sort(key=lambda item: (item["exploited"], item["outlets"], item["latest"]), reverse=True)
    return {"cves": cves[:80], "advisories": other[:40]}


def parse_version(title):
    match = VERSION.search(title)
    if not match:
        return None
    major, minor, patch, pre = match.group(1), match.group(2), match.group(3), match.group(4)
    if int(major) > 2100:
        return None
    level = ("calendar" if int(major) >= 1990 or int(minor) >= 1990 else "major" if minor == "0" and patch in (None, "0")
             else "minor" if patch in (None, "0") else "patch")
    return {"version": match.group(0).lstrip("vV").strip(), "level": level, "prerelease": bool(pre)}


def releases(store, days, now=None):
    projects = {}
    for row in rows(store, days, coverage="release", limit=1500, now=now):
        parsed = parse_version(row["title"])
        if not parsed or row["source_id"] in projects:
            continue  # newest first, so the first stable match is the latest release
        tag = link(row)["url"].rsplit("/", 1)[-1]
        if parsed["prerelease"] or PRERELEASE_TAG.search(tag):
            continue
        source = BY_ID.get(row["source_id"])
        projects[row["source_id"]] = {"project": (source.label if source else row["sourceName"]).removesuffix(" releases").removesuffix(" Releases"),
                                      "source_id": row["source_id"], **parsed, "release": link(row)}
    items = sorted(projects.values(), key=lambda item: item["release"]["published_at"], reverse=True)
    return items


BUILDERS = {"ai-models": ai_models, "incidents": incidents, "security": security, "releases": releases}


def build(kind, days, store=None, now=None):
    store = store or archive()
    data = BUILDERS[kind](store, days, now=now)
    return {"kind": kind, "title": KINDS[kind][0], "days": days, "notice": NOTICE,
            "generated_at": (now or datetime.now(UTC)).isoformat(timespec="seconds"), "items": data}


@router.get("/api/trackers/{kind}")
def tracker(request: Request, response: Response, kind: str,
            days: int | None = Query(default=None, ge=1, le=30)):
    if kind not in KINDS:
        raise HTTPException(404, "Unknown tracker.")
    days = days or KINDS[kind][1]
    key = f"{kind}:{days}"
    cached, _ = _tracker_cache.get(key)
    if cached is None:
        cached = build(kind, days)
        _tracker_cache.put(key, cached, ttl=TRACKER_TTL, stale=0)
    response.headers["Cache-Control"] = "public, max-age=120"
    response.headers["Vercel-CDN-Cache-Control"] = "public, s-maxage=300, stale-while-revalidate=900"
    return cached


@router.get("/api/trackers")
def tracker_index(response: Response):
    response.headers["Cache-Control"] = "public, max-age=3600"
    return {"trackers": [{"id": kind, "title": title, "default_days": days} for kind, (title, days) in KINDS.items()],
            "notice": NOTICE}

