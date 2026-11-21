"""Build the November 21, 2026 candidate source pack.

Writes docs/research/source-candidates-2026-11-21.json. The pack is only a proposal:
`python -m scripts.check_source_pack <pack> --report <report> --promote <out>` checks
each feed and keeps active, English-verified entries. Nothing here fetches a URL.
"""
import json
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "docs/research/source-candidates-2026-11-21.json"
rows = []


def add(ident, label, url, hosts, *, kind="engineering", topic="software", coverage="article", fmt="blog",
        collection="Systems and software", refresh=360, region="Global", group=None, **extra):
    rows.append({"id": ident, "group": group or ident, "label": label, "url": url, "hosts": list(hosts),
                 "kind": kind, "topic": topic, "coverage": coverage, "format": fmt, "region": region,
                 "language": "en", "refresh_minutes": refresh, "collection": collection, **extra})


def news(ident, label, url, hosts, *, topic="industry", region="Global", refresh=0, collection="Global technology", **extra):
    add(ident, label, url, hosts, kind="news", topic=topic, coverage="reporting", fmt="news", region=region,
        refresh=refresh, collection=collection, **extra)


def release(repo, topic="software", collection="Systems and software"):
    owner, name = repo.split("/")
    add(f"release-{owner.lower()}-{name.lower()}".replace("_", "-").replace(".", "-"), f"{repo} Releases",
        f"https://github.com/{repo}/releases.atom", ("github.com",), topic=topic, coverage="release",
        fmt="release", collection=collection, refresh=60, group="github-releases",
        article_paths=[f"/{repo}/releases/tag/"])


def youtube(ident, label, channel, topic="ai", collection="AI engineering"):
    add(ident, label, f"https://www.youtube.com/feeds/videos.xml?channel_id={channel}", ("youtube.com", "youtu.be"),
        kind="video", topic=topic, coverage="publisher", fmt="video", collection=collection, refresh=60, group="youtube")


def podcast(ident, label, url, hosts, topic="ai", collection="AI engineering"):
    add(ident, label, url, hosts, kind="podcast", topic=topic, coverage="article", fmt="podcast",
        collection=collection, refresh=120)


def newsletter(ident, label, url, hosts, topic="ai", collection="AI engineering", refresh=180):
    add(ident, label, url, hosts, topic=topic, fmt="newsletter", collection=collection, refresh=refresh)


def medium(ident, label, path, topic="software", collection="Systems and software"):
    add(ident, label, f"https://medium.com/feed/{path}", ("medium.com",), topic=topic, collection=collection,
        refresh=120, group="medium")


def arxiv(category, label, topic="research"):
    add(f"arxiv-{category.lower().replace('.', '-')}", f"arXiv {label}", f"https://rss.arxiv.org/rss/{category}",
        ("arxiv.org",), kind="research", topic=topic, coverage="preprint", fmt="paper", collection="Research", refresh=720)


# --- AI news, analysis and independent research writing -------------------------------
news("marktechpost", "MarkTechPost", "https://www.marktechpost.com/feed/", ("marktechpost.com",), topic="ai")
news("ai-news", "AI News", "https://www.artificialintelligence-news.com/feed/", ("artificialintelligence-news.com",), topic="ai")
news("synced-review", "Synced", "https://syncedreview.com/feed/", ("syncedreview.com",), topic="ai")
news("kdnuggets", "KDnuggets", "https://www.kdnuggets.com/feed", ("kdnuggets.com",), topic="ai")
news("ieee-spectrum-ai", "IEEE Spectrum Artificial Intelligence",
     "https://spectrum.ieee.org/feeds/topic/artificial-intelligence.rss", ("spectrum.ieee.org",), topic="ai")
add("the-gradient", "The Gradient", "https://thegradient.pub/rss/", ("thegradient.pub",), topic="ai", collection="AI engineering")
add("stanford-ai-lab", "Stanford AI Lab Blog", "https://ai.stanford.edu/blog/feed.xml", ("ai.stanford.edu",),
    kind="research", topic="research", collection="Research", refresh=720)
add("amazon-science", "Amazon Science", "https://www.amazon.science/index.rss", ("amazon.science",),
    kind="research", topic="research", coverage="publisher", collection="Research", refresh=720)
add("eleutherai-blog", "EleutherAI Blog", "https://blog.eleuther.ai/index.xml", ("blog.eleuther.ai",),
    kind="research", topic="ai", collection="Research", refresh=720)
