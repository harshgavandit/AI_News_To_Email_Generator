"""Reviewed feed registry. Do not make arbitrary server-side URL fetches."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Source:
    id: str
    group: str
    label: str
    kind: str
    url: str
    hosts: tuple[str, ...]
    enabled: bool = True
    topic: str = "ai"
    coverage: str = "publisher"
    region: str = "Global"
    tech_only: bool = False
    language: str = "en"
    article_paths: tuple[str, ...] = ()
    excluded_paths: tuple[str, ...] = ()

    def public(self):
        return {
            "id": self.id,
            "source": self.group,
            "label": self.label,
            "kind": self.kind,
            "feed_url": self.url,
            "enabled": self.enabled,
            "topic": self.topic,
            "coverage": self.coverage,
            "region": self.region,
            "language": self.language,
        }


def youtube(slug, name, channel):
    return Source(
        slug,
        "youtube",
        name,
        "video",
        f"https://www.youtube.com/feeds/videos.xml?channel_id={channel}",
        ("youtube.com", "youtu.be"),
        topic="video",
        coverage="reporting",
    )


def reporting(slug, name, url, *hosts, region="Global", topic="industry", tech_only=False,
              language="en", article_paths=(), excluded_paths=()):
    return Source(
        slug, slug, name, "news", url, hosts, topic=topic, coverage="reporting", region=region,
        tech_only=tech_only, language=language, article_paths=article_paths, excluded_paths=excluded_paths,
    )


def advisory(slug, name, url, *hosts, region):
    return Source(slug, slug, name, "news", url, hosts, topic="security", coverage="advisory", region=region)


def status(slug, name, url, *hosts):
    return Source(slug, slug, name, "status", url, hosts, topic="outages", coverage="status")


# Global Multi-Category Feed Matrix
DEFAULT_SOURCES = (
    # 1. AI & Frontier Labs
    Source("openai-news", "openai", "OpenAI News", "news", "https://openai.com/news/rss.xml", ("openai.com",)),
    *(Source(f"anthropic-{part}", "anthropic", f"Anthropic {part.title()}", kind,
             f"https://raw.githubusercontent.com/Olshansk/rss-feeds/main/feeds/feed_anthropic_{part}.xml",
             ("anthropic.com",)) for part, kind in (("news", "news"), ("research", "research"), ("engineering", "engineering"))),
    Source("google-deepmind", "google-deepmind", "Google DeepMind", "research", "https://deepmind.google/blog/rss.xml", ("deepmind.google", "blog.google")),
    Source("google-research", "google-research", "Google Research", "research", "https://research.google/blog/rss/", ("research.google", "research.google.com")),
    Source("meta-ai", "meta-ai", "Meta AI Engineering", "research", "https://engineering.fb.com/category/ai-research/feed/", ("engineering.fb.com",)),
    Source("hugging-face", "hugging-face", "Hugging Face Blog", "engineering", "https://huggingface.co/blog/feed.xml", ("huggingface.co",)),
    Source("arxiv-ai", "arxiv-ai", "arXiv AI", "research", "https://rss.arxiv.org/rss/cs.AI", ("arxiv.org",),
           topic="research", coverage="preprint"),
    Source("microsoft-research", "microsoft-research", "Microsoft Research", "research", "https://www.microsoft.com/en-us/research/feed/", ("microsoft.com",)),
    Source("aws-ml", "aws-ml", "AWS Machine Learning", "engineering", "https://aws.amazon.com/blogs/machine-learning/feed/", ("aws.amazon.com",)),
    Source("langchain", "langchain", "LangChain Blog", "engineering", "https://www.langchain.com/blog/rss.xml", ("langchain.com", "blog.langchain.com")),
    Source("simon-willison", "simon-willison", "Simon Willison", "engineering", "https://simonwillison.net/atom/everything/", ("simonwillison.net",)),
    Source("mistral-ai", "mistral-ai", "Mistral AI News", "news", "https://mistral.ai/news/index.xml", ("mistral.ai",), topic="ai", region="Europe"),
    Source("bair-blog", "bair-blog", "Berkeley AI Research (BAIR)", "research", "https://bair.berkeley.edu/blog/feed.xml", ("bair.berkeley.edu",), topic="research"),

    # 2. Global Tech & Industry
    reporting("techcrunch", "TechCrunch", "https://techcrunch.com/feed/", "techcrunch.com", topic="startups"),
    reporting("y-combinator", "Y Combinator Blog", "https://www.ycombinator.com/blog/rss/", "ycombinator.com", "www.ycombinator.com", topic="startups"),
    reporting("venturebeat", "VentureBeat", "https://venturebeat.com/feed/", "venturebeat.com", topic="ai"),
    reporting("the-verge", "The Verge", "https://www.theverge.com/rss/index.xml", "theverge.com", topic="bigtech"),
    reporting("ars-technica", "Ars Technica", "https://feeds.arstechnica.com/arstechnica/index", "arstechnica.com", topic="software"),
    reporting("wired", "WIRED", "https://www.wired.com/feed/rss", "wired.com", topic="industry"),
    reporting("mit-tech-review", "MIT Technology Review", "https://www.technologyreview.com/feed/", "technologyreview.com", topic="ai"),
    reporting("bbc-tech", "BBC Technology", "https://feeds.bbci.co.uk/news/technology/rss.xml", "bbc.com", "bbc.co.uk"),
    reporting("guardian-tech", "The Guardian Technology", "https://www.theguardian.com/technology/rss", "theguardian.com"),
    reporting("cbs-tech", "CBS News Technology", "https://www.cbsnews.com/latest/rss/technology", "cbsnews.com"),
    reporting("cnbc-tech", "CNBC Technology", "https://www.cnbc.com/id/19854910/device/rss/rss.html", "cnbc.com", tech_only=True),
    reporting("axios-tech", "Axios Technology Coverage", "https://api.axios.com/feed/", "axios.com", tech_only=True),
    reporting("the-register", "The Register",
              "https://api.theregister.com/api/v1/article?orderBy=published&site_id=2&remapper=rss&content=node",
              "theregister.com"),
    reporting("ieee-spectrum", "IEEE Spectrum Computing", "https://spectrum.ieee.org/feeds/topic/computing.rss",
              "spectrum.ieee.org"),
    Source("apple-newsroom", "apple-newsroom", "Apple Newsroom", "news", "https://www.apple.com/newsroom/rss-feed.rss",
           ("apple.com",), topic="bigtech"),
    Source("microsoft-source", "microsoft-source", "Microsoft Source", "news", "https://news.microsoft.com/source/feed/",
           ("news.microsoft.com", "blogs.microsoft.com", "commandline.microsoft.com", "news.xbox.com"), topic="bigtech"),
    Source("google-keyword", "google-keyword", "Google The Keyword", "news", "https://blog.google/rss/", ("blog.google",),
           topic="bigtech"),
    reporting("platformer", "Platformer", "https://www.platformer.news/rss/", "platformer.news", "www.platformer.news",
              topic="bigtech"),

    # 3. World & Regional Tech
    reporting("rest-of-world", "Rest of World", "https://restofworld.org/feed/latest/", "restofworld.org", region="Global", topic="industry"),
    Source("tech-in-asia", "tech-in-asia", "Tech in Asia", "news", "https://www.techinasia.com/feed", ("techinasia.com",), enabled=True, topic="startups", coverage="reporting", region="APAC"),
    reporting("sifted", "Sifted", "https://sifted.eu/feed", "sifted.eu", region="EU", topic="startups"),
    Source("hacker-news", "hacker-news", "Hacker News discussions", "news", "https://hnrss.org/frontpage",
           ("news.ycombinator.com",), topic="software", coverage="discussion"),
    reporting("techcabal", "TechCabal", "https://techcabal.com/feed/", "techcabal.com", region="Africa", topic="startups"),
    reporting("scmp-tech", "SCMP Technology", "https://www.scmp.com/rss/5/feed", "scmp.com", region="Asia"),
    reporting("indian-express-tech", "The Indian Express Technology", "https://indianexpress.com/section/technology/feed/", "indianexpress.com", region="India"),
    reporting("latamlist", "LatamList", "https://latamlist.com/feed/", "latamlist.com", region="Latin America", topic="startups"),
    reporting("tecnoblog", "Tecnoblog", "https://tecnoblog.net/feed/", "tecnoblog.net", region="Latin America",
              language="pt-BR", excluded_paths=("/achados/",)),
    reporting("betakit", "BetaKit", "https://betakit.com/feed/", "betakit.com", region="North America", topic="startups"),
    reporting("tech-eu", "Tech.eu", "https://tech.eu/feed/", "tech.eu", region="EU", topic="startups"),
    reporting("itweb", "ITWeb", "https://www.itweb.co.za/rss", "itweb.co.za", region="Africa"),
    reporting("inc42", "Inc42", "https://inc42.com/feed/", "inc42.com", region="India", topic="startups"),
    reporting("itnews-au", "iTnews", "https://www.itnews.com.au/RSS/rss.ashx", "itnews.com.au", region="APAC"),
    reporting("e27", "e27", "https://e27.co/index_wp.php/feed/", "e27.co", region="APAC", topic="startups"),
    reporting("tnglobal", "TNGlobal", "https://technode.global/feed/", "technode.global", region="APAC"),
    reporting("korea-times-tech", "The Korea Times Technology", "https://feed.koreatimes.co.kr/k/business.xml",
              "koreatimes.co.kr", region="Asia", tech_only=True),
    reporting("etnews-tech", "ETNews Technology", "https://rss.etnews.com/03.xml", "etnews.com",
              region="Asia", language="ko"),
    reporting("japan-today-tech", "Japan Today Technology", "https://japantoday.com/category/tech/feed",
              "japantoday.com", region="Asia"),
    reporting("reseller-nz", "Reseller News New Zealand", "https://www.reseller.co.nz/feed/", "reseller.co.nz", region="APAC"),
    reporting("heise-online", "heise online", "https://www.heise.de/rss/heise-atom.xml", "heise.de",
              region="Europe", language="de", article_paths=("/news/",)),
    reporting("le-monde-pixels", "Le Monde Pixels", "https://www.lemonde.fr/pixels/rss_full.xml", "lemonde.fr",
              region="Europe", language="fr"),
    reporting("golem-de", "Golem.de", "https://rss.golem.de/rss.php?feed=RSS2.0", "golem.de",
              region="Europe", language="de"),
    reporting("itmedia-news", "ITmedia NEWS", "https://rss.itmedia.co.jp/rss/2.0/news_bursts.xml", "itmedia.co.jp",
              region="Asia", language="ja"),
    reporting("contxto", "Contxto", "https://contxto.com/en/feed/", "contxto.com",
              region="Latin America", topic="startups"),
    reporting("xataka-mx", "Xataka México", "https://www.xataka.com.mx/feedburner.xml", "xataka.com.mx",
              region="Latin America", language="es-MX", excluded_paths=("/seleccion/", "/cine-y-tv/", "/territorio-")),
    reporting("disrupt-africa", "Disrupt Africa", "https://disruptafrica.com/feed/", "disruptafrica.com",
              region="Africa", topic="startups"),
    reporting("techafrica-news", "TechAfrica News", "https://techafricanews.com/feed/", "techafricanews.com", region="Africa"),
    reporting("the-national-tech", "The National Technology",
              "https://www.thenationalnews.com/arc/outboundfeeds/rss/category/future/technology/?outputType=xml",
              "thenationalnews.com", region="Middle East & North Africa"),
    reporting("entarabi", "entARABI", "https://entarabi.com/en/feed/", "entarabi.com",
              region="Middle East & North Africa", topic="startups"),
    reporting("wamda", "Wamda", "https://www.wamda.com/feed", "wamda.com",
              region="Middle East & North Africa", topic="startups"),
    reporting("thenextweb", "The Next Web", "https://thenextweb.com/feed", "thenextweb.com", "www.thenextweb.com",
              region="Europe", topic="startups"),
    reporting("crunchbase-news", "Crunchbase News", "https://news.crunchbase.com/feed/", "crunchbase.com", "news.crunchbase.com",
              topic="startups"),
    reporting("siliconangle", "SiliconANGLE", "https://siliconangle.com/feed/", "siliconangle.com", "www.siliconangle.com",
              topic="startups"),

    # 4. Engineering & Cloud
    Source("github-blog", "github-blog", "The GitHub Blog", "engineering", "https://github.blog/feed/", ("github.blog",), topic="software"),
    reporting("infoq", "InfoQ", "https://feed.infoq.com/", "infoq.com", topic="software"),
    Source("aws-news", "aws-news", "AWS News Blog", "engineering", "https://aws.amazon.com/blogs/aws/feed/", ("aws.amazon.com",), topic="software"),
    Source("cloudflare-blog", "cloudflare-blog", "Cloudflare Blog", "engineering", "https://blog.cloudflare.com/rss/", ("blog.cloudflare.com",), topic="software"),
    Source("vercel", "vercel", "Vercel Changelog", "engineering", "https://vercel.com/atom", ("vercel.com",), topic="software"),
    Source("kubernetes", "kubernetes", "Kubernetes Blog", "engineering", "https://kubernetes.io/feed.xml", ("kubernetes.io",), topic="software"),
    Source("postgresql", "postgresql", "PostgreSQL News", "engineering", "https://www.postgresql.org/news.rss", ("postgresql.org",), topic="software"),
    Source("docker-blog", "docker-blog", "Docker Blog", "engineering", "https://www.docker.com/blog/feed/",
           ("docker.com", "www.docker.com"), topic="software"),
    Source("golang-blog", "golang-blog", "The Go Blog", "engineering", "https://go.dev/blog/feed.atom",
           ("go.dev",), topic="software"),
    Source("mozilla-hacks", "mozilla-hacks", "Mozilla Hacks", "engineering", "https://hacks.mozilla.org/feed/",
           ("hacks.mozilla.org",), topic="software"),
    Source("arxiv-se", "arxiv-se", "arXiv Software Engineering", "research", "https://rss.arxiv.org/rss/cs.SE",
           ("arxiv.org",), topic="software", coverage="preprint"),
    Source("nvidia", "nvidia", "NVIDIA Technical Blog", "engineering", "https://developer.nvidia.com/blog/feed/", ("developer.nvidia.com",), topic="chips"),
    Source("nvidia-newsroom", "nvidia", "NVIDIA Newsroom", "news", "https://nvidianews.nvidia.com/releases.xml", ("nvidianews.nvidia.com",), topic="chips"),
    Source("arm-newsroom", "arm-newsroom", "Arm Newsroom", "news", "https://newsroom.arm.com/feed", ("newsroom.arm.com",),
           topic="chips"),
    Source("amd-newsroom", "amd-newsroom", "AMD Newsroom", "news", "https://ir.amd.com/news-events/press-releases/rss",
           ("ir.amd.com",), topic="chips"),
    reporting("semi-engineering", "Semiconductor Engineering", "https://semiengineering.com/feed/",
              "semiengineering.com", "www.semiengineering.com", topic="chips"),
    reporting("extremetech", "ExtremeTech", "https://www.extremetech.com/feed", "extremetech.com", "www.extremetech.com",
              topic="chips"),
    reporting("phoronix", "Phoronix", "https://www.phoronix.com/rss.php", "phoronix.com", topic="software"),
    reporting("techpowerup", "TechPowerUp", "https://www.techpowerup.com/rss/news", "techpowerup.com", topic="chips"),
    reporting("toms-hardware", "Tom's Hardware", "https://www.tomshardware.com/feeds/all", "tomshardware.com", "www.tomshardware.com", topic="chips"),
    Source("the-new-stack", "the-new-stack", "The New Stack", "engineering", "https://thenewstack.io/feed/", ("thenewstack.io",), topic="software"),
    Source("stackoverflow-blog", "stackoverflow-blog", "Stack Overflow Blog", "engineering", "https://stackoverflow.blog/feed/", ("stackoverflow.blog",), topic="software"),
    reporting("smashing-magazine", "Smashing Magazine", "https://www.smashingmagazine.com/feed/", "smashingmagazine.com",
              topic="software", region="Europe"),

    # Security advisories and independent cybersecurity reporting
    reporting("the-hacker-news", "The Hacker News", "https://feeds.feedburner.com/TheHackersNews",
              "thehackernews.com", "www.thehackernews.com", "feeds.feedburner.com", topic="security"),
    reporting("dark-reading", "Dark Reading", "https://www.darkreading.com/rss.xml",
              "darkreading.com", "www.darkreading.com", topic="security"),
    reporting("security-affairs", "Security Affairs", "https://securityaffairs.com/feed",
              "securityaffairs.com", "www.securityaffairs.com", topic="security", region="Europe"),
    reporting("bleepingcomputer", "BleepingComputer", "https://www.bleepingcomputer.com/feed/", "bleepingcomputer.com", topic="security"),
    reporting("securityweek", "SecurityWeek", "https://www.securityweek.com/feed/", "securityweek.com", topic="security"),
    reporting("the-record", "The Record", "https://therecord.media/feed", "therecord.media", topic="security"),
    reporting("krebs-on-security", "KrebsOnSecurity", "https://krebsonsecurity.com/feed/", "krebsonsecurity.com",
              topic="security", region="North America"),
    reporting("schneier", "Schneier on Security", "https://www.schneier.com/feed/atom/",
              "schneier.com", "www.schneier.com", topic="security", region="North America"),
    advisory("cisa-alerts", "CISA Alerts", "https://www.cisa.gov/cybersecurity-advisories/alerts.xml", "cisa.gov",
             region="North America"),
    advisory("cert-eu", "CERT-EU Advisories", "https://cert.europa.eu/publications/security-advisories-rss", "cert.europa.eu",
             region="Europe"),
    Source("arxiv-crypto", "arxiv-crypto", "arXiv Cryptography & Security", "research",
           "https://rss.arxiv.org/rss/cs.CR", ("arxiv.org",), topic="security", coverage="preprint"),

    # Research publications and research news
    Source("nature-computing", "nature-computing", "Nature Portfolio Computer Science", "research",
           "https://www.nature.com/subjects/computer-science.rss", ("nature.com",), topic="research"),
    Source("mit-robotics", "mit-robotics", "MIT News Robotics", "research", "https://news.mit.edu/topic/mitrobotics-rss.xml",
           ("news.mit.edu",), topic="research"),
    reporting("quanta-computing", "Quanta Magazine Computer Science", "https://www.quantamagazine.org/computer-science/feed/",
              "quantamagazine.org", topic="research"),
    reporting("stat-health-tech", "STAT Health Tech", "https://www.statnews.com/category/health-tech/feed/", "statnews.com",
              region="North America"),

    # 5. Creator & Video Insights
    youtube("matthew-berman", "Matthew Berman", "UCawZsQWqfGSbCI5yjkdVkTA"),
    youtube("ai-engineer", "AI Engineer", "UCLKPca3kwwd-B59HNr-_lvA"),
    youtube("karpathy", "Andrej Karpathy", "UCXUPKJO5MZQN11PqgIvyuvQ"),
    youtube("two-minute-papers", "Two Minute Papers", "UCbfYPyITQ-7l4upoX8nvctg"),
    youtube("hugging-face-video", "Hugging Face on YouTube", "UCHlNU7kIZhRgSbhHvFoy72w"),

    # Cloud & Outage Monitors
    status("azure-status", "Microsoft Azure Status", "https://rssfeed.azure.status.microsoft/en-us/status/feed/", "azure.status.microsoft", "status.azure.com", "rssfeed.azure.status.microsoft"),
    status("google-cloud-status", "Google Cloud Status", "https://status.cloud.google.com/feed.atom", "status.cloud.google.com"),
    status("cloudflare-status", "Cloudflare Status", "https://www.cloudflarestatus.com/api/v3/incidents.rss", "cloudflarestatus.com"),
    status("github-status", "GitHub Status", "https://www.githubstatus.com/history.rss", "githubstatus.com"),
)

BY_ID = {source.id: source for source in DEFAULT_SOURCES}
GROUPS = tuple(dict.fromkeys(s.group for s in DEFAULT_SOURCES))
KINDS = ("all", "news", "research", "engineering", "video", "status")
LANGUAGES = {code: label for code, label in (
    ("en", "English"), ("fr", "French"), ("de", "German"), ("ja", "Japanese"), ("ko", "Korean"),
    ("pt-BR", "Portuguese (Brazil)"), ("es-MX", "Spanish (Mexico)"),
) if any(source.language == code for source in DEFAULT_SOURCES)}
