"""Build the second November 21, 2026 candidate source pack (gap-filling wave).

Writes docs/research/source-candidates-2026-11-21b.json. Like the first wave, the pack is a
proposal only: the "Validate candidate sources" workflow checks every feed from GitHub's
runners, and `scripts.promote_sources` appends only the ids it approves. Nothing here
fetches a URL.

This wave targets gaps left after the first wave: cloud and platform changelogs, service
status pages, national CERT advisories, AI-lab and independent research writing, the
agent/LLM tooling and data/infra projects not yet followed on GitHub, company engineering
blogs (including Indian and Asian engineering teams), hardware and electronics trade press,
regional English technology outlets, newsletters and developer podcasts. Candidates already
proposed in the first wave (promoted or not) are excluded rather than re-proposed.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs/research/source-candidates-2026-11-21b.json"
EARLIER = (ROOT / "docs/research/source-candidates-2026-11-21.json", ROOT / "docs/research/source-candidates-2026-11-21-recheck.json")
rows = []


def add(ident, label, url, hosts, *, kind="engineering", topic="software", coverage="article", fmt="blog",
        collection="Systems and software", refresh=360, region="Global", group=None, **extra):
    rows.append({"id": ident, "group": group or ident, "label": label, "url": url, "hosts": list(hosts),
                 "kind": kind, "topic": topic, "coverage": coverage, "format": fmt, "region": region,
                 "language": "en", "refresh_minutes": refresh, "collection": collection, **extra})


def news(ident, label, url, hosts, *, topic="industry", region="Global", collection="Global technology", **extra):
    add(ident, label, url, hosts, kind="news", topic=topic, coverage="reporting", fmt="news", region=region,
        refresh=0, collection=collection, **extra)


def official(ident, label, url, hosts, *, topic="software", collection="Systems and software", fmt="blog", **extra):
    add(ident, label, url, hosts, topic=topic, coverage="publisher", fmt=fmt, collection=collection, **extra)


def research(ident, label, url, hosts, *, topic="ai", coverage="publisher", **extra):
    add(ident, label, url, hosts, kind="research", topic=topic, coverage=coverage, collection="Research", refresh=720, **extra)


def release(repo, topic="software", collection="Systems and software"):
    owner, name = repo.split("/")
    add(f"release-{owner.lower()}-{name.lower()}".replace("_", "-").replace(".", "-"), f"{repo} Releases",
        f"https://github.com/{repo}/releases.atom", ("github.com",), topic=topic, coverage="release",
        fmt="release", collection=collection, refresh=60, group="github-releases",
        article_paths=[f"/{repo}/releases/tag/"])


def changelog(ident, label, url, hosts, *, topic="software"):
    add(ident, label, url, hosts, topic=topic, coverage="release", fmt="release", refresh=120)


def status(ident, label, url, hosts):
    add(ident, label, url, hosts, kind="status", topic="outages", coverage="status", fmt="news",
        collection="Service status", refresh=0)


def advisory(ident, label, url, hosts, *, region="Global"):
    add(ident, label, url, hosts, kind="news", topic="security", coverage="advisory", fmt="news", region=region,
        collection="Security", refresh=0)


def security_blog(ident, label, url, hosts, **extra):
    add(ident, label, url, hosts, topic="security", coverage="publisher", collection="Security", **extra)


def newsletter(ident, label, url, hosts, topic="ai", collection="AI engineering"):
    add(ident, label, url, hosts, topic=topic, fmt="newsletter", collection=collection, refresh=180)


def podcast(ident, label, url, hosts, topic="software", collection="Systems and software"):
    add(ident, label, url, hosts, kind="podcast", topic=topic, coverage="article", fmt="podcast",
        collection=collection, refresh=120)


def medium(ident, label, path, topic="software", collection="Systems and software"):
    add(ident, label, f"https://medium.com/feed/{path}", ("medium.com",), topic=topic, collection=collection,
        refresh=120, group="medium")


# --- Cloud, platform and developer changelogs ------------------------------------------
changelog("openai-developer-changelog", "OpenAI Developer Changelog", "https://developers.openai.com/changelog/rss.xml",
          ("developers.openai.com", "platform.openai.com"), topic="ai")
official("chrome-developers", "Chrome for Developers Blog", "https://developer.chrome.com/static/blog/feed.xml",
         ("developer.chrome.com",))
official("inside-java", "Inside Java", "https://inside.java/feed.xml", ("inside.java",))
official("gitlab-blog", "GitLab Blog", "https://about.gitlab.com/atom.xml", ("about.gitlab.com",))
official("digitalocean-blog", "DigitalOcean Blog", "https://www.digitalocean.com/blog/rss.xml", ("digitalocean.com",))
official("backblaze-blog", "Backblaze Blog", "https://www.backblaze.com/blog/feed/", ("backblaze.com",))
official("fastly-blog", "Fastly Blog", "https://www.fastly.com/blog_rss.xml", ("fastly.com",))
official("honeycomb-blog", "Honeycomb Blog", "https://www.honeycomb.io/feed", ("honeycomb.io",))
official("sourcegraph-blog", "Sourcegraph Blog", "https://sourcegraph.com/blog/rss.xml", ("sourcegraph.com",))
official("letsencrypt-blog", "Let's Encrypt News", "https://letsencrypt.org/feed.xml", ("letsencrypt.org",), topic="security",
         collection="Security")
official("brave-blog", "Brave Blog", "https://brave.com/blog/index.xml", ("brave.com",))
official("signal-blog", "Signal Blog", "https://signal.org/blog/rss.xml", ("signal.org",), topic="security", collection="Security")
official("eff-deeplinks", "EFF Deeplinks", "https://www.eff.org/rss/updates.xml", ("eff.org",), topic="industry",
         collection="Global technology")
official("github-security-lab", "GitHub Security Lab", "https://securitylab.github.com/feed.xml", ("securitylab.github.com",),
         topic="security", collection="Security")

# --- Service status pages ---------------------------------------------------------------
status("anthropic-status", "Anthropic Status", "https://status.anthropic.com/history.rss", ("status.anthropic.com",))
status("aws-health", "AWS Health Dashboard", "https://status.aws.amazon.com/rss/all.rss", ("status.aws.amazon.com", "health.aws.amazon.com"))
status("fastly-status", "Fastly Status", "https://www.fastlystatus.com/history.rss", ("fastlystatus.com",))
status("slack-status", "Slack Status", "https://slack-status.com/feed/rss", ("slack-status.com",))
status("atlassian-status", "Atlassian Bitbucket Status", "https://bitbucket.status.atlassian.com/history.rss",
       ("bitbucket.status.atlassian.com",))

# --- National CERTs and vulnerability advisories -----------------------------------------
advisory("cccs-advisories", "Canadian Centre for Cyber Security Alerts and Advisories",
         "https://www.cyber.gc.ca/api/cccs/rss/v1/get?feed=alerts_advisories&lang=en", ("cyber.gc.ca",), region="North America")
advisory("ubuntu-security-notices", "Ubuntu Security Notices", "https://ubuntu.com/security/notices/rss.xml", ("ubuntu.com",))
advisory("exploit-db", "Exploit Database", "https://www.exploit-db.com/rss.xml", ("exploit-db.com",))
advisory("hkcert-alerts", "HKCERT Security Bulletins", "https://www.hkcert.org/getrss/security-bulletin", ("hkcert.org",),
         region="Asia-Pacific")
security_blog("citizen-lab", "The Citizen Lab", "https://citizenlab.ca/feed/", ("citizenlab.ca",))
security_blog("sophos-news", "Sophos News", "https://news.sophos.com/en-us/feed/", ("news.sophos.com",))
security_blog("tenable-blog", "Tenable Blog", "https://www.tenable.com/blog/feed", ("tenable.com",))
security_blog("objective-see", "Objective-See Blog", "https://objective-see.org/rss.xml", ("objective-see.org",))
news("cyberscoop", "CyberScoop", "https://cyberscoop.com/feed/", ("cyberscoop.com",), topic="security", collection="Security")
news("the-register-security", "The Register Security", "https://www.theregister.com/security/headlines.atom",
     ("theregister.com",), topic="security", collection="Security", publisher_group="the-register")
news("security-boulevard", "Security Boulevard", "https://securityboulevard.com/feed/", ("securityboulevard.com",),
     topic="security", collection="Security")
podcast("smashing-security", "Smashing Security", "https://www.smashingsecurity.com/rss", ("smashingsecurity.com",),
        topic="security", collection="Security")
podcast("security-now", "Security Now", "https://feeds.twit.tv/sn.xml", ("twit.tv",), topic="security", collection="Security")

# --- AI labs, research groups and independent AI writing ------------------------------------
research("lmsys-blog", "LMSYS Org Blog", "https://lmsys.org/rss.xml", ("lmsys.org",))
research("epoch-ai", "Epoch AI", "https://epoch.ai/blog/rss.xml", ("epoch.ai",))
research("hazy-research", "Hazy Research (Stanford)", "https://hazyresearch.stanford.edu/feed.xml", ("hazyresearch.stanford.edu",))
research("cacm", "Communications of the ACM", "https://cacm.acm.org/feed/", ("cacm.acm.org",), topic="research")
research("mit-news-computing", "MIT News Computer Science", "https://news.mit.edu/rss/topic/computer-science-and-technology",
         ("news.mit.edu",), topic="research")
research("stanford-hai", "Stanford HAI News", "https://hai.stanford.edu/news/rss.xml", ("hai.stanford.edu",))
research("together-ai-blog", "Together AI Blog", "https://www.together.ai/blog/rss.xml", ("together.ai",))
research("cohere-blog", "Cohere Blog", "https://cohere.com/blog/rss.xml", ("cohere.com",))
newsletter("smol-ai-news", "AI News by smol.ai", "https://news.smol.ai/rss.xml", ("news.smol.ai",))
newsletter("thezvi", "Don't Worry About the Vase (Zvi Mowshowitz)", "https://thezvi.substack.com/feed", ("thezvi.substack.com",))
newsletter("exponential-view", "Exponential View", "https://www.exponentialview.co/feed", ("exponentialview.co",))
newsletter("algorithmic-bridge", "The Algorithmic Bridge", "https://www.thealgorithmicbridge.com/feed", ("thealgorithmicbridge.com",))
newsletter("gradient-flow", "Gradient Flow", "https://gradientflow.com/feed/", ("gradientflow.com",))
newsletter("air-street-press", "Air Street Press", "https://press.airstreet.com/feed", ("press.airstreet.com",))
newsletter("big-technology", "Big Technology", "https://www.bigtechnology.com/feed", ("bigtechnology.com",), topic="bigtech",
           collection="Global technology")
newsletter("lennys-newsletter", "Lenny's Newsletter", "https://www.lennysnewsletter.com/feed", ("lennysnewsletter.com",),
           topic="startups", collection="Global technology")
newsletter("elad-gil", "Elad Gil", "https://blog.eladgil.com/feed", ("blog.eladgil.com",), topic="startups",
           collection="Global technology")
newsletter("fabricated-knowledge", "Fabricated Knowledge", "https://www.fabricatedknowledge.com/feed",
           ("fabricatedknowledge.com",), topic="chips", collection="Global technology")
newsletter("the-chip-letter", "The Chip Letter", "https://thechipletter.substack.com/feed", ("thechipletter.substack.com",),
           topic="chips", collection="Global technology")
newsletter("asianometry", "Asianometry Newsletter", "https://www.asianometry.com/feed", ("asianometry.com",), topic="chips",
           collection="Global technology")
newsletter("tldr-tech", "TLDR Tech", "https://tldr.tech/api/rss/tech", ("tldr.tech",), topic="industry",
           collection="Global technology")
newsletter("tldr-ai", "TLDR AI", "https://tldr.tech/api/rss/ai", ("tldr.tech",))
newsletter("ios-dev-weekly", "iOS Dev Weekly", "https://iosdevweekly.com/issues.rss", ("iosdevweekly.com",), topic="software",
           collection="Systems and software")
newsletter("console-dev", "Console.dev", "https://console.dev/rss.xml", ("console.dev",), topic="software",
           collection="Systems and software")
newsletter("software-lead-weekly", "Software Lead Weekly", "https://softwareleadweekly.com/issues.rss",
           ("softwareleadweekly.com",), topic="software", collection="Systems and software")

# --- Developer podcasts -------------------------------------------------------------------
podcast("talk-python", "Talk Python To Me", "https://talkpython.fm/episodes/rss", ("talkpython.fm",))
podcast("python-bytes", "Python Bytes", "https://pythonbytes.fm/episodes/rss", ("pythonbytes.fm",))
podcast("rustacean-station", "Rustacean Station", "https://rustacean-station.org/podcast.rss", ("rustacean-station.org",))
podcast("gradient-dissent", "Gradient Dissent (Weights & Biases)", "https://feeds.captivate.fm/gradient-dissent/",
        ("wandb.ai", "captivate.fm"), topic="ai", collection="AI engineering")
podcast("cognitive-revolution", "The Cognitive Revolution", "https://feeds.megaphone.fm/RINTP3108857801", ("megaphone.fm",),
        topic="ai", collection="AI engineering")

# --- Company engineering blogs ----------------------------------------------------------------
official("doordash-engineering", "DoorDash Engineering", "https://careersatdoordash.com/engineering-blog/feed/",
         ("careersatdoordash.com",))
official("yelp-engineering", "Yelp Engineering", "https://engineeringblog.yelp.com/feed.xml", ("engineeringblog.yelp.com",))
official("nextdoor-engineering", "Nextdoor Engineering", "https://engblog.nextdoor.com/feed", ("engblog.nextdoor.com",))
official("figma-blog", "Figma Blog", "https://www.figma.com/blog/feed/atom.xml", ("figma.com",))
official("canva-engineering", "Canva Engineering", "https://www.canva.dev/blog/engineering/feed", ("canva.dev",))
official("swiggy-bytes", "Swiggy Bytes", "https://bytes.swiggy.com/feed", ("bytes.swiggy.com",), region="India")
official("flipkart-tech", "Flipkart Tech Blog", "https://blog.flipkart.tech/feed", ("blog.flipkart.tech",), region="India")
official("mercari-engineering", "Mercari Engineering", "https://engineering.mercari.com/en/blog/feed.xml",
         ("engineering.mercari.com",), region="Asia")
official("toss-tech", "Toss Tech", "https://toss.tech/rss.xml", ("toss.tech",), region="Asia")
official("cloudflare-radar", "Cloudflare Radar Blog", "https://blog.cloudflare.com/tag/cloudflare-radar/rss/", ("blog.cloudflare.com",),
         topic="industry", collection="Global technology", publisher_group="cloudflare-blog")
official("booking-tech", "Booking.com Engineering", "https://medium.com/feed/booking-com-development", ("medium.com",),
         group="medium")
medium("gojek-engineering", "Gojek Engineering", "gojekengineering")
medium("meesho-tech", "Meesho Tech", "meesho-tech")
medium("criteo-engineering", "Criteo R&D", "criteo-engineering")
medium("tinder-engineering", "Tinder Tech", "tinder")
medium("medium-tag-data-science", "Medium Data Science", "tag/data-science", topic="ai", collection="AI engineering")

# --- Hardware, electronics, data centres, space and mobility ---------------------------------
news("electronics-weekly", "Electronics Weekly", "https://www.electronicsweekly.com/feed/", ("electronicsweekly.com",),
     topic="chips", region="Europe")
news("edn", "EDN", "https://www.edn.com/feed/", ("edn.com",), topic="chips")
news("embedded-com", "Embedded.com", "https://www.embedded.com/feed/", ("embedded.com",), topic="chips")
news("datacenter-knowledge", "Data Center Knowledge", "https://www.datacenterknowledge.com/rss.xml",
     ("datacenterknowledge.com",), topic="software")
news("space-com-tech", "Space.com", "https://www.space.com/feeds/all", ("space.com",), topic="research")
news("ieee-spectrum-semis", "IEEE Spectrum Semiconductors", "https://spectrum.ieee.org/feeds/topic/semiconductors.rss",
     ("spectrum.ieee.org",), topic="chips", publisher_group="ieee-spectrum")
news("light-reading", "Light Reading", "https://www.lightreading.com/rss.xml", ("lightreading.com",), topic="industry")
news("rcr-wireless", "RCR Wireless News", "https://www.rcrwireless.com/feed", ("rcrwireless.com",), topic="industry")

# --- AI and enterprise technology reporting --------------------------------------------------
news("ai-business", "AI Business", "https://aibusiness.com/rss.xml", ("aibusiness.com",), topic="ai")
news("mit-tech-review-ai", "MIT Technology Review AI", "https://www.technologyreview.com/topic/artificial-intelligence/feed",
     ("technologyreview.com",), topic="ai", publisher_group="mit-tech-review")
news("techrepublic", "TechRepublic", "https://www.techrepublic.com/rssfeeds/articles/", ("techrepublic.com",), topic="software")
news("computerworld", "Computerworld", "https://www.computerworld.com/feed", ("computerworld.com",), topic="bigtech")
news("network-world", "Network World", "https://www.networkworld.com/feed", ("networkworld.com",), topic="software")
news("gizmodo-tech", "Gizmodo", "https://gizmodo.com/feed", ("gizmodo.com",), topic="industry")
news("macrumors", "MacRumors", "https://feeds.macrumors.com/MacRumors-All", ("macrumors.com",), topic="bigtech")
news("windows-central", "Windows Central", "https://www.windowscentral.com/feeds/all", ("windowscentral.com",), topic="bigtech")
news("xda-developers", "XDA Developers", "https://www.xda-developers.com/feed/", ("xda-developers.com",), topic="bigtech")
news("android-police", "Android Police", "https://www.androidpolice.com/feed/", ("androidpolice.com",), topic="bigtech")
news("semafor-tech", "Semafor Technology", "https://www.semafor.com/vertical/tech/rss.xml", ("semafor.com",), topic="industry")

# --- Regional English technology and startup reporting ---------------------------------------
news("techpoint-africa", "Techpoint Africa", "https://techpoint.africa/feed/", ("techpoint.africa",), topic="startups", region="Africa")
news("techweez", "Techweez", "https://techweez.com/feed/", ("techweez.com",), region="Africa")
news("mybroadband", "MyBroadband", "https://mybroadband.co.za/news/feed", ("mybroadband.co.za",), region="Africa")
news("menabytes", "MENAbytes", "https://www.menabytes.com/feed/", ("menabytes.com",), topic="startups",
     region="Middle East & North Africa")
news("techjuice", "TechJuice", "https://www.techjuice.pk/feed/", ("techjuice.pk",), region="Asia")
news("dailysocial", "DailySocial", "https://dailysocial.id/feed", ("dailysocial.id",), topic="startups", region="Asia")
news("the-bridge-jp", "The Bridge", "https://thebridge.jp/en/feed", ("thebridge.jp",), topic="startups", region="Asia")
news("it-world-canada", "IT World Canada", "https://www.itworldcanada.com/feed", ("itworldcanada.com",), region="North America")
news("techround", "TechRound", "https://techround.co.uk/feed/", ("techround.co.uk",), topic="startups", region="Europe")
news("the-hindu-tech", "The Hindu Technology", "https://www.thehindu.com/sci-tech/technology/feeder/default.rss",
     ("thehindu.com",), region="India")
news("gadgets360", "Gadgets 360", "https://www.gadgets360.com/rss/news", ("gadgets360.com",), topic="bigtech", region="India")

# --- Agent, LLM, data and infrastructure projects on GitHub -----------------------------------
for repo in (
    "crewAIInc/crewAI-tools", "camel-ai/camel", "Significant-Gravitas/AutoGPT", "e2b-dev/E2B", "ComposioHQ/composio",
    "livekit/agents", "pipecat-ai/pipecat", "Arize-ai/phoenix", "comet-ml/opik", "mem0ai/mem0", "getzep/graphiti",
    "anthropics/claude-agent-sdk-python", "sst/opencode", "RooCodeInc/Roo-Code", "block/goose", "meta-llama/llama-stack",
    "huggingface/lerobot", "InternLM/lmdeploy", "exo-explore/exo", "mlc-ai/mlc-llm", "mudler/LocalAI",
    "comfyanonymous/ComfyUI", "gradio-app/gradio", "streamlit/streamlit", "triton-lang/triton", "NVIDIA/NeMo",
    "microsoft/onnxruntime", "huggingface/text-embeddings-inference", "dottxt-ai/outlines", "567-labs/instructor",
    "deepset-ai/haystack", "guidance-ai/guidance", "pytorch/torchtune", "NVIDIA/Megatron-LM"
):
    release(repo, topic="ai", collection="AI engineering")
for repo in (
    "pola-rs/polars", "pandas-dev/pandas", "numpy/numpy", "apache/arrow", "delta-io/delta", "trinodb/trino",
    "dbt-labs/dbt-core", "apache/superset", "metabase/metabase", "jaegertracing/jaeger", "linkerd/linkerd2",
    "backstage/backstage", "dagger/dagger", "k3s-io/k3s", "kubernetes-sigs/kind", "cert-manager/cert-manager",
    "kyverno/kyverno", "falcosecurity/falco", "sigstore/cosign", "containers/podman", "moby/moby", "ansible/ansible",
    "hashicorp/consul", "hashicorp/nomad", "minio/minio", "tauri-apps/tauri", "electron/electron", "withastro/astro",
    "nuxt/nuxt", "vitest-dev/vitest", "biomejs/biome", "eslint/eslint", "rust-lang/rust-analyzer", "nginx/nginx",
    "Kong/kong", "temporalio/temporal", "nats-io/nats-server", "etcd-io/etcd", "dragonflydb/dragonfly", "pgvector/pgvector",
    "go-gitea/gitea", "jupyterlab/jupyterlab",
):
    release(repo)

if __name__ == "__main__":
    from app.sources import DEFAULT_SOURCES
    known_ids = {source.id for source in DEFAULT_SOURCES}
    known_urls = {source.url.rstrip("/") for source in DEFAULT_SOURCES}
    earlier = [row for path in EARLIER if path.exists() for row in json.loads(path.read_text(encoding="utf-8"))]
    tried_ids, tried_urls = {row["id"] for row in earlier}, {row["url"].rstrip("/") for row in earlier}
    overlap = [row["id"] for row in rows if row["id"] in known_ids | tried_ids
               or row["url"].rstrip("/") in known_urls | tried_urls]
    assert not overlap, f"already integrated or proposed: {overlap}"
    ids = [row["id"] for row in rows]
    assert len(ids) == len(set(ids)), "duplicate candidate id"
    assert len({row["url"] for row in rows}) == len(rows), "duplicate candidate url"
    OUT.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{len(rows)} candidates -> {OUT}")