add("ai2-blog", "Ai2 Blog on Medium", "https://medium.com/feed/ai2-blog", ("medium.com", "blog.allenai.org"),
    kind="research", topic="ai", coverage="publisher", collection="Research", refresh=720, group="medium")
add("alignment-forum", "AI Alignment Forum", "https://www.alignmentforum.org/feed.xml", ("alignmentforum.org",),
    kind="research", topic="ai", coverage="discussion", collection="Research", refresh=360)
add("vicki-boykis", "Vicki Boykis", "https://vickiboykis.com/index.xml", ("vickiboykis.com",), topic="ai",
    collection="AI engineering", refresh=720)
add("karpathy-blog", "Andrej Karpathy Blog", "https://karpathy.github.io/feed.xml", ("karpathy.github.io",),
    topic="ai", collection="AI engineering", refresh=1440)
add("google-cloud-blog", "Google Cloud Blog", "https://cloudblog.withgoogle.com/rss/", ("cloud.google.com", "cloudblog.withgoogle.com"),
    coverage="publisher", collection="Systems and software", refresh=120)
add("aws-open-source", "AWS Open Source Blog", "https://aws.amazon.com/blogs/opensource/feed/", ("aws.amazon.com",), coverage="publisher")
add("aws-compute", "AWS Compute Blog", "https://aws.amazon.com/blogs/compute/feed/", ("aws.amazon.com",), coverage="publisher")
add("aws-big-data", "AWS Big Data Blog", "https://aws.amazon.com/blogs/big-data/feed/", ("aws.amazon.com",), coverage="publisher")
newsletter("last-week-in-ai", "Last Week in AI", "https://lastweekin.ai/feed", ("lastweekin.ai",))
newsletter("ai-snake-oil", "AI Snake Oil", "https://www.aisnakeoil.com/feed", ("aisnakeoil.com", "www.aisnakeoil.com"))
newsletter("gary-marcus", "Marcus on AI", "https://garymarcus.substack.com/feed", ("garymarcus.substack.com",))
newsletter("the-sequence", "TheSequence", "https://thesequence.substack.com/feed", ("thesequence.substack.com",))
newsletter("sebastian-ruder", "NLP News — Sebastian Ruder", "https://newsletter.ruder.io/feed", ("newsletter.ruder.io",))
newsletter("data-engineering-weekly", "Data Engineering Weekly", "https://www.dataengineeringweekly.com/feed",
           ("dataengineeringweekly.com", "www.dataengineeringweekly.com"), topic="software", collection="Systems and software")

# --- arXiv categories not yet covered ---------------------------------------------------
arxiv("cs.MA", "Multiagent Systems", topic="ai")
arxiv("cs.IR", "Information Retrieval", topic="ai")
arxiv("cs.NE", "Neural and Evolutionary Computing", topic="ai")
arxiv("cs.HC", "Human-Computer Interaction")
arxiv("cs.NI", "Networking and Internet Architecture")
arxiv("cs.OS", "Operating Systems")

# --- Agentic AI, LLM tooling and ML frameworks on GitHub -----------------------------
for repo in ("microsoft/autogen", "openai/openai-node", "anthropics/anthropic-sdk-typescript",
             "modelcontextprotocol/typescript-sdk", "vercel/ai", "mastra-ai/mastra", "NVIDIA/TensorRT-LLM",
             "deepspeedai/DeepSpeed", "unslothai/unsloth", "axolotl-ai-cloud/axolotl", "open-webui/open-webui",
             "continuedev/continue", "cline/cline", "All-Hands-AI/OpenHands", "Aider-AI/aider", "chroma-core/chroma",
             "langgenius/dify", "n8n-io/n8n", "FlowiseAI/Flowise", "microsoft/graphrag", "ml-explore/mlx",
             "keras-team/keras", "huggingface/text-generation-inference", "huggingface/smolagents",
             "openai/openai-agents-js", "google-gemini/gemini-api-cookbook", "letta-ai/letta"):
    release(repo, topic="ai", collection="AI engineering")

# --- Runtimes, frameworks, infrastructure and security tooling on GitHub ---------------
for repo in ("denoland/deno", "oven-sh/bun", "docker/compose", "containerd/containerd", "istio/istio",
             "hashicorp/terraform", "hashicorp/vault", "argoproj/argo-workflows", "fluxcd/flux2", "caddyserver/caddy",
             "grafana/loki", "open-telemetry/opentelemetry-collector", "elastic/elasticsearch", "apache/iceberg",
             "facebook/react", "angular/angular", "vuejs/core", "tailwindlabs/tailwindcss", "nestjs/nest",
             "rails/rails", "laravel/framework", "spring-projects/spring-boot", "flutter/flutter",
             "aquasecurity/trivy", "projectdiscovery/nuclei", "home-assistant/core"):
    release(repo)

