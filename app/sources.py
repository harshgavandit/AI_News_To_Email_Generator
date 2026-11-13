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

    def public(self):
        return {"id": self.id, "source": self.group, "label": self.label, "kind": self.kind,
                "feed_url": self.url, "enabled": self.enabled}


def youtube(slug, name, channel):
    return Source(slug, "youtube", name, "video",
                  f"https://www.youtube.com/feeds/videos.xml?channel_id={channel}", ("youtube.com", "youtu.be"))


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
)
BY_ID = {source.id: source for source in DEFAULT_SOURCES}
GROUPS = tuple(dict.fromkeys(s.group for s in DEFAULT_SOURCES))
KINDS = ("all", "news", "research", "engineering", "video")
