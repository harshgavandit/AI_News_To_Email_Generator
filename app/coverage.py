"""One classification for API filters, archives, and global edition selection."""
import re
from unicodedata import normalize
from urllib.parse import parse_qs, urlsplit

from app.sanitation import sanitize_article, sanitize_story_excerpt
from app.sources import BY_ID

TOPICS = {
    "ai": "AI & Machine Learning",
    "software": "Software & Cloud",
    "startups": "Startups & Venture",
    "security": "Cybersecurity & Privacy",
    "chips": "Chips & Hardware",
    "bigtech": "Tech Companies",
    "research": "Research & Science",
    "industry": "Industry & Policy",
    "outages": "Service Outages",
    "video": "Video",
}


def headline_pattern(pattern):
    return re.compile(rf"\b(?:{pattern})\b", re.I)


HYPHENS = str.maketrans({mark: "-" for mark in "‐‑‒–—−"})


# Headline signals take precedence over section names and feed defaults, which
# often describe a whole publisher.
STORY_SIGNALS = (
    ("outages", headline_pattern(
        r"outages?|service (?:disruptions?|interruptions?)|services? (?:go(?:es)?|went|is|are) down|"
        r"(?:aws|microsoft 365|azure|cloudflare|github|google cloud) (?:goes|went|is) down|"
        r"indisponibilidade|panne (?:informatique|majeure)|caída de (?:la plataforma|servicio)"
    )),
    ("security", headline_pattern(
        r"ransomware|cyber[ -]?(?:attacks?|security|incidents?)|data breach(?:es)?|"
        r"zero[ -]days?|0[ -]days?|vulnerabilit(?:y|ies)|cve[- ]\d{4}[- ]\d+|"
        r"threat actors?|infosec|botnets?|ddos|rootkits?|backdoors?|exploits?|cisa advisory|"
        r"remote code execution|rce|supply chain attacks?|cryptojacking|trojans?|"
        r"phishing|malware|spyware|security (?:alerts?|fix(?:es)?|patch(?:es)?|updates?)|"
        r"privacy (?:law|lawsuit|watchdog|breach)|ciberseguridad|ciber(?:ataques?|segurança)|"
        r"vazamento de dados|cybersécurité|cyberattaque|sicherheitslücke[n]?|cyberangriff(?:e)?"
    )),
    ("startups", headline_pattern(
        r"start[ -]?ups?|venture capital|seed (?:round|funding)|series[- ](?:a|b|c|d|e) (?:round|funding)|"
        r"unicorns?|decacorns?|angel (?:investing|investors?)|venture capital(?:ists)?|valuations?|"
        r"y combinator|techstars|pre-seed|term sheets?|bootstrapped|early-stage|"
        r"funding round|startup accelerator|venture fund|rodada de investimento|financiación semilla|"
        r"levée de fonds|finanzierungsrunde"
    )),
    ("industry", headline_pattern(
        r"antitrust|anti[ -]monopoly|export (?:controls?|restrictions?)|"
        r"(?:digital markets|digital services|ai) act|tech polic(?:y|ies)|"
        r"trade sanctions?|tariffs?|telecommunications? policy|copyright (?:dispute|lawsuit|infringement)|"
        r"ftc|doj|sec|european commission|cma|"
        r"(?:digital|internet) regulation|net neutrality|data sovereignty|"
        r"(?:anti)?monop[oó]lio|regulação digital|soberanía de datos|souveraineté numérique"
    )),
    ("research", headline_pattern(
        r"peer[ -]reviewed|researchers (?:develop|discover|find|introduce|publish|show|unveil)|"
        r"scientists (?:create|develop|discover|find|unveil)|(?:new )?study (?:finds|shows|suggests)|"
        r"(?:research|scientific) paper|preprints?|arxiv|quantum (?:computing|computer|network)|"
        r"algorithmic (?:breakthrough|efficiency)|benchmarks?|empirical (?:study|evaluation)|"
        r"state of the art|sota|cryptographic protocols?|"
        r"pesquisadores (?:criam|descobrem)|chercheurs (?:découvrent|développent)"
    )),
)
COMPANY = headline_pattern(
    r"alphabet|amazon|amd|anthropic|apple|asml|baidu|broadcom|bytedance|cisco|cloudflare|"
    r"crowdstrike|databricks|deepseek|google|huawei|ibm|intel|meta|microsoft|mistral|"
    r"nvidia|openai|oracle|palantir|palo alto networks|qualcomm|salesforce|samsung|sap|"
    r"snowflake|tencent|tesla|tiktok|tsmc|uber|xai|tech giant(?:s)?|chipmakers?"
)
CORPORATE_ACTION = headline_pattern(
    r"ceo|chief executive|succession|successor|shareholders?|earnings|quarterly (?:profit|revenue)|"
    r"mergers?|acquisition|acquir(?:e|es|ed|ing)|layoffs?|lay(?:s|ing)? off|laid off|"
    r"spins? off|spin[ -]?off|ipo|board of directors"
)
DOMAIN_SIGNALS = (
    ("chips", headline_pattern(
        r"semiconductors?|chip[ -]?makers?|chiplets?|chip (?:foundr(?:y|ies)|manufacturing|shortage)|"
        r"(?:ai|smartphone|custom) chips?|cpus?|gpus?|tpus?|npus?|"
        r"processors?|graphics cards?|smartphones?|laptops?|motherboards?|memory chips?|"
        r"hardware accelerators?|wearables?|foldables?|game consoles?|"
        r"tsmc|asml|lithography|wafers?|silicon|photolithography|risc-v|arm architecture|"
        r"blackwell|hopper|gaudi|quantum processors?|microarchitecture|"
        r"robotics|humanoid robots?|autonomous drones?|lidar|"
        r"semicondutores?|procesadores?|processeurs?|halbleiter|grafikkarten?"
    )),
    ("ai", headline_pattern(
        r"ai|gen[ -]?ai|artificial intelligence|machine learning|deep learning|language models?|"
        r"llms?|chatgpt|openai|anthropic|claude (?:code|models?)|google gemini|deepmind|agentic|diffusion models?|"
        r"multimodal|frontier models?|reasoning models?|rag|fine-tuning|synthetic data|embedding models?|"
        r"deepseek|mistral|grok|copilot|reinforcement learning|rlhf|"
        r"intelig[eê]ncia artificial|intelligence artificielle|künstliche intelligenz"
    )),
    ("software", headline_pattern(
        r"open[ -]source|developer tools?|software|sdk|browser|operating systems?|"
        r"linux|kubernetes|postgresql|sqlite|databases?|programming languages?|compilers?|rust|"
        r"devops|ci/cd|docker|containers?|microservices?|cloud-native|backend|frontend|"
        r"api(?:s)?|sdk(?:s)?|typescript|golang|webassembly|wasm|database engines?|redis|mongodb|graphql|git|"
        r"react (?:native|\d+)|cloud computing|serverless|infrastructure as code|"
        r"código abierto|c[oó]digo aberto|logiciel(?:s)?|code source ouvert"
    )),
    ("chips", headline_pattern(r"iphone|ipad|macbook|geforce|radeon|snapdragon|ryzen|hardware")),
)
SECTION_TOPICS = {
    "ai": "ai",
    "artificial intelligence": "ai",
    "inteligência artificial": "ai",
    "inteligencia artificial": "ai",
    "big tech": "bigtech",
    "tech companies": "bigtech",
    "cybersecurity": "security",
    "security": "security",
    "infosec": "security",
    "privacidade": "security",
    "hardware": "chips",
    "chips": "chips",
    "gadgets": "chips",
    "semiconductors": "chips",
    "robotics": "chips",
    "research": "research",
    "science": "research",
    "preprints": "research",
    "software": "software",
    "open source": "software",
    "devops": "software",
    "programming": "software",
    "developer": "software",
    "apps": "software",
    "cloud": "software",
    "startups": "startups",
    "venture capital": "startups",
    "funding": "startups",
    "venture": "startups",
    "tech policy": "industry",
    "policy": "industry",
    "telecom": "industry",
    "regulation": "industry",
}
JAPANESE_SIGNALS = (
    ("outages", re.compile(r"障害|接続できない")),
    ("security", re.compile(r"脆弱性|ランサムウェア|サイバー攻撃|情報漏えい")),
    ("startups", re.compile(r"スタートアップ|資金調達")),
    ("industry", re.compile(r"独占禁止|輸出規制")),
    ("research", re.compile(r"研究チーム|論文|量子コンピュータ")),
    ("chips", re.compile(r"半導体|スマートフォン|グラフィックスカード")),
    ("ai", re.compile(r"生成AI|人工知能|大規模言語モデル", re.I)),
    ("software", re.compile(r"オープンソース|クラウド|ソフトウェア")),
)
KOREAN_SIGNALS = (
    ("outages", re.compile(r"접속 장애|서비스 장애|먹통")),
    ("security", re.compile(r"취약점|랜섬웨어|사이버\s*공격|개인정보\s*유출")),
    ("startups", re.compile(r"스타트업|투자\s*유치")),
    ("industry", re.compile(r"독점금지|수출\s*규제")),
    ("research", re.compile(r"연구진|논문|양자컴퓨터")),
    ("chips", re.compile(r"반도체|스마트폰|그래픽카드")),
    ("ai", re.compile(r"인공지능|생성형\s*AI|거대언어모델", re.I)),
    ("software", re.compile(r"오픈소스|클라우드|소프트웨어")),
)
LOCAL_SIGNALS = {"ja": JAPANESE_SIGNALS, "ko": KOREAN_SIGNALS}