# --- Engineering blogs ---------------------------------------------------------------
for ident, label, url, hosts in (
    ("linkedin-engineering", "LinkedIn Engineering", "https://engineering.linkedin.com/blog.rss.html", ("linkedin.com", "engineering.linkedin.com")),
    ("github-engineering", "GitHub Engineering", "https://github.blog/engineering/feed/", ("github.blog",)),
    ("etsy-code-as-craft", "Etsy Code as Craft", "https://www.etsy.com/codeascraft/rss", ("etsy.com", "www.etsy.com")),
    ("zalando-engineering", "Zalando Engineering", "https://engineering.zalando.com/atom.xml", ("engineering.zalando.com",)),
    ("instacart-tech", "Instacart Tech", "https://tech.instacart.com/feed", ("tech.instacart.com",)),
    ("sentry-blog", "Sentry Engineering", "https://blog.sentry.io/feed.xml", ("blog.sentry.io",)),
    ("jane-street-tech", "Jane Street Tech Blog", "https://blog.janestreet.com/feed.xml", ("blog.janestreet.com",)),
    ("cockroach-labs", "Cockroach Labs Blog", "https://www.cockroachlabs.com/blog/index.xml", ("cockroachlabs.com", "www.cockroachlabs.com")),
    ("jetbrains-blog", "JetBrains Blog", "https://blog.jetbrains.com/feed/", ("blog.jetbrains.com",)),
    ("swift-blog", "Swift.org Blog", "https://www.swift.org/atom.xml", ("swift.org", "www.swift.org")),
    ("typescript-blog", "TypeScript Blog", "https://devblogs.microsoft.com/typescript/feed/", ("devblogs.microsoft.com",)),
    ("v8-blog", "V8 Blog", "https://v8.dev/blog.atom", ("v8.dev",)),
    ("llvm-blog", "LLVM Project Blog", "https://blog.llvm.org/index.xml", ("blog.llvm.org",)),
    ("apple-developer-news", "Apple Developer News", "https://developer.apple.com/news/rss/news.rss", ("developer.apple.com",)),
    ("expedia-tech", "Expedia Group Technology", "https://medium.com/feed/expedia-group-tech", ("medium.com",)),
    ("walmart-global-tech", "Walmart Global Tech", "https://medium.com/feed/walmartglobaltech", ("medium.com",)),
    ("paypal-tech", "PayPal Technology", "https://medium.com/feed/paypal-tech", ("medium.com",)),
    ("medium-engineering", "Medium Engineering", "https://medium.engineering/feed", ("medium.engineering",)),
    ("agoda-engineering", "Agoda Engineering", "https://medium.com/feed/agoda-engineering", ("medium.com",)),
):
    add(ident, label, url, hosts, coverage="publisher", refresh=360,
        group="medium" if "medium.com/feed" in url else None)

# --- Release notes and documentation updates -----------------------------------------
add("gcp-release-notes", "Google Cloud Release Notes", "https://cloud.google.com/feeds/gcp-release-notes.xml",
    ("cloud.google.com",), coverage="release", fmt="release", refresh=120)
add("cloudflare-changelog", "Cloudflare Developer Changelog", "https://developers.cloudflare.com/changelog/rss/index.xml",
    ("developers.cloudflare.com",), coverage="release", fmt="release", refresh=120)
add("chrome-releases", "Chrome Releases", "https://chromereleases.googleblog.com/feeds/posts/default",
    ("chromereleases.googleblog.com",), coverage="release", fmt="release", refresh=120)

