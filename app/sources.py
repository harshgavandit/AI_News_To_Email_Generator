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

    def public(self):
        return {"id": self.id, "source": self.group, "label": self.label, "kind": self.kind,
                "feed_url": self.url, "enabled": self.enabled, "topic": self.topic,
                "coverage": self.coverage, "region": self.region}


def youtube(slug, name, channel):
    return Source(slug, "youtube", name, "video",
                  f"https://www.youtube.com/feeds/videos.xml?channel_id={channel}", ("youtube.com", "youtu.be"))


def reporting(slug, name, url, *hosts, region="Global", topic="industry"):
    return Source(slug, slug, name, "news", url, hosts, topic=topic, coverage="reporting", region=region)


def status(slug, name, url, *hosts):
    return Source(slug, slug, name, "status", url, hosts, topic="outages", coverage="status")


DEFAULT_SOURCES = (
    Source("openai-news", "openai", "OpenAI News", "news", "https://openai.com/news/rss.xml", ("openai.com",)),
    *(Source(f"anthropic-{part}", "anthropic", f"Anthropic {part.title()}", kind,
             f"https://raw.githubusercontent.com/Olshansk/rss-feeds/main/feeds/feed_anthropic_{part}.xml",
             ("anthropic.com",)) for part, kind in (("news", "news"), ("research", "research"), ("engineering", "engineering"))),
    Source("hugging-face", "hugging-face", "Hugging Face", "engineering", "https://huggingface.co/blog/feed.xml", ("huggingface.co",)),
    Source("google-research", "google-research", "Google Research", "research", "https://research.google/blog/rss/", ("research.google", "research.google.com")),
    Source("google-deepmind", "google-deepmind", "Google DeepMind", "research", "https://deepmind.google/blog/rss.xml", ("deepmind.google", "blog.google")),
    Source("microsoft-research", "microsoft-research", "Microsoft Research", "research", "https://www.microsoft.com/en-us/research/feed/", ("microsoft.com",)),
    Source("aws-ml", "aws-ml", "AWS Machine Learning", "engineering", "https://aws.amazon.com/blogs/machine-learning/feed/", ("aws.amazon.com",)),
    Source("nvidia", "nvidia", "NVIDIA Technical Blog", "engineering", "https://developer.nvidia.com/blog/feed/", ("developer.nvidia.com",)),
    Source("langchain", "langchain", "LangChain", "engineering", "https://www.langchain.com/blog/rss.xml", ("langchain.com", "blog.langchain.com")),
    Source("simon-willison", "simon-willison", "Simon Willison", "engineering", "https://simonwillison.net/atom/everything/", ("simonwillison.net",)),
    youtube("matthew-berman", "Matthew Berman", "UCawZsQWqfGSbCI5yjkdVkTA"),
    youtube("ai-engineer", "AI Engineer", "UCLKPca3kwwd-B59HNr-_lvA"),
    youtube("karpathy", "Andrej Karpathy", "UCXUPKJO5MZQN11PqgIvyuvQ"),
    youtube("two-minute-papers", "Two Minute Papers", "UCbfYPyITQ-7l4upoX8nvctg"),
    youtube("hugging-face-video", "Hugging Face on YouTube", "UCHlNU7kIZhRgSbhHvFoy72w"),
    reporting("bbc-tech", "BBC Technology", "https://feeds.bbci.co.uk/news/technology/rss.xml", "bbc.com", "bbc.co.uk"),
    reporting("guardian-tech", "The Guardian Technology", "https://www.theguardian.com/technology/rss", "theguardian.com"),
    reporting("the-verge", "The Verge", "https://www.theverge.com/rss/index.xml", "theverge.com"),
    reporting("ars-technica", "Ars Technica", "https://feeds.arstechnica.com/arstechnica/index", "arstechnica.com"),
    reporting("techcrunch", "TechCrunch", "https://techcrunch.com/feed/", "techcrunch.com"),
    reporting("wired", "WIRED", "https://www.wired.com/feed/rss", "wired.com"),
    reporting("rest-of-world", "Rest of World", "https://restofworld.org/feed/latest/", "restofworld.org"),
    reporting("techcabal", "TechCabal", "https://techcabal.com/feed/", "techcabal.com", region="Africa"),
    reporting("scmp-tech", "SCMP Technology", "https://www.scmp.com/rss/5/feed", "scmp.com", region="Asia"),
    reporting("indian-express-tech", "The Indian Express Technology", "https://indianexpress.com/section/technology/feed/", "indianexpress.com", region="India"),
    reporting("latamlist", "LatamList", "https://latamlist.com/feed/", "latamlist.com", region="Latin America"),
    reporting("bleepingcomputer", "BleepingComputer", "https://www.bleepingcomputer.com/feed/", "bleepingcomputer.com", topic="security"),
    Source("nvidia-newsroom", "nvidia", "NVIDIA Newsroom", "news", "https://nvidianews.nvidia.com/releases.xml", ("nvidianews.nvidia.com",), topic="chips"),
    Source("github-blog", "github-blog", "The GitHub Blog", "engineering", "https://github.blog/feed/", ("github.blog",), topic="software"),
    Source("kubernetes", "kubernetes", "Kubernetes Blog", "engineering", "https://kubernetes.io/feed.xml", ("kubernetes.io",), topic="software"),
    Source("postgresql", "postgresql", "PostgreSQL News", "engineering", "https://www.postgresql.org/news.rss", ("postgresql.org",), topic="software"),
    Source("aws-news", "aws-news", "AWS News Blog", "engineering", "https://aws.amazon.com/blogs/aws/feed/", ("aws.amazon.com",), topic="software"),
    status("azure-status", "Microsoft Azure Status", "https://rssfeed.azure.status.microsoft/en-us/status/feed/", "azure.status.microsoft", "status.azure.com", "rssfeed.azure.status.microsoft"),
    status("google-cloud-status", "Google Cloud Status", "https://status.cloud.google.com/feed.atom", "status.cloud.google.com"),
    status("cloudflare-status", "Cloudflare Status", "https://www.cloudflarestatus.com/api/v3/incidents.rss", "cloudflarestatus.com"),
    status("github-status", "GitHub Status", "https://www.githubstatus.com/history.rss", "githubstatus.com"),
)
BY_ID = {source.id: source for source in DEFAULT_SOURCES}
GROUPS = tuple(dict.fromkeys(s.group for s in DEFAULT_SOURCES))
KINDS = ("all", "news", "research", "engineering", "video", "status")