def article_source(article):
    # Earlier callers used only a source group such as OpenAI or Anthropic.
    source = BY_ID.get(article.get("source_id")) or BY_ID.get(article.get("source"))
    if source:
        return source
    group = article.get("source")
    return next((source for source in BY_ID.values() if source.group == group), None)


def topic_for(article):
    source = article_source(article)
    default = source.topic if source else "industry"
    kind = article.get("kind") or (source.kind if source else "")
    if kind == "video" or default == "video":
        return "video"
    if kind == "status" or default == "outages":
        return "outages"
    if kind == "research" or default == "research":
        return "research"
    if source and source.coverage == "advisory":
        return default

    title = normalize("NFKC", article.get("title") or "").translate(HYPHENS)
    if source:
        for topic, pattern in LOCAL_SIGNALS.get(source.language, ()):
            if pattern.search(title):
                return topic
    for topic, pattern in STORY_SIGNALS:
        if pattern.search(title):
            return topic
    if COMPANY.search(title) and CORPORATE_ACTION.search(title):
        return "bigtech"
    for topic, pattern in DOMAIN_SIGNALS:
        if pattern.search(title):
            return topic
    for tag in (article.get("category") or "").split("|"):
        if topic := SECTION_TOPICS.get(" ".join(tag.casefold().split())):
            return topic
    return default