# --- Medium and DEV topic feeds -----------------------------------------------------
medium("medium-tag-ai-agents", "Medium AI Agents", "tag/ai-agents", topic="ai", collection="AI engineering")
medium("medium-tag-llm", "Medium LLM", "tag/llm", topic="ai", collection="AI engineering")
medium("medium-tag-generative-ai", "Medium Generative AI", "tag/generative-ai", topic="ai", collection="AI engineering")
medium("medium-tag-kubernetes", "Medium Kubernetes", "tag/kubernetes")
medium("medium-tag-rust", "Medium Rust", "tag/rust")
medium("ai-advances", "AI Advances on Medium", "ai-advances", topic="ai", collection="AI engineering")
medium("javarevisited", "Javarevisited on Medium", "javarevisited")
medium("google-cloud-community", "Google Cloud Community on Medium", "google-cloud")
add("itnext", "ITNEXT", "https://itnext.io/feed", ("itnext.io",), refresh=120)
for tag, topic, collection in (("ai", "ai", "AI engineering"), ("llm", "ai", "AI engineering"),
                               ("rust", "software", "Systems and software"), ("kubernetes", "software", "Systems and software")):
    add(f"dev-tag-{tag}", f"DEV Community #{tag}", f"https://dev.to/feed/tag/{tag}", ("dev.to",),
        topic=topic, collection=collection, refresh=120, group="dev")

# --- Security --------------------------------------------------------------------------
for ident, label, url, hosts, coverage in (
    ("help-net-security", "Help Net Security", "https://www.helpnetsecurity.com/feed/", ("helpnetsecurity.com",), "reporting"),
    ("infosecurity-magazine", "Infosecurity Magazine", "https://www.infosecurity-magazine.com/rss/news/", ("infosecurity-magazine.com",), "reporting"),
    ("cso-online", "CSO Online", "https://www.csoonline.com/feed/", ("csoonline.com",), "reporting"),
    ("graham-cluley", "Graham Cluley", "https://grahamcluley.com/feed/", ("grahamcluley.com",), "article"),
    ("malwarebytes-labs", "Malwarebytes Labs", "https://www.malwarebytes.com/blog/feed/index.xml", ("malwarebytes.com",), "publisher"),
    ("msrc-blog", "Microsoft Security Response Center", "https://msrc.microsoft.com/blog/feed", ("msrc.microsoft.com",), "publisher"),
    ("check-point-research", "Check Point Research", "https://research.checkpoint.com/feed/", ("research.checkpoint.com",), "publisher"),
    ("zero-day-initiative", "Zero Day Initiative", "https://www.zerodayinitiative.com/blog?format=rss", ("zerodayinitiative.com",), "publisher"),
    ("watchtowr-labs", "watchTowr Labs", "https://labs.watchtowr.com/rss/", ("labs.watchtowr.com",), "publisher"),
    ("crowdstrike-blog", "CrowdStrike Blog", "https://www.crowdstrike.com/blog/feed/", ("crowdstrike.com",), "publisher"),
):
    if coverage == "reporting":
        news(ident, label, url, hosts, topic="security", collection="Security")
    else:
        add(ident, label, url, hosts, kind="engineering", topic="security", coverage=coverage,
            collection="Security", refresh=120)
podcast("risky-business", "Risky Business", "https://risky.biz/feeds/risky-business/", ("risky.biz",),
        topic="security", collection="Security")

# --- Cloud, DevOps and developer news ------------------------------------------------
news("devops-com", "DevOps.com", "https://devops.com/feed/", ("devops.com",), topic="software", collection="Systems and software")
news("infoworld", "InfoWorld", "https://www.infoworld.com/feed/", ("infoworld.com",), topic="software", collection="Systems and software")
news("dzone", "DZone", "https://feeds.dzone.com/home", ("dzone.com",), topic="software", collection="Systems and software")
news("computer-weekly", "Computer Weekly", "https://www.computerweekly.com/rss/All-Computer-Weekly-content.xml",
     ("computerweekly.com",), region="Europe")
news("the-stack", "The Stack", "https://www.thestack.technology/rss/", ("thestack.technology",), region="Europe")
newsletter("changelog-news", "Changelog News", "https://changelog.com/news/feed", ("changelog.com",), topic="software",
           collection="Systems and software")
newsletter("node-weekly", "Node Weekly", "https://nodeweekly.com/rss", ("nodeweekly.com",), topic="software",
           collection="Systems and software", refresh=720)
newsletter("react-status", "React Status", "https://react.statuscode.com/rss", ("react.statuscode.com",), topic="software",
           collection="Systems and software", refresh=720)
podcast("kubernetes-podcast", "Kubernetes Podcast from Google", "https://kubernetespodcast.com/feeds/audio.xml",
        ("kubernetespodcast.com",), topic="software", collection="Systems and software")
podcast("changelog-podcast", "The Changelog", "https://changelog.com/podcast/feed", ("changelog.com",), topic="software",
        collection="Systems and software")
podcast("syntax-fm", "Syntax", "https://feed.syntax.fm/rss", ("syntax.fm",), topic="software", collection="Systems and software")

