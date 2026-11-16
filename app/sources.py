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
    integration: str = "rss"
    author_name: str = ""
    author_url: str = ""

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
            "integration": self.integration,
            "reading_policy": "excerpt",
            "author_name": self.author_name,
            "author_url": self.author_url,
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


def releases(slug, name, url, host, *, article_paths=()):
    return Source(slug, slug, name, "engineering", url, (host,), topic="software", coverage="release",
                  article_paths=article_paths)


def article_feed(slug, name, url, *hosts, group=None, topic="software", author_name="", author_url="",
                 region="Global", language="en"):
    if group == "medium":
        hosts = ("medium.com", *hosts)
    return Source(slug, group or slug, name, "engineering", url, hosts, topic=topic, coverage="article",
                  author_name=author_name, author_url=author_url, region=region, language=language)


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

    # 2. Global Tech & Industry
    reporting("techcrunch", "TechCrunch", "https://techcrunch.com/feed/", "techcrunch.com", topic="startups"),
    reporting("y-combinator", "Y Combinator Blog", "https://www.ycombinator.com/blog/rss/", "ycombinator.com", "www.ycombinator.com", topic="startups"),
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
    Source("hacker-news", "hacker-news", "Hacker News", "news", "https://hacker-news.firebaseio.com/v0/topstories.json",
           ("news.ycombinator.com",), topic="software", coverage="discussion", integration="hacker-news-api"),
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
    reporting("canaltech", "Canaltech", "https://canaltech.com.br/rss/", "canaltech.com.br",
              region="Latin America", language="pt-BR",
              article_paths=("/apps/", "/ciencia/", "/hardware/", "/inteligencia-artificial/", "/internet/",
                             "/mercado/", "/seguranca/", "/smartphone/", "/software/", "/tablet/", "/telecom/")),
    reporting("fayerwayer", "FayerWayer", "https://www.fayerwayer.com/arc/outboundfeeds/rss/?outputType=xml",
              "fayerwayer.com", region="Latin America", language="es-419",
              article_paths=("/ciencia/", "/internet/", "/moviles/", "/tecnologia/")),
    reporting("the-national-tech", "The National Technology",
              "https://www.thenationalnews.com/arc/outboundfeeds/rss/category/future/technology/?outputType=xml",
              "thenationalnews.com", region="Middle East & North Africa"),
    reporting("entarabi", "entARABI", "https://entarabi.com/en/feed/", "entarabi.com",
              region="Middle East & North Africa", topic="startups"),
    reporting("entarabi-ar", "entARABI (العربية)", "https://entarabi.com/feed/", "entarabi.com",
              region="Middle East & North Africa", topic="startups", language="ar", excluded_paths=("/en/",)),
    reporting("aitnews", "AITnews (البوابة التقنية)", "https://aitnews.com/feed/", "aitnews.com",
              region="Middle East & North Africa", language="ar"),
    reporting("technews-tw-chips", "TechNews 科技新報 — Semiconductors", "https://technews.tw/category/semiconductor/feed/",
              "technews.tw", region="Asia", topic="chips", language="zh-TW"),
    reporting("xataka-es", "Xataka España", "https://www.xataka.com/feedburner.xml", "xataka.com", region="Europe",
              language="es-ES", excluded_paths=("/seleccion/", "/magnet/", "/cine-y-tv/", "/ecologia-y-naturaleza/")),
    reporting("numerama", "Numerama", "https://www.numerama.com/feed/", "numerama.com", region="Europe", language="fr",
              article_paths=("/tech/", "/cyberguerre/", "/sciences/", "/vroom/")),
    reporting("tweakers", "Tweakers", "https://tweakers.net/feeds/nieuws.xml", "tweakers.net", region="Europe",
              language="nl", article_paths=("/nieuws/",)),
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
    article_feed("cncf-blog", "Cloud Native Computing Foundation", "https://www.cncf.io/blog/feed/", "cncf.io"),
    Source("vercel", "vercel", "Vercel Changelog", "engineering", "https://vercel.com/atom", ("vercel.com",), topic="software"),
    Source("kubernetes", "kubernetes", "Kubernetes Blog", "engineering", "https://kubernetes.io/feed.xml", ("kubernetes.io",), topic="software"),
    Source("postgresql", "postgresql", "PostgreSQL News", "engineering", "https://www.postgresql.org/news.rss", ("postgresql.org",), topic="software"),
    Source("docker-blog", "docker-blog", "Docker Blog", "engineering", "https://www.docker.com/blog/feed/",
           ("docker.com", "www.docker.com"), topic="software"),
    Source("golang-blog", "golang-blog", "The Go Blog", "engineering", "https://go.dev/blog/feed.atom",
           ("go.dev",), topic="software"),
    Source("rust-blog", "rust-blog", "Inside Rust", "engineering", "https://blog.rust-lang.org/feed.xml",
           ("blog.rust-lang.org",), topic="software"),
    Source("spotify-engineering", "spotify-engineering", "Spotify Engineering", "engineering",
           "https://engineering.atspotify.com/feed", ("engineering.atspotify.com",), topic="software"),
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
    Source("the-new-stack", "the-new-stack", "The New Stack", "engineering", "https://thenewstack.io/feed/", ("thenewstack.io",), topic="software"),
    Source("stackoverflow-blog", "stackoverflow-blog", "Stack Overflow Blog", "engineering", "https://stackoverflow.blog/feed/", ("stackoverflow.blog",), topic="software"),
    reporting("smashing-magazine", "Smashing Magazine", "https://www.smashingmagazine.com/feed/", "smashingmagazine.com",
              topic="software", region="Europe"),

    # Articles, tutorials, and practitioner write-ups
    article_feed("netflix-techblog", "Netflix TechBlog on Medium", "https://medium.com/feed/netflix-techblog",
                 "netflixtechblog.com", group="medium", author_name="Netflix Technology Blog",
                 author_url="https://medium.com/@NetflixTechBlog"),
    article_feed("airbnb-engineering", "Airbnb Engineering on Medium", "https://medium.com/feed/airbnb-engineering",
                 "airbnb.io", group="medium"),
    article_feed("ux-collective", "UX Collective on Medium", "https://uxdesign.cc/feed", "uxdesign.cc", group="medium"),
    article_feed("medium-codex", "CodeX on Medium", "https://medium.com/feed/codex", group="medium"),
    article_feed("medium-proandroiddev", "ProAndroidDev on Medium", "https://medium.com/feed/proandroiddev",
                 "proandroiddev.com", group="medium"),
    article_feed("medium-level-up-coding", "Level Up Coding on Medium", "https://medium.com/feed/gitconnected",
                 "levelup.gitconnected.com", group="medium"),
    article_feed("medium-towards-ai", "Towards AI on Medium", "https://medium.com/feed/towards-artificial-intelligence",
                 "pub.towardsai.net", group="medium", topic="ai"),
    article_feed("medium-ai", "Medium Artificial Intelligence", "https://medium.com/feed/tag/artificial-intelligence",
                 group="medium", topic="ai"),
    article_feed("medium-programming", "Medium Programming", "https://medium.com/feed/tag/programming", group="medium"),
    article_feed("medium-cloud", "Medium Cloud Computing", "https://medium.com/feed/tag/cloud-computing", group="medium"),
    article_feed("medium-security", "Medium Cybersecurity", "https://medium.com/feed/tag/cybersecurity",
                 group="medium", topic="security"),
    article_feed("medium-open-source", "Medium Open Source", "https://medium.com/feed/tag/open-source", group="medium"),
    article_feed("medium-software-engineering", "Medium Software Engineering", "https://medium.com/feed/tag/software-engineering", group="medium"),
    article_feed("medium-system-design", "Medium System Design", "https://medium.com/feed/tag/system-design", group="medium"),
    article_feed("medium-data-engineering", "Medium Data Engineering", "https://medium.com/feed/tag/data-engineering", group="medium"),
    article_feed("medium-devops", "Medium DevOps", "https://medium.com/feed/tag/devops", group="medium"),
    article_feed("medium-machine-learning", "Medium Machine Learning", "https://medium.com/feed/tag/machine-learning", group="medium", topic="ai"),
    Source("dev-community", "dev", "DEV Community", "engineering", "https://dev.to/api/articles?per_page=80",
           ("dev.to",), topic="software", coverage="article", integration="dev-api"),
    Source("dev-latest", "dev", "DEV Community Latest", "engineering", "https://dev.to/api/articles/latest?per_page=60",
           ("dev.to",), topic="software", coverage="article", integration="dev-api"),
    article_feed("dev-architecture", "DEV Community Architecture", "https://dev.to/feed/tag/architecture", "dev.to", group="dev"),
    article_feed("dev-security", "DEV Community Security", "https://dev.to/feed/tag/security", "dev.to", group="dev", topic="security"),
    Source("hashnode-discover", "hashnode", "Hashnode Global Technology Feed", "engineering", "https://gql-beta.hashnode.com/",
           ("hashnode.com", "hashnode.dev"), topic="software", coverage="article", integration="hashnode-api", language="und"),
    article_feed("hashnode", "Hashnode Community Publication", "https://townhall.hashnode.com/rss.xml", "townhall.hashnode.com", group="hashnode", topic="software"),
    article_feed("freecodecamp", "freeCodeCamp", "https://www.freecodecamp.org/news/rss/", "freecodecamp.org"),
    article_feed("towards-data-science", "Towards Data Science", "https://towardsdatascience.com/feed/", "towardsdatascience.com", topic="ai"),
    article_feed("martin-fowler", "Martin Fowler", "https://martinfowler.com/feed.atom", "martinfowler.com"),
    article_feed("zenn", "Zenn", "https://zenn.dev/feed", "zenn.dev", region="Asia-Pacific", language="ja"),
    article_feed("linuxfr", "LinuxFr", "https://linuxfr.org/news.atom", "linuxfr.org", region="Europe", language="fr"),
    reporting("medianama", "MediaNama", "https://www.medianama.com/feed/", "medianama.com",
              region="Asia-Pacific"),
    reporting("manual-do-usuario", "Manual do Usuário", "https://manualdousuario.net/feed/", "manualdousuario.net",
              region="Latin America", language="pt-BR"),
    article_feed("kubernetes-zh", "Kubernetes Blog (Chinese)", "https://kubernetes.io/zh-cn/feed.xml",
                 "kubernetes.io", language="zh-CN"),

    # Official change logs and project release notes
    releases("github-changelog", "GitHub Changelog", "https://github.blog/changelog/feed/", "github.blog",
             article_paths=("/changelog/",)),
    releases("node-releases", "Node.js Releases", "https://nodejs.org/en/feed/blog.xml", "nodejs.org",
             article_paths=("/en/blog/release/",)),
    releases("uv-releases", "uv Releases", "https://github.com/astral-sh/uv/releases.atom", "github.com",
             article_paths=("/astral-sh/uv/releases/tag/",)),
    releases("rust-releases", "Rust Releases", "https://github.com/rust-lang/rust/releases.atom", "github.com",
             article_paths=("/rust-lang/rust/releases/tag/",)),
    Source("kubernetes-blog", "kubernetes-blog", "Kubernetes Blog", "engineering",
           "https://kubernetes.io/feed.xml", ("kubernetes.io",), topic="software", article_paths=("/blog/",)),
    Source("python-blog", "python-blog", "Python Insider", "engineering",
           "https://blog.python.org/feeds/posts/default", ("blog.python.org",), topic="software"),
    Source("go-blog", "go-blog", "The Go Blog", "engineering",
           "https://go.dev/blog/feed.atom", ("go.dev",), topic="software"),

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
    Source("kubernetes-advisories", "kubernetes-advisories", "Kubernetes Security Advisories", "news",
           "https://kubernetes.io/docs/reference/issues-security/official-cve-feed/feed.xml", ("github.com",),
           topic="security", coverage="advisory", article_paths=("/kubernetes/kubernetes/issues/",)),
    Source("arxiv-crypto", "arxiv-crypto", "arXiv Cryptography & Security", "research",
           "https://rss.arxiv.org/rss/cs.CR", ("arxiv.org",), topic="security", coverage="preprint"),

    # Research publications and research news
    Source("nature-computing", "nature-computing", "Nature Portfolio Computer Science", "research",
           "https://www.nature.com/subjects/computer-science.rss", ("nature.com",), topic="research"),
    Source("nature-machine-intelligence", "nature-machine-intelligence", "Nature Machine Intelligence", "research",
           "https://www.nature.com/natmachintell.rss", ("nature.com",), topic="research", coverage="journal",
           article_paths=("/articles/",)),
    Source("science-robotics", "science-robotics", "Science Robotics", "research",
           "https://www.science.org/action/showFeed?type=etoc&feed=rss&jc=scirobotics", ("science.org",),
           topic="research", coverage="journal", article_paths=("/doi/",)),
    Source("joss", "joss", "Journal of Open Source Software", "research", "https://joss.theoj.org/papers.atom",
           ("joss.theoj.org",), topic="research", coverage="journal", article_paths=("/papers/",)),
    Source("arxiv-programming", "arxiv-programming", "arXiv Programming Languages", "research",
           "https://rss.arxiv.org/rss/cs.PL", ("arxiv.org",), topic="software", coverage="preprint"),
    Source("arxiv-distributed", "arxiv-distributed", "arXiv Distributed Computing", "research",
           "https://rss.arxiv.org/rss/cs.DC", ("arxiv.org",), topic="software", coverage="preprint"),
    Source("mit-robotics", "mit-robotics", "MIT News Robotics", "research", "https://news.mit.edu/topic/mitrobotics-rss.xml",
           ("news.mit.edu",), topic="research"),
    reporting("quanta-computing", "Quanta Magazine Computer Science", "https://www.quantamagazine.org/computer-science/feed/",
              "quantamagazine.org", topic="research"),
    reporting("stat-health-tech", "STAT Health Tech", "https://www.statnews.com/category/health-tech/feed/", "statnews.com",
              region="North America"),
    Source("w3c-news", "w3c-news", "W3C News", "engineering", "https://www.w3.org/news/feed/", ("w3.org",),
           topic="software", article_paths=("/news/",)),

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
    ("pt-BR", "Portuguese (Brazil)"), ("es-MX", "Spanish (Mexico)"), ("es-ES", "Spanish (Spain)"),
    ("es-419", "Spanish (Latin America)"), ("nl", "Dutch"),
    ("zh-CN", "Chinese (Simplified)"), ("zh-TW", "Chinese (Traditional)"), ("ar", "Arabic"),
    ("und", "Not specified"),
) if any(source.language == code for source in DEFAULT_SOURCES)}