def public_article(article):
    source = article_source(article)
    saved_topic = article.get("topic")
    topic = saved_topic if saved_topic in TOPICS else topic_for(article)
    article = sanitize_article(article)
    publisher = article.get("publisher") or (source.label if source else "")
    region = source.region if source else "Global"
    url = article.get("url", "")
    published_at = article.get("published_at", "")
    
    raw_summary = article.get("cleanSummary") or article.get("description") or article.get("summary") or ""
    if source and source.id == "hacker-news":
        raw_summary = ""  # The syndicated feed carries link labels and popularity counters.
    # Earlier releases stored a headline-derived sentence for videos with no excerpt.
    synthetic_video = article.get("source") == "youtube" and raw_summary.startswith(f"Video by {publisher} covering ")
    clean_summary = sanitize_story_excerpt("" if synthetic_video else raw_summary, article.get("source", ""),
                                           video_fallback=False)
    has_excerpt = bool(clean_summary)
    
    why_it_matters = article.get("whyItMatters", "")
    words_count = len(clean_summary.split())
    reading_time = max(1, (words_count + 199) // 200)

    private_fields = {"search_title", "search_description", "search_publisher", "topic_rank"}
    result = {key: value for key, value in article.items() if key not in private_fields}
    result.update({
        # Strict requested schema: { id, title, cleanSummary, whyItMatters, category, region, sourceName, sourceUrl, publishedAt, readingTimeMinutes }
        "id": article.get("id", ""),
        "title": article.get("title", ""),
        "cleanSummary": clean_summary,
        "whyItMatters": why_it_matters,
        "category": topic,
        "region": region,
        "region_id": region_id(region),
        "sourceName": publisher,
        "sourceUrl": url,
        "publishedAt": published_at,
        "readingTimeMinutes": reading_time,
        "has_excerpt": has_excerpt,
        # Backward compatibility properties:
        "description": clean_summary,
        "summary": clean_summary,
        "topic": topic,
        "topic_label": TOPICS.get(topic, topic.title()),
        "publisher": publisher,
        "url": url,
        "published_at": published_at,
        "coverage": source.coverage if source else "publisher",
        "language": source.language if source else "en",
    })
    if source and source.coverage == "preprint":
        result["research_status"] = "preprint"
    if article.get("kind") == "video" and len(url) <= 2048:
        thumbnail = youtube_thumbnail(url)
        if thumbnail:
            result["thumbnail_url"] = thumbnail
    return result


def youtube_thumbnail(url):
    try:
        parts = urlsplit(url)
        if parts.scheme != "https" or parts.username or parts.password or parts.port not in (None, 443):
            return None
        if parts.hostname == "youtu.be":
            video = parts.path.strip("/")
        elif parts.hostname in {"youtube.com", "www.youtube.com"} and parts.path == "/watch":
            video = parse_qs(parts.query, max_num_fields=64).get("v", [""])[0]
        else:
            return None
    except ValueError:
        return None
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", video):
        return f"https://i.ytimg.com/vi/{video}/mqdefault.jpg"


REGION_LABELS = {
    "Global": "Global publishers",
    "NA": "North America",
    "LatAm": "Latin America & Caribbean",
    "EU": "Europe",
    "Africa": "Africa",
    "MENA": "Middle East & North Africa",
    "APAC": "Asia-Pacific",
}
REGIONS = {
    "Global": {"Global"},
    "NA": {"NA", "North America"},
    "LatAm": {"LatAm", "Latin America", "Latin America & Caribbean"},
    "EU": {"EU", "Europe"},
    "Africa": {"Africa", "Sub-Saharan Africa"},
    "MENA": {"MENA", "Middle East", "North Africa", "Middle East & North Africa"},
    "APAC": {"APAC", "Asia", "India", "Asia-Pacific", "Oceania", "Australia"},
}
REGION_IDS = {label: key for key, labels in REGIONS.items() for label in labels}


def region_id(raw_region):
    return REGION_IDS.get(raw_region, "Global")


def region_matches(article, region):
    source = article_source(article)
    actual = source.region if source else "Global"
    return region in ("", "all") or region_id(actual) == region