# --- Hardware, chips, robotics, quantum and XR ---------------------------------------
news("eetimes", "EE Times", "https://www.eetimes.com/feed/", ("eetimes.com",), topic="chips")
news("hpcwire", "HPCwire", "https://www.hpcwire.com/feed/", ("hpcwire.com",), topic="chips")
news("robotics-automation-news", "Robotics & Automation News", "https://roboticsandautomationnews.com/feed/",
     ("roboticsandautomationnews.com",), topic="industry")
news("quantum-insider", "The Quantum Insider", "https://thequantuminsider.com/feed/", ("thequantuminsider.com",), topic="research")
news("road-to-vr", "Road to VR", "https://www.roadtovr.com/feed/", ("roadtovr.com",), topic="bigtech")
news("uploadvr", "UploadVR", "https://www.uploadvr.com/rss/", ("uploadvr.com",), topic="bigtech")
news("electrek", "Electrek", "https://electrek.co/feed/", ("electrek.co",), topic="industry")
add("raspberry-pi-news", "Raspberry Pi News", "https://www.raspberrypi.com/news/feed/", ("raspberrypi.com",),
    topic="chips", coverage="publisher", refresh=360)
add("adafruit-blog", "Adafruit Blog", "https://blog.adafruit.com/feed/", ("blog.adafruit.com",), topic="chips", refresh=360)

# --- Mainstream and independent technology news --------------------------------------
for ident, label, url, hosts, topic in (
    ("engadget", "Engadget", "https://www.engadget.com/rss.xml", ("engadget.com",), "bigtech"),
    ("zdnet", "ZDNET", "https://www.zdnet.com/news/rss.xml", ("zdnet.com",), "industry"),
    ("cnet-news", "CNET News", "https://www.cnet.com/rss/news/", ("cnet.com",), "bigtech"),
    ("fast-company-tech", "Fast Company Technology", "https://www.fastcompany.com/technology/rss", ("fastcompany.com",), "industry"),
    ("nyt-technology", "The New York Times Technology", "https://rss.nytimes.com/services/xml/rss/nyt/Technology.xml", ("nytimes.com",), "industry"),
    ("404-media", "404 Media", "https://www.404media.co/rss/", ("404media.co",), "industry"),
    ("geekwire", "GeekWire", "https://www.geekwire.com/feed/", ("geekwire.com",), "startups"),
    ("techradar", "TechRadar", "https://www.techradar.com/rss", ("techradar.com",), "bigtech"),
    ("android-authority", "Android Authority", "https://www.androidauthority.com/feed/", ("androidauthority.com",), "bigtech"),
    ("neowin", "Neowin", "https://www.neowin.net/news/rss/", ("neowin.net",), "bigtech"),
    ("techmeme", "Techmeme", "https://www.techmeme.com/feed.xml", ("techmeme.com",), "industry"),
):
    news(ident, label, url, hosts, topic=topic)
add("slashdot", "Slashdot", "https://rss.slashdot.org/Slashdot/slashdotMain", ("slashdot.org", "tech.slashdot.org", "rss.slashdot.org"),
    kind="news", topic="industry", coverage="discussion", fmt="news", collection="Global technology", refresh=30)
add("lobsters", "Lobsters", "https://lobste.rs/rss", ("lobste.rs",), kind="news", topic="software", coverage="discussion",
    fmt="news", refresh=30)
add("product-hunt", "Product Hunt", "https://www.producthunt.com/feed", ("producthunt.com", "www.producthunt.com"),
    kind="news", topic="startups", coverage="discussion", fmt="news", collection="Global technology", refresh=120)

# --- Startups and venture ----------------------------------------------------------------
add("a16z", "Andreessen Horowitz", "https://a16z.com/feed/", ("a16z.com",), topic="startups", collection="Global technology")
add("tomasz-tunguz", "Tomasz Tunguz", "https://tomtunguz.com/index.xml", ("tomtunguz.com",), topic="startups",
    collection="Global technology", refresh=720)
newsletter("not-boring", "Not Boring", "https://www.notboring.co/feed", ("notboring.co", "www.notboring.co"), topic="startups",
           collection="Global technology", refresh=720)
news("eu-startups", "EU-Startups", "https://www.eu-startups.com/feed/", ("eu-startups.com",), topic="startups", region="Europe")
news("uktn", "UKTN", "https://www.uktech.news/feed", ("uktech.news",), topic="startups", region="Europe")
news("kr-asia", "KrASIA", "https://kr-asia.com/feed", ("kr-asia.com",), topic="startups", region="Asia")
news("technode", "TechNode", "https://technode.com/feed/", ("technode.com",), region="Asia")
news("pandaily", "Pandaily", "https://pandaily.com/feed/", ("pandaily.com",), region="Asia")
news("et-tech", "ET Tech", "https://economictimes.indiatimes.com/tech/rssfeeds/13357270.cms",
     ("economictimes.indiatimes.com",), region="India")
news("mint-technology", "Mint Technology", "https://www.livemint.com/rss/technology", ("livemint.com",), region="India")

# --- Podcasts and video ---------------------------------------------------------------
podcast("lex-fridman", "Lex Fridman Podcast", "https://lexfridman.com/feed/podcast/", ("lexfridman.com",))
podcast("dwarkesh", "Dwarkesh Podcast", "https://www.dwarkesh.com/feed", ("dwarkesh.com", "www.dwarkesh.com"))
podcast("hard-fork", "Hard Fork", "https://feeds.simplecast.com/l2i9YnTd", ("nytimes.com", "simplecast.com"), topic="industry",
        collection="Global technology")
for ident, label, channel, topic, collection in (
    ("yt-yannic-kilcher", "Yannic Kilcher", "UCZHmQk67mSJgfCCTn7xBfew", "ai", "AI engineering"),
    ("yt-ai-explained", "AI Explained", "UCNJ1Ymd5yFuUPtn21xtRbbw", "ai", "AI engineering"),
    ("yt-mlst", "Machine Learning Street Talk", "UCMLtBahI5DMrt0NPvDSoIRQ", "ai", "AI engineering"),
    ("yt-sentdex", "sentdex", "UCfzlCWGWYyIQ0aLC5w48gBQ", "ai", "AI engineering"),
    ("yt-ibm-technology", "IBM Technology", "UCKWaEZ-_VweaEx1j62do_vQ", "ai", "AI engineering"),
    ("yt-openai", "OpenAI on YouTube", "UCXZCJLdBC09xxGZ6gcdrc6A", "ai", "AI engineering"),
    ("yt-anthropic", "Anthropic on YouTube", "UCrDwWp7EBBv4NwvScIpBDOA", "ai", "AI engineering"),
    ("yt-google-deepmind", "Google DeepMind on YouTube", "UCP7jMXSY2xbc3KCAE0MHQ-A", "ai", "AI engineering"),
    ("yt-nvidia", "NVIDIA on YouTube", "UCHuiy8bXnmK5nisYHUd1J5g", "chips", "Global technology"),
    ("yt-lex-fridman", "Lex Fridman on YouTube", "UCSHZKyawb77ixDdsGog4iWA", "ai", "AI engineering"),
    ("yt-theprimeagen", "ThePrimeagen", "UC8ENHE5xdFSwx71u3fDH5Xw", "software", "Systems and software"),
    ("yt-theo", "Theo - t3.gg", "UCbRP3c757lWg9M-U7TyEkXA", "software", "Systems and software"),
    ("yt-google-cloud-tech", "Google Cloud Tech", "UCJS9pqu9BzkAMNTmzNMNhvg", "software", "Systems and software"),
    ("yt-github", "GitHub on YouTube", "UC7c3Kb6jYCRj4JOHHZTxKsQ", "software", "Systems and software"),
    ("yt-networkchuck", "NetworkChuck", "UC9x0AN7BWHpCDHSm9NiJFJQ", "security", "Security"),
):
    youtube(ident, label, channel, topic=topic, collection=collection)

if __name__ == "__main__":
    from app.sources import DEFAULT_SOURCES
    # Candidates promoted from this pack keep their id and URL; anything else that matches is a duplicate.
    by_id = {source.id: source.url for source in DEFAULT_SOURCES}
    known_urls = {source.url.rstrip("/") for source in DEFAULT_SOURCES}
    recheck = OUT.with_name("source-candidates-2026-11-21-recheck.json")
    corrected = {row["id"]: row["url"] for row in json.loads(recheck.read_text(encoding="utf-8"))} if recheck.exists() else {}
    overlap = [row["id"] for row in rows if by_id.get(row["id"], row["url"]) not in (row["url"], corrected.get(row["id"]))
               or (row["id"] not in by_id and row["url"].rstrip("/") in known_urls)]
    assert not overlap, f"already integrated: {overlap}"
    ids = [row["id"] for row in rows]
    assert len(ids) == len(set(ids)), "duplicate candidate id"
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{len(rows)} candidates -> {OUT}")
