"""Source-grounded engineering stories for the Curiosity Cards collection."""
from copy import deepcopy
from datetime import UTC, datetime, timedelta
import re
from urllib.parse import urlsplit

from app.article_language import is_english_article
from app.article_metadata import restore_metadata
from app.coverage import public_article
from app.discovery import search_text
from app.news import canonical_url
from app.sanitation import sanitize_text
from app.sources import BY_ID, DEFAULT_SOURCES


def _seed(ident, title, url, publisher, company, year, description, tags, read_minutes, source_id, *,
          authors="", publisher_detail="", read_time_basis="estimate", published="", why="", themes=(),
          kind="engineering"):
    """A manually reviewed card. ``source_id`` is None for talks and posts outside the feed catalog."""
    source = BY_ID[source_id] if source_id else None
    kind = source.kind if source else kind
    return {
        "id": ident,
        "title": title,
        "url": url,
        "publisher": publisher,
        "company": company,
        "published_at": published,
        "year": int(year),
        "description": description,
        "summary": description,
        "summary_basis": "editorial_source_summary",
        "why_read": why,
        "themes": list(themes),
        "tags": list(tags),
        "read_minutes": read_minutes,
        "read_time_basis": read_time_basis,
        "estimated_reading_minutes": read_minutes,
        "reading_time_basis": read_time_basis,
        "source_id": source_id,
        "source": source.group if source else "curiosity",
        "kind": kind,
        "category": "Research" if kind == "research" else "Engineering",
        "author": authors,
        "publisher_detail": publisher_detail,
        "curiosity_seed": True,
    }


CURATED_CURIOSITY = (
    _seed("google-monorepo-2016", "Why Google Stores Billions of Lines of Code in a Single Repository",
          "https://research.google/pubs/why-google-stores-billions-of-lines-of-code-in-a-single-repository/",
          "Google Research", "Google", 2016,
          "Google Research describes a common source of truth for tens of thousands of developers and the systems, workflows, benefits, and trade-offs behind working in one very large repository.",
          ("Monorepo", "Developer infrastructure", "Build systems"), 12, "google-research",
          authors="Rachel Potvin · Josh Levenberg", publisher_detail="Communications of the ACM, 59 (2016), pp. 78–87"),
    _seed("anthropic-opus-4-6", "Introducing Claude Opus 4.6",
          "https://www.anthropic.com/news/claude-opus-4-6", "Anthropic", "Anthropic", 2026,
          "Anthropic reports improvements in coding, longer-running agent work, and reliability across larger codebases, alongside a beta one-million-token context window.",
          ("Claude", "Coding", "AI systems", "Long context"), 10, "anthropic-news",
          publisher_detail="Anthropic model and systems update"),
    _seed("anthropic-long-context", "Prompt engineering for Claude’s long context window",
          "https://www.anthropic.com/news/prompting-long-context", "Anthropic", "Anthropic", 2023,
          "Anthropic’s case study tests quote extraction and examples drawn from other parts of a document as techniques for improving long-context recall.",
          ("Long context", "Evaluation", "Prompt engineering"), 12, "anthropic-news",
          publisher_detail="Anthropic technical case study"),
    _seed("openai-gpt-4-1-prompting", "GPT-4.1 Prompting Guide",
          "https://developers.openai.com/cookbook/examples/gpt4-1_prompting_guide", "OpenAI Cookbook", "OpenAI", 2025,
          "OpenAI’s archived guide shares prompting practices drawn from internal testing, including explicit instructions, examples, planning, and iterative evaluations. It may refer to outdated models or APIs.",
          ("Prompt engineering", "Agents", "Evaluation", "Archived guide"), 15, "openai-news",
          authors="Noah MacCallum · Julian Lee", publisher_detail="OpenAI Cookbook · archived reference"),
    _seed("flash-attention-eli5", "ELI5: FlashAttention",
          "https://gordicaleksa.medium.com/eli5-flash-attention-5c44017022ad", "Aleksa Gordić on Medium", "Independent research",
          2023,
          "A step-by-step explanation of FlashAttention’s tiling and recomputation strategy, and how reducing GPU memory traffic can make exact attention more efficient.",
          ("FlashAttention", "GPU systems", "Machine learning"), 20, "medium-gordicaleksa",
          authors="Aleksa Gordić", publisher_detail="Medium publisher estimate", read_time_basis="publisher"),
    _seed("attention-is-all-you-need", "Attention Is All You Need",
          "https://research.google/pubs/attention-is-all-you-need/", "Google Research", "Google", 2017,
          "The Transformer paper presents an attention-based sequence model that removes recurrence and uses attention to represent relationships between tokens.",
          ("Transformers", "Attention", "Machine learning"), 15, "google-research",
          authors="Ashish Vaswani and co-authors", publisher_detail="NeurIPS research paper"),
    _seed("google-file-system", "The Google File System",
          "https://research.google/pubs/the-google-file-system/", "Google Research", "Google", 2003,
          "Google’s paper explains a fault-tolerant distributed file system designed for large data-intensive workloads on commodity machines.",
          ("Distributed systems", "Storage", "Fault tolerance"), 14, "google-research",
          authors="Sanjay Ghemawat · Howard Gobioff · Shun-Tak Leung", publisher_detail="ACM SOSP research paper"),
    _seed("google-mapreduce", "MapReduce: Simplified Data Processing on Large Clusters",
          "https://research.google/pubs/mapreduce-simplified-data-processing-on-large-clusters/", "Google Research", "Google", 2004,
          "The MapReduce paper describes a programming model and runtime that parallelize data processing while handling partitioning, scheduling, machine failures, and communication across a cluster.",
          ("Distributed systems", "Data processing", "Cluster computing"), 12, "google-research",
          authors="Jeffrey Dean · Sanjay Ghemawat", publisher_detail="OSDI research paper"),
    _seed("google-bigtable", "Bigtable: A Distributed Storage System for Structured Data",
          "https://research.google/pubs/bigtable-a-distributed-storage-system-for-structured-data/", "Google Research", "Google", 2006,
          "The paper describes Bigtable’s data model and implementation for storing structured data at petabyte scale across thousands of commodity servers.",
          ("Distributed systems", "Databases", "Storage"), 12, "google-research",
          authors="Fay Chang and co-authors", publisher_detail="USENIX OSDI research paper"),
    _seed("google-spanner", "Spanner: Google’s Globally-Distributed Database",
          "https://research.google/pubs/spanner-googles-globally-distributed-database-2/", "Google Research", "Google", 2012,
          "Spanner’s paper explains a globally distributed, synchronously replicated database and the time API used to support externally consistent transactions.",
          ("Distributed systems", "Databases", "Consistency"), 14, "google-research",
          authors="James C. Corbett and co-authors", publisher_detail="OSDI research paper"),
    _seed("anthropic-source-control", "Redesigning source control at Anthropic",
          "https://www.anthropic.com/research/redesigning-source-control", "Anthropic Engineering", "Anthropic", 2026,
          "Anthropic describes redesigning developer infrastructure as Claude increased the pace of code changes, including the source-control, build, and CI bottlenecks that became more visible at higher throughput.",
          ("Developer infrastructure", "Source control", "Claude Code", "CI"), 12, "anthropic-engineering",
          publisher_detail="Anthropic engineering article"),
    _seed("openai-performance-factory", "How OpenAI’s Performance Factory keeps ChatGPT fast",
          "https://openai.com/index/how-openai-performance-factory-keeps-chatgpt-fast/", "OpenAI Engineering", "OpenAI", 2026,
          "OpenAI explains a cloud workflow that uses agents to investigate performance regressions, collect evidence, and propose fixes for an engineer to review.",
          ("Performance engineering", "AI agents", "ChatGPT infrastructure", "Regression testing"), 10, "openai-news",
          publisher_detail="OpenAI engineering article"),
    _seed("meta-template-driven-ml", "Design Once, Deploy at Scale: Building a Template-Driven ML Ecosystem",
          "https://engineering.fb.com/2026/11/18/ml-applications/design-once-deploy-at-scale-template-driven-ml-ecosystem/",
          "Engineering at Meta", "Meta", 2026,
          "Meta describes standardizing production model design around reusable components so teams can ship and maintain a large model portfolio with less per-model engineering work.",
          ("Machine learning systems", "Reusable architecture", "Production engineering"), 12, "meta-engineering",
          authors="Anirudh Agrawal and co-authors", publisher_detail="Engineering at Meta · ML Applications"),
    _seed("openai-postgres-chatgpt", "Scaling PostgreSQL to power 800 million ChatGPT users",
          "https://openai.com/index/scaling-postgresql/", "OpenAI Engineering", "OpenAI", 2026,
          "OpenAI’s systems case study describes how a single-primary PostgreSQL deployment and regional read replicas supported read-heavy product traffic, and why some write-heavy workloads moved to sharded systems.",
          ("PostgreSQL", "Distributed systems", "ChatGPT infrastructure", "Database scaling"), 14, "openai-news",
          publisher_detail="OpenAI engineering case study"),
    _seed("uber-artifact-storage", "Modernizing Artifact Storage at Uber",
          "https://www.uber.com/us/en/blog/modernizing-artifact-storage/", "Uber Engineering", "Uber", 2026,
          "Uber explains how it modernized storage and distribution for software build artifacts and dependencies used by downstream engineering teams.",
          ("Build systems", "Artifact storage", "Developer infrastructure"), 10, "uber-engineering",
          publisher_detail="Uber Engineering · English edition"),
    _seed("netflix-live-operations", "The Human Infrastructure: How Netflix Built the Operations Layer Behind Live at Scale",
          "https://netflixtechblog.com/the-human-infrastructure-how-netflix-built-the-operations-layer-behind-live-at-scale-33e2a311c597",
          "Netflix Technology Blog", "Netflix", 2026,
          "Netflix describes the live operations practices and teams developed to support a growing slate of live streams, including events reaching tens of millions of concurrent members.",
          ("Live streaming", "Reliability", "Operations", "Scaling"), 15, "netflix-techblog",
          authors="Brett Axler · Casper Choffat · Alo Lowry", publisher_detail="Netflix TechBlog · Medium publisher estimate",
          read_time_basis="publisher"),

    # --- Google: cluster management, traffic, latency, monorepo practice ---------------------------
    _seed("google-borg", "Large-scale cluster management at Google with Borg",
          "https://research.google/pubs/large-scale-cluster-management-at-google-with-borg/", "Google Research", "Google", 2015,
          "The Borg paper describes the cluster manager that runs hundreds of thousands of jobs across Google’s clusters, covering admission control, task packing, over-commitment and the isolation needed to mix latency-sensitive services with batch work.",
          ("Cluster management", "Scheduling", "Infrastructure"), 25, "google-research",
          authors="Abhishek Verma and co-authors", publisher_detail="EuroSys research paper"),
    _seed("google-borg-omega-kubernetes", "Borg, Omega, and Kubernetes",
          "https://research.google/pubs/borg-omega-and-kubernetes/", "Google Research", "Google", 2016,
          "Lessons from three generations of Google container-management systems, and how experience with Borg and Omega shaped the design of Kubernetes.",
          ("Containers", "Kubernetes", "Cluster management"), 14, "google-research",
          authors="Brendan Burns · Brian Grant · David Oppenheimer · Eric Brewer · John Wilkes",
          publisher_detail="ACM Queue article"),
    _seed("google-maglev", "Maglev: A Fast and Reliable Software Network Load Balancer",
          "https://research.google/pubs/maglev-a-fast-and-reliable-software-network-load-balancer/", "Google Research", "Google", 2016,
          "How Google serves traffic through a distributed software load balancer on commodity servers, using consistent hashing and connection tracking to spread packets evenly and survive machine failures.",
          ("Load balancing", "Networking", "Traffic"), 18, "google-research",
          authors="Daniel E. Eisenbud and co-authors", publisher_detail="USENIX NSDI research paper"),
    _seed("google-tail-at-scale", "The Tail at Scale",
          "https://research.google/pubs/the-tail-at-scale/", "Google Research", "Google", 2013,
          "Why rare slow responses dominate latency in large fan-out services, and techniques such as hedged and tied requests that keep user-facing systems responsive despite variable component latency.",
          ("Latency", "Distributed systems", "Performance"), 15, "google-research",
          authors="Jeffrey Dean · Luiz André Barroso", publisher_detail="Communications of the ACM"),
    _seed("google-dapper", "Dapper, a Large-Scale Distributed Systems Tracing Infrastructure",
          "https://research.google/pubs/dapper-a-large-scale-distributed-systems-tracing-infrastructure/", "Google Research",
          "Google", 2010,
          "Google’s production tracing system follows requests across many services with low overhead and sampling, and helped inspire the distributed tracing tools used widely today.",
          ("Observability", "Tracing", "Microservices"), 16, "google-research",
          authors="Benjamin H. Sigelman and co-authors", publisher_detail="Google technical report"),
    _seed("google-sre-book", "Site Reliability Engineering: How Google Runs Production Systems",
          "https://sre.google/sre-book/table-of-contents/", "Google SRE", "Google", 2016,
          "Google’s free book on running production services, covering error budgets, monitoring, on-call, incident response, postmortems and how SRE teams balance reliability with release velocity.",
          ("Reliability", "Operations", "SRE"), 30, "google-research", publisher_detail="O’Reilly book, free online edition"),
    _seed("google-swe-book", "Software Engineering at Google",
          "https://abseil.io/resources/swe-book", "Abseil", "Google", 2020,
          "Lessons on programming over time at Google scale: code review, testing culture, large-scale changes, dependency management, and build and version-control practices around the monorepo.",
          ("Engineering culture", "Monorepo", "Testing"), 30, "google-research",
          authors="Titus Winters · Tom Manshreck · Hyrum Wright", publisher_detail="O’Reilly book, free online edition"),
    # --- Anthropic: Claude Code and agent engineering --------------------------------------------
    _seed("anthropic-teams-claude-code", "How Anthropic teams use Claude Code",
          "https://claude.com/resources/articles/how-anthropic-teams-use-claude-code", "Claude by Anthropic", "Anthropic", 2025,
          "Anthropic describes how its own engineering, security, data and non-technical teams use Claude Code day to day, from navigating unfamiliar codebases to debugging and automating routine work.",
          ("Claude Code", "Developer workflow", "AI agents"), 15, "anthropic-engineering",
          publisher_detail="Anthropic case study"),
    _seed("claude-code-best-practices", "Best practices for Claude Code",
          "https://code.claude.com/docs/en/best-practices", "Claude Code Docs", "Anthropic", 2025,
          "Practical guidance from the Claude Code team on giving an agent context, planning before coding, verifying changes with tests and running several sessions in parallel.",
          ("Claude Code", "Agentic coding", "Developer workflow"), 15, "anthropic-engineering",
          publisher_detail="Claude Code documentation"),
    _seed("anthropic-building-effective-agents", "Building effective agents",
          "https://www.anthropic.com/research/building-effective-agents", "Anthropic", "Anthropic", 2024,
          "Anthropic distinguishes workflows from agents and describes composable patterns such as prompt chaining, routing, parallelization and orchestrator-workers, arguing for simple designs over heavy frameworks.",
          ("AI agents", "Architecture", "LLM systems"), 12, "anthropic-engineering", publisher_detail="Anthropic engineering article"),
    _seed("anthropic-multi-agent-research", "How we built our multi-agent research system",
          "https://www.anthropic.com/research/multi-agent-research-system", "Anthropic", "Anthropic", 2025,
          "The engineering behind Claude’s Research feature: a lead agent that plans and delegates to parallel subagents, plus the prompting, evaluation and production-reliability lessons from running it.",
          ("Multi-agent systems", "Evaluation", "Production AI"), 18, "anthropic-engineering",
          publisher_detail="Anthropic engineering article"),
    _seed("anthropic-context-engineering", "Effective context engineering for AI agents",
          "https://www.anthropic.com/research/effective-context-engineering-for-ai-agents", "Anthropic", "Anthropic", 2025,
          "Why context is a finite resource for agents, and techniques such as just-in-time retrieval, compaction, structured note-taking and sub-agents for long-running tasks.",
          ("Context engineering", "AI agents", "LLM systems"), 14, "anthropic-engineering",
          publisher_detail="Anthropic engineering article"),
    _seed("anthropic-writing-tools", "Writing effective tools for AI agents",
          "https://www.anthropic.com/research/writing-tools-for-agents", "Anthropic", "Anthropic", 2025,
          "How Anthropic designs, evaluates and iterates on tools for agents, including choosing the right tools, namespacing, returning meaningful context and using Claude to improve tool descriptions.",
          ("Tool design", "AI agents", "Evaluation"), 14, "anthropic-engineering", publisher_detail="Anthropic engineering article"),
    _seed("anthropic-postmortem-2025", "A postmortem of three recent issues",
          "https://www.anthropic.com/research/a-postmortem-of-three-recent-issues", "Anthropic", "Anthropic", 2025,
          "Anthropic’s technical postmortem of three infrastructure bugs that degraded some Claude responses, how serving across several hardware platforms made them hard to detect, and the changes made afterwards.",
          ("Postmortem", "Reliability", "Inference infrastructure"), 14, "anthropic-engineering",
          publisher_detail="Anthropic engineering postmortem"),
    # --- OpenAI: infrastructure behind training and ChatGPT ---------------------------------------
    _seed("openai-kubernetes-7500", "Scaling Kubernetes to 7,500 nodes",
          "https://openai.com/index/scaling-kubernetes-to-7500-nodes/", "OpenAI", "OpenAI", 2021,
          "OpenAI explains running research workloads on a very large Kubernetes cluster, including networking, API server and etcd load, monitoring, health checks and GPU scheduling.",
          ("Kubernetes", "GPU infrastructure", "Scaling"), 15, "openai-news", publisher_detail="OpenAI engineering article"),
    _seed("openai-kubernetes-2500", "Scaling Kubernetes to 2,500 nodes",
          "https://openai.com/index/scaling-kubernetes-to-2500-nodes/", "OpenAI", "OpenAI", 2018,
          "The earlier chapter of OpenAI’s cluster story: the etcd, networking, DNS and image-pull problems found while growing a Kubernetes cluster for deep learning research.",
          ("Kubernetes", "Infrastructure", "Scaling"), 10, "openai-news", publisher_detail="OpenAI engineering article"),
    # --- Microsoft: engineering ecosystem --------------------------------------------------------
    _seed("microsoft-largest-git-repo", "The largest Git repo on the planet",
          "https://devblogs.microsoft.com/bharry/the-largest-git-repo-on-the-planet/", "Brian Harry’s Blog", "Microsoft", 2017,
          "How Microsoft moved Windows development into a single Git repository of roughly 300 GB and millions of files, and the virtualized file system work that made Git usable at that size.",
          ("Monorepo", "Git", "Developer infrastructure"), 10, "engineering-at-microsoft",
          authors="Brian Harry", publisher_detail="Microsoft Developer Blogs"),
    _seed("microsoft-scaling-git", "Scaling Git (and some back story)",
          "https://devblogs.microsoft.com/bharry/scaling-git-and-some-back-story/", "Brian Harry’s Blog", "Microsoft", 2017,
          "The background to Microsoft’s move to Git: why the company standardized its engineering systems and the performance problems that had to be solved for very large repositories.",
          ("Git", "Engineering systems", "Scaling"), 12, "engineering-at-microsoft",
          authors="Brian Harry", publisher_detail="Microsoft Developer Blogs"),
    _seed("microsoft-learn-mcp", "How we built the Microsoft Learn MCP Server",
          "https://devblogs.microsoft.com/engineering-at-microsoft/how-we-built-the-microsoft-learn-mcp-server/",
          "Engineering@Microsoft", "Microsoft", 2026,
          "Microsoft describes building a Model Context Protocol server so GitHub Copilot and other agents can ground answers in current Microsoft Learn documentation.",
          ("MCP", "AI agents", "Documentation"), 10, "engineering-at-microsoft", publisher_detail="Engineering@Microsoft"),
    # --- Payments: Stripe, Razorpay, Airbnb ---------------------------------------------------------
    _seed("stripe-online-migrations", "Online migrations at scale",
          "https://stripe.com/blog/online-migrations", "Stripe", "Stripe", 2017,
          "Stripe’s four-step pattern for moving data models with zero downtime while payments keep flowing: dual writes, changing reads, changing writes and removing the old data.",
          ("Data migrations", "Payments", "Reliability"), 12, "stripe-engineering", publisher_detail="Stripe engineering blog"),
    _seed("stripe-idempotency", "Designing robust and predictable APIs with idempotency",
          "https://stripe.com/blog/idempotency", "Stripe", "Stripe", 2017,
          "Why network failures make payment APIs dangerous to retry, and how idempotency keys with exponential backoff let clients retry safely without charging twice.",
          ("API design", "Payments", "Distributed systems"), 10, "stripe-engineering", publisher_detail="Stripe engineering blog"),
    _seed("stripe-rate-limiters", "Scaling your API with rate limiters",
          "https://stripe.com/blog/rate-limiters", "Stripe", "Stripe", 2017,
          "The four kinds of request and concurrency limiters and load shedders Stripe uses to keep its API available under traffic spikes, with guidance on rolling them out safely.",
          ("Rate limiting", "Traffic", "Reliability"), 10, "stripe-engineering", publisher_detail="Stripe engineering blog"),
    _seed("razorpay-kafka-upi", "Five Years of Kafka at Razorpay’s UPI Switch",
          "https://engineering.razorpay.com/tryst-with-kafka-2f5cef766c45", "Razorpay Engineering", "Razorpay", 2026,
          "Razorpay’s UPI Switch, which processes real-time payments with NPCI, is built around Kafka. The team reviews the decisions, operational incidents and optimizations from five years of running it.",
          ("Payments", "Kafka", "Event-driven systems"), 14, "razorpay-engineering",
          authors="Kshitij Nawandar", publisher_detail="Razorpay Engineering on Medium"),
    _seed("razorpay-reliable-deploys", "How We Deploy Reliably at Razorpay",
          "https://engineering.razorpay.com/how-we-deploy-reliably-at-razorpay-52ddf676caf8", "Razorpay Engineering", "Razorpay", 2026,
          "Most payment incidents start with a deployment, so Razorpay invests in progressive canaries, canaries for Kafka consumers, rollouts ordered by merchant criticality and alert-driven canary analysis.",
          ("Deployment", "Payments", "Reliability"), 12, "razorpay-engineering",
          authors="Anusha Musthaphak", publisher_detail="Razorpay Engineering on Medium"),
    _seed("airbnb-payment-orchestration", "Rebuilding Payment Orchestration at Airbnb",
          "https://medium.com/airbnb-engineering/rebuilding-payment-orchestration-at-airbnb-341d194a781b",
          "The Airbnb Tech Blog", "Airbnb", 2026,
          "Airbnb explains why it rebuilt the system that coordinates payment flows across processors and payment methods, and the design choices behind the new orchestration layer.",
          ("Payments", "Orchestration", "Distributed systems"), 12, "airbnb-engineering",
          publisher_detail="The Airbnb Tech Blog on Medium"),
    # --- Palo Alto Networks: security data and AI platforms ---------------------------------------
    _seed("paloalto-unified-data-platform", "How Palo Alto Networks built a multi-tenant scalable Unified Data Platform",
          "https://cloud.google.com/blog/topics/partners/palo-alto-networks-builds-a-multi-tenant-unified-data-platform",
          "Google Cloud Blog", "Palo Alto Networks", 2026,
          "Palo Alto Networks replaced about 30,000 single-tenant data pipelines for firewall logs, telemetry and threat events with a multi-tenant platform on Dataflow, Pub/Sub and BigQuery.",
          ("Data platforms", "Security", "Multi-tenancy"), 10, "google-cloud-blog",
          publisher_detail="Google Cloud Blog · written with Palo Alto Networks engineers"),
    _seed("paloalto-synonym-rag", "Bridging the Language Gap: Our Journey to a Synonym-Aware RAG System",
          "https://live.paloaltonetworks.com/t5/engineering-blogs/bridging-the-language-gap-our-journey-to-a-synonym-aware-rag/ba-p/1236616",
          "Palo Alto Networks Engineering", "Palo Alto Networks", 2025,
          "How Palo Alto Networks handled acronyms, aliases and product names in internal search, so retrieval-augmented answers still find the right documents when users and documents use different terms.",
          ("RAG", "Search", "Enterprise AI"), 12, "paloalto-engineering", publisher_detail="Palo Alto Networks Engineering Blogs"),
    # --- Traffic, microservices and data at internet companies ----------------------------------------
    _seed("uber-domain-microservices", "Introducing Domain-Oriented Microservice Architecture",
          "https://www.uber.com/blog/microservice-architecture/", "Uber Engineering", "Uber", 2020,
          "How Uber grouped roughly 2,200 microservices into domains, layers and gateways to reduce the complexity of a very large service architecture without abandoning microservices.",
          ("Microservices", "Architecture", "Scaling"), 15, "uber-engineering", publisher_detail="Uber Engineering"),
    _seed("uber-big-data-platform", "Uber’s Big Data Platform: 100+ Petabytes with Minute Latency",
          "https://www.uber.com/blog/uber-big-data-platform/", "Uber Engineering", "Uber", 2018,
          "Four generations of Uber’s data platform, and how Hudi brought incremental updates to a Hadoop data lake holding more than 100 petabytes.",
          ("Data platforms", "Hadoop", "Data engineering"), 18, "uber-engineering", publisher_detail="Uber Engineering"),
    _seed("cloudflare-pingora", "How we built Pingora, the proxy that connects Cloudflare to the Internet",
          "https://blog.cloudflare.com/how-we-built-pingora-the-proxy-that-connects-cloudflare-to-the-internet/",
          "Cloudflare Blog", "Cloudflare", 2022,
          "Why Cloudflare replaced NGINX with an in-house Rust proxy, and how its multithreaded design and connection reuse cut CPU and memory use while serving more than a trillion requests a day.",
          ("Proxies", "Rust", "Traffic"), 12, "cloudflare-blog", publisher_detail="Cloudflare Blog"),
    _seed("cloudflare-outage-2019", "Details of the Cloudflare outage on July 2, 2019",
          "https://blog.cloudflare.com/details-of-the-cloudflare-outage-on-july-2-2019/", "Cloudflare Blog", "Cloudflare", 2019,
          "A detailed postmortem of how one regular expression in a WAF rule exhausted CPU across Cloudflare’s network, and the process and engineering changes that followed.",
          ("Postmortem", "Reliability", "Regular expressions"), 20, "cloudflare-blog",
          authors="John Graham-Cumming", publisher_detail="Cloudflare Blog"),
    _seed("netflix-zuul-2", "Zuul 2: The Netflix Journey to Asynchronous, Non-Blocking Systems",
          "https://netflixtechblog.com/zuul-2-the-netflix-journey-to-asynchronous-non-blocking-systems-45947377fb5c",
          "Netflix Technology Blog", "Netflix", 2016,
          "Netflix rebuilt its edge gateway on an asynchronous, non-blocking architecture and explains the trade-offs in throughput, connection handling and debuggability that came with it.",
          ("API gateway", "Asynchronous systems", "Traffic"), 10, "netflix-techblog", publisher_detail="Netflix TechBlog"),
    _seed("meta-tao", "TAO: The power of the graph",
          "https://engineering.fb.com/2013/06/25/core-infra/tao-the-power-of-the-graph/", "Engineering at Meta", "Meta", 2013,
          "Facebook’s geographically distributed data store for the social graph, which serves billions of reads per second through a caching layer in front of MySQL.",
          ("Graph storage", "Caching", "Distributed systems"), 8, "meta-engineering", publisher_detail="Engineering at Meta"),
    _seed("meta-memcache", "Scaling Memcache at Facebook",
          "https://www.usenix.org/conference/nsdi13/technical-sessions/presentation/nishtala", "USENIX", "Meta", 2013,
          "How Facebook built a distributed key-value cache from memcached that serves billions of requests per second, covering cluster, region and cross-region consistency problems.",
          ("Caching", "Scaling", "Consistency"), 20, "meta-engineering",
          authors="Rajesh Nishtala and co-authors", publisher_detail="USENIX NSDI research paper"),
    _seed("spotify-event-delivery", "Spotify’s Event Delivery – The Road to the Cloud (Part I)",
          "https://engineering.atspotify.com/2016/02/spotifys-event-delivery-the-road-to-the-cloud-part-i",
          "Spotify Engineering", "Spotify", 2016,
          "How Spotify’s system for delivering hundreds of thousands of events per second worked, why it was outgrowing its design, and how the team planned the move to Google Cloud Pub/Sub.",
          ("Event delivery", "Data pipelines", "Cloud migration"), 10, "spotify-engineering", publisher_detail="Spotify Engineering"),
    _seed("amazon-dynamo", "Amazon’s Dynamo",
          "https://www.allthingsdistributed.com/2007/10/amazons_dynamo.html", "All Things Distributed", "Amazon", 2007,
          "The Dynamo paper describes a highly available key-value store that trades strict consistency for availability, using consistent hashing, vector clocks, sloppy quorums and hinted handoff.",
          ("Databases", "Availability", "Distributed systems"), 30, "aws-architecture",
          authors="Giuseppe DeCandia and co-authors", publisher_detail="SOSP research paper"),
    _seed("aws-timeouts-retries-jitter", "Timeouts, retries, and backoff with jitter",
          "https://builder.aws.com/content/3EumjoZascWd1oZiEgL8ORlv3qE/timeouts-retries-and-backoff-with-jitter",
          "AWS Builder Center", "Amazon", 2019,
          "From the Amazon Builders’ Library: how Amazon chooses timeouts, when retries make outages worse, and how exponential backoff with jitter prevents synchronized retry storms.",
          ("Resilience", "Retries", "Distributed systems"), 12, "aws-architecture",
          authors="Marc Brooker", publisher_detail="Amazon Builders’ Library"),
    _seed("discord-trillions-messages", "How Discord Stores Trillions of Messages",
          "https://discord.com/blog/how-discord-stores-trillions-of-messages", "Discord Engineering", "Discord", 2023,
          "Why Discord moved its message storage from Cassandra to ScyllaDB, and the Rust data services that coalesce requests to protect the database from hot partitions.",
          ("Databases", "Rust", "Scaling"), 15, "engineering-discord", publisher_detail="Discord Engineering Blog"),
    _seed("slack-outage-2021", "Slack’s Outage on January 4th 2021",
          "https://slack.engineering/slacks-outage-on-january-4th-2021/", "Engineering at Slack", "Slack", 2021,
          "A postmortem of how network saturation in a cloud provider triggered cascading failures in Slack’s autoscaling and provisioning on the first working day of the year.",
          ("Postmortem", "Autoscaling", "Reliability"), 12, "engineering-slack", publisher_detail="Engineering at Slack"),
    _seed("shopify-deconstructing-monolith", "Deconstructing the Monolith: Designing Software that Maximizes Developer Productivity",
          "https://shopify.engineering/deconstructing-monolith-designing-software-maximizes-developer-productivity",
          "Shopify Engineering", "Shopify", 2019,
          "Why Shopify chose a modular monolith over microservices for its core Rails application, and how it introduced component boundaries without splitting the codebase.",
          ("Modular monolith", "Architecture", "Developer productivity"), 12, "engineering-shopify",
          publisher_detail="Shopify Engineering"),
    _seed("figma-database-scaling", "How Figma’s databases team lived to tell the scale",
          "https://www.figma.com/blog/how-figmas-databases-team-lived-to-tell-the-scale/", "Figma Blog", "Figma", 2024,
          "How Figma scaled PostgreSQL through rapid growth by partitioning vertically and then sharding horizontally, including the query engine and migration tooling the team built.",
          ("PostgreSQL", "Sharding", "Database scaling"), 18, "figma-blog", publisher_detail="Figma engineering blog"),
    _seed("dropbox-sync-engine", "Rewriting the heart of our sync engine",
          "https://dropbox.tech/infrastructure/rewriting-the-heart-of-our-sync-engine", "Dropbox Tech", "Dropbox", 2020,
          "Why Dropbox rewrote its desktop sync engine in Rust, and the testing, data-model and incremental-rollout strategy that made the rewrite safe.",
          ("Rewrites", "Rust", "Testing"), 18, "engineering-dropbox", publisher_detail="Dropbox Tech Blog"),
    _seed("github-merge-queue", "How GitHub uses merge queue to ship hundreds of changes every day",
          "https://github.blog/engineering/engineering-principles/how-github-uses-merge-queue-to-ship-hundreds-of-changes-every-day/",
          "The GitHub Blog", "GitHub", 2024,
          "How GitHub moved its monolith deployments to a merge queue that groups and tests pull requests together, reducing deploy wait times for hundreds of daily changes.",
          ("CI/CD", "Monorepo", "Developer productivity"), 8, "github-engineering", publisher_detail="GitHub engineering blog"),
    # --- Game engineering: netcode, rendering, engines, NPC AI, physics (each link checked 2026-11-22) -----
    _seed("riot-valorant-netcode", "Peeking into VALORANT's Netcode",
          "https://www.riotgames.com/en/news/peeking-valorants-netcode", "Riot Games Tech Blog", "Riot Games", 2020,
          "VALORANT's gameplay and project tech leads explain how the team approached peeker's advantage, hit registration and simulation divergence in a competitive shooter, and the netcode trade-offs behind those decisions.",
          ("Netcode", "Multiplayer", "Game servers", "FPS"), 15, None, published="2020-07-28",
          authors="Matt deWet · David Straily", publisher_detail="Riot Games Tech Blog",
          why="A rare first-party look at why online shooters feel unfair and what a studio can actually change.",
          themes=("game-engineering", "distributed-systems")),
    _seed("riot-valorant-128-tick", "VALORANT's 128-Tick Servers",
          "https://www.riotgames.com/en/news/valorants-128-tick-servers", "Riot Games Tech Blog", "Riot Games", 2020,
          "A VALORANT engineer walks through cutting server frame time from about 50 ms to under 2 ms so game servers could run at 128 ticks per second, using code optimization, hardware tweaks and operating-system tuning.",
          ("Game servers", "Performance", "Profiling", "Linux"), 20, None, published="2020-08-31",
          authors="Brent Randall", publisher_detail="Riot Games Tech Blog",
          why="A concrete performance budget story: every millisecond per frame was found and removed on real servers.",
          themes=("game-engineering", "performance")),
    _seed("riot-fixing-the-internet", "Fixing the Internet for Real Time Applications: Part I",
          "https://www.riotgames.com/en/news/fixing-internet-real-time-applications-part-i", "Riot Games Tech Blog",
          "Riot Games", 2015,
          "The first part of Riot's series on why the public internet struggles with real-time games such as League of Legends, where milliseconds matter, and the networking problems Riot set out to solve for its players.",
          ("Networking", "Latency", "Multiplayer"), 12, None, published="2015-11-06", publisher_detail="Riot Games Tech Blog",
          why="Explains latency from the network's point of view, not just the game client's.",
          themes=("game-engineering", "cloud")),
    _seed("rockstar-rdr2-atmosphere", "Creating the Atmospheric World of Red Dead Redemption 2",
          "https://advances.realtimerendering.com/s2019/index.htm", "SIGGRAPH Advances in Real-Time Rendering",
          "Rockstar Games", 2019,
          "Rockstar North's Fabian Bauer presents the sky, cloud, fog and volumetric lighting techniques behind Red Dead Redemption 2's open world, designed to follow the physics of light transport while staying art-directable.",
          ("Rendering", "Volumetrics", "Open world", "Lighting"), 40, None, published="2019-07-29",
          authors="Fabian Bauer", publisher_detail="SIGGRAPH 2019 course talk · slides on the course page",
          why="One of the few detailed public talks from Rockstar's own graphics engineers.",
          themes=("game-engineering", "performance")),
    _seed("gta-v-graphics-study", "GTA V - Graphics Study",
          "https://www.adriancourreges.com/blog/2015/11/02/gta-v-graphics-study/", "Adrian Courrèges",
          "Adrian Courrèges", 2015,
          "An independent study that walks through the rendering passes GTA V uses to build a single frame, reconstructed by capturing and inspecting the game's draw calls. It is an outside analysis, not a Rockstar publication.",
          ("Rendering", "GTA V", "Rockstar", "Open world"), 25, None, published="2015-11-02",
          publisher_detail="Independent graphics analysis",
          why="The clearest public breakdown of how an open-world Rockstar frame comes together.",
          themes=("game-engineering", "performance")),
    _seed("epic-nanite", "A Deep Dive into Nanite Virtualized Geometry",
          "https://advances.realtimerendering.com/s2021/index.html", "SIGGRAPH Advances in Real-Time Rendering",
          "Epic Games", 2021,
          "Epic's engineers explain Nanite, the virtualized geometry system in Unreal Engine 5 that renders film-quality meshes with enormous triangle counts in real time.",
          ("Unreal Engine", "Rendering", "GPU", "Geometry"), 45, "unreal-engine-blog",
          authors="Brian Karis · Rune Stubbe · Graham Wihlidal", publisher_detail="SIGGRAPH 2021 course talk",
          why="The architecture behind one of the biggest shifts in real-time rendering in a decade.",
          themes=("game-engineering", "performance")),
    _seed("epic-lumen", "Lumen: Real-time Global Illumination in Unreal Engine 5",
          "https://advances.realtimerendering.com/s2022/index.html", "SIGGRAPH Advances in Real-Time Rendering",
          "Epic Games", 2022,
          "Epic's engineers present Lumen, Unreal Engine 5's real-time global illumination system, and the techniques it combines to deliver dynamic indirect lighting in shipping games.",
          ("Unreal Engine", "Global illumination", "Rendering", "Ray tracing"), 45, "unreal-engine-blog",
          authors="Daniel Wright · Krzysztof Narkowicz · Patrick Kelly", publisher_detail="SIGGRAPH 2022 course talk",
          why="Shows how a production engine fits dynamic lighting into a fixed frame budget.",
          themes=("game-engineering", "performance")),
    _seed("roblox-return-to-service", "Roblox Return to Service",
          "https://about.roblox.com/newsroom/2022/01/roblox-return-to-service-10-28-10-31-2021", "Roblox Newsroom",
          "Roblox", 2022,
          "Roblox's account, written with HashiCorp, of the 73-hour outage that took its platform down in October 2021: how a Consul cluster at the heart of its infrastructure failed, including streaming and BoltDB problems, and the slow road back.",
          ("Postmortem", "Consul", "Reliability", "Game infrastructure"), 25, None, published="2022-01-20",
          authors="Daniel Sturman with Roblox and HashiCorp engineers", publisher_detail="Roblox engineering postmortem",
          why="A candid postmortem of a multi-day outage at a platform serving tens of millions of players.",
          themes=("reliability", "game-engineering", "distributed-systems")),
    _seed("overwatch-ecs-netcode", "Overwatch Gameplay Architecture and Netcode",
          "https://www.gdcvault.com/play/1024001/-Overwatch-Gameplay-Architecture-and", "GDC Vault",
          "Blizzard Entertainment", 2017,
          "Blizzard's GDC talk on how Overwatch uses an Entity Component System architecture to keep gameplay code manageable as heroes and abilities grow, and how that architecture shapes the game's netcode.",
          ("Entity Component System", "Netcode", "Game architecture"), 40, None,
          publisher_detail="GDC 2017 talk", why="A widely cited case for ECS from a shipped, fast-paced multiplayer game.",
          themes=("game-engineering", "distributed-systems")),
    _seed("naughty-dog-fibers", "Parallelizing the Naughty Dog Engine Using Fibers",
          "https://www.gdcvault.com/play/1022186/Parallelizing-the-Naughty-Dog-Engine", "GDC Vault", "Naughty Dog", 2015,
          "A walkthrough of the engine changes needed to run The Last of Us Remastered at 60 fps on PlayStation 4, including the fiber-based job system and frame-centric engine design Naughty Dog adopted.",
          ("Job systems", "Multithreading", "Game engines", "Console"), 45, None,
          publisher_detail="GDC 2015 talk", why="A classic on spreading a game frame across every CPU core.",
          themes=("game-engineering", "performance")),
    _seed("bungie-halo-reach-networking", "I Shot You First: Networking the Gameplay of Halo: Reach",
          "https://www.gdcvault.com/play/1014345/I-Shot-You-First-Networking", "GDC Vault", "Bungie", 2011,
          "Bungie's David Aldridge on networking the gameplay of Halo: Reach, a fast-paced multiplayer shooter, and the techniques used to keep play feeling responsive over real-world connections.",
          ("Netcode", "Multiplayer", "Game networking"), 45, None, authors="David Aldridge", publisher_detail="GDC 2011 talk",
          why="A foundational talk on multiplayer networking that engineers still reference.",
          themes=("game-engineering", "distributed-systems")),
    _seed("fear-goap-ai", "Building the AI of F.E.A.R. with Goal Oriented Action Planning",
          "https://www.gamedeveloper.com/design/building-the-ai-of-f-e-a-r-with-goal-oriented-action-planning",
          "Game Developer", "Game Developer", 2020,
          "How Jeff Orkin at Monolith Productions used Goal-Oriented Action Planning to give F.E.A.R.'s enemies adaptive, believable behaviour, an approach to NPC AI that many later games built on.",
          ("NPC AI", "Planning", "Game AI"), 12, None, published="2020-05-07", publisher_detail="Game Developer featured blog",
          why="Explains a planning technique behind some of the most praised enemy AI in games.",
          themes=("game-engineering", "ai")),
    _seed("box2d-solver2d", "Solver2D",
          "https://box2d.org/posts/2024/02/solver2d/", "Box2D Blog", "Box2D", 2024,
          "Box2D's creator builds a test bed to compare rigid-body physics solvers side by side while working on Box2D v3.0, after a stability problem prompted a closer look at the engine's growing complexity.",
          ("Physics engines", "Rigid bodies", "Simulation"), 20, "box2d-blog", published="2024-02-05",
          authors="Erin Catto", publisher_detail="Box2D Blog",
          why="An unusually honest comparison of physics solver trade-offs from the author of Box2D.",
          themes=("game-engineering", "performance")),
    _seed("gaffer-game-networking", "What Every Programmer Needs To Know About Game Networking",
          "https://gafferongames.com/post/what_every_programmer_needs_to_know_about_game_networking/", "Gaffer On Games",
          "Gaffer On Games", 2010,
          "Glenn Fiedler's introduction to how multiplayer games work over the network, from early peer-to-peer lockstep models to client-server architectures with client-side prediction.",
          ("Netcode", "Multiplayer", "Client-side prediction"), 11, None, published="2010-02-24",
          authors="Glenn Fiedler", publisher_detail="Gaffer On Games",
          why="The standard starting point for understanding multiplayer netcode.",
          themes=("game-engineering", "distributed-systems")),
    _seed("discord-webrtc-voice", "How Discord Handles Two and Half Million Concurrent Voice Users using WebRTC",
          "https://discord.com/blog/how-discord-handles-two-and-half-million-concurrent-voice-users-using-webrtc",
          "Discord Blog", "Discord", 2018,
          "Discord explains the voice architecture it built on WebRTC for gamers, and how the system scaled to handle two and a half million concurrent voice users.",
          ("WebRTC", "Voice", "Real-time systems", "Scaling"), 10, "engineering-discord", published="2018-09-10",
          authors="Jozsef Vass", publisher_detail="Discord Engineering",
          why="Real-time media at gaming scale, explained by the team that runs it.",
          themes=("distributed-systems", "game-engineering")),
    _seed("discord-go-to-rust", "Why Discord is switching from Go to Rust",
          "https://discord.com/blog/why-discord-is-switching-from-go-to-rust", "Discord Blog", "Discord", 2020,
          "Why Discord rewrote a latency-sensitive service from Go to Rust after garbage-collection pauses caused regular latency spikes, and what the rewrite did to its performance.",
          ("Rust", "Go", "Garbage collection", "Latency"), 10, "engineering-discord", published="2020-02-04",
          authors="Jesse Howarth", publisher_detail="Discord Engineering",
          why="A measured language-migration story driven by profiles, not fashion.",
          themes=("performance",)),

    # --- Scale, infrastructure, AI and security (each link checked 2026-11-22) -------------------------
    _seed("cloudflare-cloudbleed", "Incident report on memory leak caused by Cloudflare parser bug",
          "https://blog.cloudflare.com/incident-report-on-memory-leak-caused-by-cloudflare-parser-bug/",
          "Cloudflare Blog", "Cloudflare", 2017,
          "Cloudflare's incident report on a bug in its HTML parser that leaked server memory into responses, reported by Google Project Zero, and how the team found, fixed and cleaned up after it.",
          ("Postmortem", "Memory safety", "Parsers"), 16, "cloudflare-blog", published="2017-02-23",
          authors="John Graham-Cumming", publisher_detail="Cloudflare Blog",
          why="A detailed security postmortem showing how one parser bug reached across a global network.",
          themes=("security", "reliability")),
    _seed("meta-threads-infrastructure", "How Meta built the infrastructure for Threads",
          "https://engineering.fb.com/2023/12/19/core-infra/how-meta-built-the-infrastructure-for-threads/",
          "Engineering at Meta", "Meta", 2023,
          "Meta explains the infrastructure that let Threads launch to an unprecedented wave of sign-ups in July 2023, and how reusing existing large-scale systems let the product scale quickly.",
          ("Launch scaling", "Infrastructure", "Social graph"), 12, "meta-engineering", published="2023-12-19",
          authors="Laine Campbell · Chunqiang (CQ) Tang", publisher_detail="Engineering at Meta",
          why="How a brand-new app absorbed a launch-day surge by building on proven infrastructure.",
          themes=("distributed-systems", "cloud")),
    _seed("whatsapp-2-million-connections", "1 million is so 2011",
          "https://blog.whatsapp.com/1-million-is-so-2011", "WhatsApp Blog", "WhatsApp", 2012,
          "A short post on how WhatsApp pushed a single server past two million concurrent TCP connections, with CPU and memory to spare, and the hardware and tuning behind it.",
          ("TCP", "Connection scaling", "FreeBSD"), 4, None, published="2012-01-06", publisher_detail="WhatsApp Blog",
          why="A famous data point on how far one well-tuned machine can go.",
          themes=("performance", "distributed-systems")),
    _seed("netflix-video-pipeline-microservices", "Rebuilding Netflix Video Processing Pipeline with Microservices",
          "https://netflixtechblog.com/rebuilding-netflix-video-processing-pipeline-with-microservices-4e5e6310e359",
          "Netflix Technology Blog", "Netflix", 2024,
          "Netflix describes rebuilding the pipeline that encodes its video for streaming as a set of microservices, and what the new architecture changed for the teams that run it.",
          ("Microservices", "Video encoding", "Streaming"), 9, "netflix-techblog", published="2024-01-10",
          publisher_detail="Netflix TechBlog · Medium publisher estimate", read_time_basis="publisher",
          why="A real migration from a monolithic media pipeline, with the reasons spelled out.",
          themes=("distributed-systems", "cloud")),
    _seed("uber-docstore-cache", "How Uber Serves Over 40 Million Reads Per Second from Online Storage Using an Integrated Cache",
          "https://www.uber.com/blog/how-uber-serves-over-40-million-reads-per-second-using-an-integrated-cache/",
          "Uber Engineering", "Uber", 2024,
          "How Uber's Docstore, an in-house distributed database built on MySQL, serves more than 40 million reads per second by building a cache into the storage layer.",
          ("Caching", "MySQL", "Distributed databases"), 15, "uber-engineering", published="2024-02-15",
          authors="Preetham Narayanareddy · Eli Pozniansky · Zurab Kutsia", publisher_detail="Uber Engineering",
          why="Cache consistency at a scale most teams never reach, explained in detail.",
          themes=("databases", "performance")),
    _seed("project-zero-forcedentry", "A deep dive into an NSO zero-click iMessage exploit: Remote Code Execution",
          "https://projectzero.google/2021/12/a-deep-dive-into-nso-zero-click.html", "Google Project Zero",
          "Google", 2021,
          "Google Project Zero dissects FORCEDENTRY, NSO Group's zero-click iMessage exploit, showing how a crafted image file led to remote code execution on iPhones without any user interaction.",
          ("Exploits", "iOS", "Zero-click"), 25, "project-zero", published="2021-12-15",
          authors="Ian Beer · Samuel Groß", publisher_detail="Project Zero",
          why="One of the most technically remarkable exploit analyses ever published.",
          themes=("security",)),
    _seed("meta-genai-infrastructure", "Building Meta's GenAI Infrastructure",
          "https://engineering.fb.com/2024/03/12/data-center-engineering/building-metas-genai-infrastructure/",
          "Engineering at Meta", "Meta", 2024,
          "Meta details two 24,000-GPU clusters built for generative AI training, covering their hardware, network, storage and software design.",
          ("GPU clusters", "AI training", "Networking", "Storage"), 10, "meta-engineering", published="2024-03-12",
          authors="Kevin Lee · Adi Gangidi · Mathew Oldham", publisher_detail="Engineering at Meta",
          why="What it takes, physically and in software, to train large models.",
          themes=("ai", "cloud")),
    _seed("anthropic-contextual-retrieval", "Introducing Contextual Retrieval",
          "https://www.anthropic.com/news/contextual-retrieval", "Anthropic", "Anthropic", 2024,
          "Anthropic explains Contextual Retrieval, a technique that adds chunk-specific context before embedding and keyword indexing to reduce retrieval failures in RAG systems.",
          ("RAG", "Embeddings", "BM25", "Retrieval"), 12, "anthropic-engineering", published="2024-09-19",
          publisher_detail="Anthropic engineering",
          why="A practical, measurable improvement for anyone building retrieval-augmented generation.",
          themes=("ai",)),
    _seed("microsoft-graphrag", "GraphRAG: Unlocking LLM discovery on narrative private data",
          "https://www.microsoft.com/en-us/research/blog/graphrag-unlocking-llm-discovery-on-narrative-private-data/",
          "Microsoft Research", "Microsoft", 2024,
          "Microsoft Research introduces GraphRAG, which uses an LLM to build a knowledge graph from private text and uses that graph to answer questions that plain vector retrieval handles poorly.",
          ("RAG", "Knowledge graphs", "LLMs"), 10, "microsoft-research", published="2024-02-13",
          authors="Jonathan Larson · Steven Truitt", publisher_detail="Microsoft Research Blog",
          why="A different shape of retrieval for questions that span a whole document collection.",
          themes=("ai",)),
    _seed("amazon-dynamodb-paper", "Amazon DynamoDB: A Scalable, Predictably Performant, and Fully Managed NoSQL Database Service",
          "https://www.usenix.org/conference/atc22/presentation/elhemali", "USENIX", "Amazon", 2022,
          "The USENIX ATC 2022 paper on how Amazon DynamoDB delivers consistent performance at any scale as a fully managed NoSQL service, and what AWS learned from operating it.",
          ("DynamoDB", "NoSQL", "Distributed databases"), 30, "amazon-science", kind="research",
          authors="Mostafa Elhemali and co-authors", publisher_detail="USENIX ATC 2022 research paper",
          why="Rare detail on how a hyperscale managed database is actually run.",
          themes=("databases", "distributed-systems")),
)
# Reviewed themes where keyword evidence alone would mislabel a classic.
for _ident, _themes in {
    "google-mapreduce": ("distributed-systems", "cloud"),
    "google-borg": ("cloud", "distributed-systems"),
    "paloalto-unified-data-platform": ("databases", "distributed-systems", "cloud"),
    "uber-big-data-platform": ("databases", "distributed-systems"),
    "anthropic-teams-claude-code": ("ai", "engineering-practice"),
    "anthropic-opus-4-6": ("ai",),
    "cloudflare-pingora": ("performance", "cloud"),
}.items():
    next(article for article in CURATED_CURIOSITY if article["id"] == _ident)["themes"] = list(_themes)

SEEDS_BY_ID = {article["id"]: article for article in CURATED_CURIOSITY}

_technical_signals = {
    "architecture": re.compile(r"\barchitect(?:ure|ural)\b", re.I),
    "infrastructure": re.compile(r"\binfrastructure\b", re.I),
    "distributed systems": re.compile(r"\bdistributed\b|\breplication\b", re.I),
    "scaling": re.compile(r"\bscal(?:e|ed|ing|ability)\b|\bthroughput\b|\bcapacity\b", re.I),
    "reliability": re.compile(r"\breliab\w*\b|\bfault[- ]tolerant\b|\bavailability\b|\bpostmortem\b", re.I),
    "software design": re.compile(r"\bdesign(?:ed|ing)?\b|\bbuild system\b|\bmonorepo\b|\bcodebase\b", re.I),
    "data systems": re.compile(r"\bdatabase\w*\b|\bstorage\b|\bpipeline\b|\bdata movement\b", re.I),
    "performance": re.compile(r"\blatency\b|\bmemory\b|\bkernel\b|\bperformance\b|\bgpu\b|\bframe time\b|"
                             r"\boptimi[sz](?:e|ed|ing|ation)\b|\bprofil(?:e|ed|ing)\b", re.I),
    "game engineering": re.compile(r"\bnetcode\b|\brender(?:ing|er)\b|\bshaders?\b|\bgame engines?\b|"
                                   r"\bsimulation\b|\bphysics\b|\bmultiplayer\b|\bray tracing\b|"
                                   r"\bglobal illumination\b|\bgame servers?\b", re.I),
    "engineering practice": re.compile(r"\bhow we (?:built|designed|scaled|migrated|operate|test)\b|\bincident report\b", re.I),
}
_promotional = re.compile(
    r"\b(?:sponsored|partner content|sign up|register now|webinar|giveaway|limited time|"
    r"introducing our new|now available|available today|pricing plans|product launch|buy now)\b", re.I)
_allowed_coverage = {"article", "publisher", "journal", "preprint"}
_company_names = {"google": "Google", "microsoft": "Microsoft", "amazon": "Amazon", "meta": "Meta",
                  "stripe": "Stripe", "uber": "Uber", "netflix": "Netflix", "airbnb": "Airbnb",
                  "spotify": "Spotify", "openai": "OpenAI", "anthropic": "Anthropic", "razorpay": "Razorpay"}
_technical_news_sources = {"openai-news", "anthropic-news"}


# --- Curation taxonomy -------------------------------------------------------------------------------
# Themes, formats and technologies are read only from the title, publisher excerpt and reviewed tags.
# Nothing here infers details an article does not state.
THEMES = (
    ("game-engineering", "Game engineering", re.compile(
        r"\b(?:game|games|gaming|gameplay|netcode|multiplayer|tick ?rate|game engines?|unreal|unity|godot|"
        r"rendering|renderer|shaders?|ray tracing|global illumination|graphics|open[- ]world|npcs?|"
        r"physics engines?|rigid[- ]body|animation|frame rate|fps|consoles?|playstation|xbox|esports|"
        r"valorant|fortnite|roblox|overwatch|halo|league of legends|gta|rockstar|factorio|simulation|"
        r"frame time)\b", re.I)),
    ("ai", "AI & LLMs", re.compile(
        r"\b(?:llms?|large language models?|language models?|transformers?|rag|retrieval|embeddings?|agents?|"
        r"agentic|inference|fine[- ]tun\w*|training runs?|model serving|prompt\w*|claude|gpt[\w.-]*|"
        r"machine learning|deep learning|neural|ml|ai|attention|tokens?|vector search)\b", re.I)),
    ("distributed-systems", "Distributed systems", re.compile(
        r"\b(?:distributed|consensus|replication|raft|paxos|microservices?|kafka|event[- ]driven|queues?|"
        r"sharding|shards?|partition\w*|service mesh|load balanc\w*|rpc|grpc|asynchronous|concurren\w*|"
        r"real[- ]time systems?|websockets?|webrtc|pub/?sub|stream processing)\b", re.I)),
    ("databases", "Databases & storage", re.compile(
        r"\b(?:databases?|postgres\w*|mysql|sqlite|sql|nosql|key[- ]value|dynamodb|cassandra|scylla\w*|"
        r"redis|memcache\w*|cach(?:e|es|ing)|storage|indexes|indexing|b-?trees?|lsm|olap|oltp|data warehouse|"
        r"clickhouse|bigtable|spanner|file systems?)\b", re.I)),
    ("cloud", "Cloud & infrastructure", re.compile(
        r"\b(?:kubernetes|k8s|containers?|cloud|data ?centers?|clusters?|serverless|cdn|edge network|"
        r"networking|network|bgp|dns|infrastructure|terraform|virtual machines?|vms?|gpu clusters?|"
        r"deploy\w*|aws|gcp|azure)\b", re.I)),
    ("security", "Security", re.compile(
        r"\b(?:security|vulnerabilit\w*|exploits?|attacks?|attackers?|malware|ransomware|zero[- ]day|"
        r"zero[- ]click|cves?|encryption|cryptograph\w*|authentication|sandbox\w*|memory safety|threat\w*|"
        r"phishing|supply chain)\b", re.I)),
    ("performance", "Performance", re.compile(
        r"\b(?:latency|performance|optimi[sz]\w*|throughput|profil\w*|benchmarks?|faster|speed ?up|"
        r"cpu|gpu|memory|simd|jit|compil\w*|garbage collection|frame time|p99|tail latency|efficien\w*)\b", re.I)),
    ("reliability", "Reliability & postmortems", re.compile(
        r"\b(?:postmortem|post-mortem|outages?|incidents?|incident report|reliab\w*|resilien\w*|sre|"
        r"availability|failover|on-?call|disaster recovery|chaos engineering|return to service|downtime)\b", re.I)),
    ("engineering-practice", "Engineering practice", re.compile(
        r"\b(?:monorepos?|build systems?|code review|developer productivity|ci/cd|merge queue|testing|"
        r"migrations?|rewrit\w*|refactor\w*|monolith|engineering culture|source control|version control|"
        r"git)\b", re.I)),
)
THEME_LABELS = {ident: label for ident, label, _ in THEMES}

FORMATS = {
    "postmortem": "Postmortem",
    "case-study": "Case study",
    "paper": "Research paper",
    "talk": "Conference talk",
    "deep-dive": "Deep dive",
}
_postmortem = re.compile(r"\b(?:postmortem|post-mortem|outage|incident report|return to service|root cause)\b", re.I)
_case_study = re.compile(
    r"\bhow (?:we|[\w.&'’-]+(?: [\w.&'’-]+)?) (?:built|build|scaled|scale|migrated|rebuilt|rewrote|redesigned|"
    r"serves?|handles?|stores?|runs?|ships?|deploy\w*|moderni[sz]ed|keeps?|uses?|optimi[sz]ed|cut|reduced|"
    r"made|sped up|improved|designed|tackled|fixed)\b|\bat scale\b|\bcase study\b|"
    r"\bbehind\b|\bjourney\b|\blessons\b", re.I)
_talk_hosts = ("gdcvault.com", "advances.realtimerendering.com", "youtube.com", "youtu.be", "infoq.com")
_paper_hosts = ("usenix.org", "research.google", "arxiv.org", "dl.acm.org", "static.googleusercontent.com",
                "pdos.csail.mit.edu", "allthingsdistributed.com", "vldb.org")

TECHNOLOGIES = tuple((label, re.compile(pattern, re.I)) for label, pattern in (
    ("Kubernetes", r"\bkubernetes\b|\bk8s\b"), ("Kafka", r"\bkafka\b"), ("PostgreSQL", r"\bpostgres(?:ql)?\b"),
    ("MySQL", r"\bmysql\b"), ("Redis", r"\bredis\b"), ("Memcached", r"\bmemcache[d]?\b"),
    ("DynamoDB", r"\bdynamodb\b"), ("Cassandra", r"\bcassandra\b"), ("ScyllaDB", r"\bscylla(?:db)?\b"),
    ("ClickHouse", r"\bclickhouse\b"), ("SQLite", r"\bsqlite\b"), ("Spanner", r"\bspanner\b"),
    ("Bigtable", r"\bbigtable\b"), ("Elasticsearch", r"\belasticsearch\b"), ("Consul", r"\bconsul\b"),
    ("BoltDB", r"\bboltdb\b"), ("etcd", r"\betcd\b"), ("gRPC", r"\bgrpc\b"), ("GraphQL", r"\bgraphql\b"),
    ("WebRTC", r"\bwebrtc\b"), ("WebAssembly", r"\bwebassembly\b|\bwasm\b"), ("eBPF", r"\bebpf\b"),
    ("Rust", r"\brust\b"), ("Go", r"\bgolang\b|\bgo\b(?= (?:service|code|runtime|to rust|version|program))|(?<=from )go\b"),
    ("C++", r"\bc\+\+"), ("Python", r"\bpython\b"), ("Java", r"\bjava\b(?!script)"), ("Erlang", r"\berlang\b"),
    ("Elixir", r"\belixir\b"), ("TypeScript", r"\btypescript\b"), ("Swift", r"\bswift\b"), ("Kotlin", r"\bkotlin\b"),
    ("Linux", r"\blinux\b"), ("FreeBSD", r"\bfreebsd\b"), ("TCP", r"\btcp\b"), ("UDP", r"\budp\b"),
    ("QUIC", r"\bquic\b"), ("HTTP/3", r"\bhttp/3\b"), ("BGP", r"\bbgp\b"), ("DNS", r"\bdns\b"),
    ("NGINX", r"\bnginx\b"), ("Envoy", r"\benvoy\b"), ("Terraform", r"\bterraform\b"), ("Docker", r"\bdocker\b"),
    ("AWS", r"\baws\b|amazon web services"), ("Google Cloud", r"\bgoogle cloud\b|\bgcp\b"), ("Azure", r"\bazure\b"),
    ("CUDA", r"\bcuda\b"), ("GPU", r"\bgpus?\b"), ("TPU", r"\btpus?\b"), ("PyTorch", r"\bpytorch\b"),
    ("LLM", r"\bllms?\b|large language models?"), ("RAG", r"\brag\b|retrieval[- ]augmented"),
    ("Embeddings", r"\bembeddings?\b"), ("Vector search", r"\bvector (?:search|database)s?\b"),
    ("AI agents", r"\b(?:ai |llm )?agents?\b(?= |$|[.,;:])"), ("MCP", r"\bmcp\b|model context protocol"),
    ("Transformers", r"\btransformers?\b"), ("Knowledge graphs", r"\bknowledge graphs?\b"), ("BM25", r"\bbm25\b"),
    ("Unreal Engine", r"\bunreal(?: engine)?\b|\bue5\b"), ("Unity", r"\bunity\b(?! of)"), ("Godot", r"\bgodot\b"),
    ("Vulkan", r"\bvulkan\b"), ("DirectX", r"\bdirectx\b|\bdx12\b|\bdxr\b"), ("Ray tracing", r"\bray[- ]tracing\b"),
    ("Global illumination", r"\bglobal illumination\b"), ("Entity Component System", r"\bentity component system\b|\becs\b"),
    ("Netcode", r"\bnetcode\b|\bnetworking the gameplay\b|\bclient-side prediction\b"),
    ("Job systems", r"\bjob systems?\b|\bfibers?\b"), ("Physics engines", r"\bphysics (?:engines?|solvers?)\b|\brigid[- ]body\b"),
    ("Game AI", r"\bnpc\b|\bgoal[- ]oriented action planning\b|\bgame ai\b"),
    ("Microservices", r"\bmicroservices?\b"), ("Service mesh", r"\bservice mesh\b"), ("Load balancing", r"\bload balanc\w*\b"),
    ("Caching", r"\bcach(?:e|es|ing)\b"), ("Sharding", r"\bshard(?:s|ing|ed)?\b"), ("Consensus", r"\bconsensus\b|\braft\b|\bpaxos\b"),
    ("Observability", r"\bobservability\b|\btracing\b(?! ray)|\bopentelemetry\b"),
    ("Monorepo", r"\bmonorepos?\b|single repository"), ("Git", r"\bgit\b"),
))
# Releases, product announcements and event recaps are not deep dives, even on engineering blogs.
_announcement = re.compile(
    r"\b(?:release notes|released|is (?:now )?(?:available|here|live)|announc\w*|launch(?:es|ing)? (?:of|our)|"
    r"dev snapshot|beta \d|alpha \d|release candidate|v?\d+\.\d+(?:\.\d+)? (?:is out|released)|showreel|"
    r"sponsor\w*|we'?re hiring|join us|meetup|recap|roundup|weekly|newsletter|this week in|webinar|"
    r"livestream|giveaway|coupon|discount)\b", re.I)
_quantitative = re.compile(
    r"\b\d[\d,.]*\s?(?:ms|µs|us|ns|million|billion|trillion|petabytes?|terabytes?|pb|tb|gb|x|qps|rps|"
    r"nodes|servers|machines|gpus|cores|users|requests|connections|ticks?|fps|percent)\b|\d+\s?%", re.I)
CURIOSITY_COMPANY_FRESH_CAP = 3

LEVELS = {"introductory": "Introductory", "intermediate": "Intermediate", "advanced": "Advanced"}
_introductory = re.compile(
    r"\b(?:an introduction|introduction to|intro to|beginners?|getting started|eli5|explained|basics|primer|101|"
    r"what every (?:programmer|developer|engineer)|guide to|a gentle|for everyone|step[- ]by[- ]step)\b", re.I)
_advanced = re.compile(
    r"\b(?:consensus|paxos|raft|linearizab\w*|lock[- ]free|kernel|compilers?|jit|exploits?|zero[- ]click|"
    r"virtuali[sz]ed geometry|global illumination|volumetric\w*|formal verification|ebpf|simd|"
    r"garbage collect\w*|memory safety|tail latency|fibers?|job systems?|distributed transactions?|"
    r"replication protocol|cache coherence|gpu clusters?)\b", re.I)
# Fresh cards at or above this depth score are saved so they outlive the 90-day archive.
KEEP_SCORE = 10
MAX_LIBRARY_CARDS = 40


def _text(article):
    tags = " ".join(str(tag) for tag in article.get("tags") or ())
    return (f"{article.get('title', '')} {article.get('description') or article.get('cleanSummary') or ''} "
            f"{tags}")


def card_themes(article):
    """Themes ranked by evidence: a title match counts three times as much as the excerpt or tags."""
    reviewed = [theme for theme in article.get("themes") or () if theme in THEME_LABELS]
    if reviewed:
        return reviewed[:3]
    title = str(article.get("title", ""))
    body = f"{article.get('description') or article.get('cleanSummary') or ''} " \
           f"{' '.join(str(tag) for tag in article.get('tags') or ())}"
    scored = []
    for order, (ident, _, matcher) in enumerate(THEMES):
        score = 3 * len(matcher.findall(title)) + len(matcher.findall(body))
        if score:
            scored.append((-score, order, ident))
    return [ident for _, _, ident in sorted(scored)[:3]] or ["engineering-practice"]


def card_format(article):
    text = _text(article)
    host = urlsplit(str(article.get("url", ""))).hostname or ""
    detail = str(article.get("publisher_detail", ""))
    if _postmortem.search(text):
        return "postmortem"
    if any(host == item or host.endswith("." + item) for item in _talk_hosts) or re.search(r"\btalk\b", detail, re.I):
        return "talk"
    if (article.get("kind") == "research" or any(host == item or host.endswith("." + item) for item in _paper_hosts)
            or re.search(r"\bpaper\b", detail, re.I)):
        return "paper"
    if _case_study.search(str(article.get("title", ""))):
        return "case-study"
    return "deep-dive"


def card_technologies(article, limit=6):
    text = _text(article)
    found = [label for label, matcher in TECHNOLOGIES if matcher.search(text)]
    # "Caching" adds nothing next to a named cache, and "GPU" adds nothing next to CUDA.
    if {"Redis", "Memcached"} & set(found):
        found = [label for label in found if label != "Caching"]
    return found[:limit]


def card_level(article):
    """Reading level from what the source says about itself: talks, papers and internals read as advanced."""
    text = f"{_text(article)} {article.get('publisher_detail', '')}"
    if _introductory.search(str(article.get("title", ""))) or (_introductory.search(text) and not _advanced.search(text)):
        return "introductory"
    if card_format(article) in {"paper", "talk"} or len(_advanced.findall(text)) >= 1:
        return "advanced"
    return "intermediate"


def quality_score(article):
    """Technical depth signal for ranking archive discoveries; never used to rewrite content."""
    title = str(article.get("title", ""))
    description = str(article.get("description") or article.get("cleanSummary") or "")
    score = curiosity_score(article)
    if card_format(article) in {"postmortem", "case-study", "paper", "talk"}:
        score += 2
    score += min(2, len(_quantitative.findall(f"{title} {description}")))
    score += min(2, len(card_technologies(article)) // 2)
    if THEMES[0][2].search(title):
        score += 1  # Game engineering is rare in feeds; give it a little room.
    if _announcement.search(title):
        score -= 4
    return score


def curiosity_article(ident):
    """Return a copy of a manually reviewed source-backed card, if it is a seed."""
    article = SEEDS_BY_ID.get(ident)
    return deepcopy(article) if article else None


def curiosity_score(article):
    title = str(article.get("title", ""))
    description = str(article.get("description") or article.get("cleanSummary") or "")
    return sum((3 if matcher.search(title) else 0) + (1 if matcher.search(description) else 0)
               for matcher in _technical_signals.values())


def is_curiosity_candidate(article):
    """Keep cards to recent, English, excerpt-backed engineering insight."""
    source = BY_ID.get(article.get("source_id"))
    if not source or not source.enabled or (source.kind not in {"engineering", "research"}
                                               and source.id not in _technical_news_sources):
        return False
    if source.coverage not in _allowed_coverage or source.language not in {"en", "und"}:
        return False
    title = sanitize_text(article.get("title"), 500)
    description = sanitize_text(article.get("description") or article.get("cleanSummary"), 700)
    if len(title) < 16 or len(description) < 80 or _promotional.search(f"{title} {description}"):
        return False
    if _announcement.search(title):
        return False
    if not is_english_article({**article, "title": title, "description": description}):
        return False
    try:
        published = datetime.fromisoformat(str(article.get("published_at", "")).replace("Z", "+00:00"))
        if published.tzinfo is None:
            return False
        now = datetime.now(UTC)
        if published > now + timedelta(days=1) or published < now - timedelta(days=90):
            return False
    except (TypeError, ValueError):
        return False
    return curiosity_score({**article, "title": title, "description": description}) >= 3


def _candidate_sources():
    return tuple(source.id for source in DEFAULT_SOURCES if source.enabled
                 and (source.kind in {"engineering", "research"} or source.id in _technical_news_sources)
                 and source.coverage in _allowed_coverage
                 and source.language in {"en", "und"})


def _identity(article):
    try:
        url = canonical_url(article.get("url", ""))
    except (TypeError, ValueError):
        url = ""
    title = search_text(article.get("title", ""))
    return url, title, {term for term in title.split() if len(term) > 2}


def _is_duplicate(article, selected):
    url, title, terms = _identity(article)
    for existing in selected:
        other_url, other_title, other_terms = _identity(existing)
        if (url and url == other_url) or (title and title == other_title):
            return True
        if len(terms) >= 5 and len(other_terms) >= 5:
            union = terms | other_terms
            if union and len(terms & other_terms) / len(union) >= 0.84:
                return True
    return False


def _tags(article):
    text = f"{article.get('title', '')} {article.get('description', '')}".casefold()
    tags = []
    for label, matcher in _technical_signals.items():
        if matcher.search(text):
            tags.append(label.title())
    return tags[:4] or ["Engineering"]


def _company(article):
    source = BY_ID.get(article.get("source_id"))
    if not source:
        return article.get("publisher") or "Technology"
    if name := _company_names.get(source.publisher_family):
        return name
    label = source.label.removeprefix("The ")
    for suffix in (" on Medium", " TechBlog", " Engineering Blog", " Engineering", " Blog"):
        label = label.removesuffix(suffix)
    return label or source.label


def _estimated_read_minutes(article):
    measured = article.get("reading_time_minutes")
    if type(measured) is int and 1 <= measured <= 120:
        return measured, "publisher"
    estimate = article.get("estimated_reading_minutes")
    if type(estimate) is int and 1 <= estimate <= 120:
        return estimate, article.get("reading_time_basis", "estimate")
    # The app does not fetch full article bodies. Use a clearly marked editorial estimate.
    return 8, "estimate"


def _card(article, summaries):
    source = BY_ID.get(article.get("source_id"))
    public = public_article(article)
    summary = summaries.get(article["id"], {})
    read_minutes, read_basis = _estimated_read_minutes(article)
    published = str(article.get("published_at") or "")
    year_match = re.match(r"\d{4}", published)
    authors = sanitize_text(article.get("author"), 200)
    themes = card_themes(article)
    return {
        "id": article["id"],
        "title": public["title"],
        "company": article.get("company") or _company(article),
        "publisher": public["publisher"],
        "publisher_detail": article.get("publisher_detail", ""),
        "author": authors,
        "published_at": published,
        "year": article.get("year") or (int(year_match.group()) if year_match else None),
        "summary": sanitize_text(summary.get("summary") or public["cleanSummary"], 900),
        "summary_basis": summary.get("summary_basis") or public["summary_basis"],
        "tags": list(article.get("tags") or _tags(article))[:5],
        "themes": themes,
        "theme": themes[0],
        "format": card_format(article),
        "level": card_level(article),
        "technologies": card_technologies(article),
        "why_read": sanitize_text(article.get("why_read") or summary.get("whyItMatters"), 300),
        "read_minutes": read_minutes,
        "read_time_basis": read_basis,
        "url": public["url"],
        "source_id": article["source_id"],
        "kind": source.kind if source else article.get("kind", "engineering"),
        "description": article.get("description", ""),
        "seed": bool(article.get("curiosity_seed")),
    }


MAX_CURIOSITY_CARDS = 160
# Fresh archive discoveries get a reserved share so evergreen seeds never crowd them out.
FRESH_SLOT_SHARE = 3
MAX_FRESH_CARDS = 40


def _fresh_discoveries(store, limit):
    if not store or limit <= 0:
        return []
    candidates = store.curiosity_candidates(_candidate_sources(), hours=90 * 24, limit=200)
    eligible = [restore_metadata(article) for article in candidates if is_curiosity_candidate(article)]
    # Stable tie-breaks: higher technical signal, then newer publication, then ID.
    eligible.sort(key=lambda item: str(item.get("id", "")))
    eligible.sort(key=lambda item: str(item.get("published_at", "")), reverse=True)
    eligible.sort(key=quality_score, reverse=True)
    # Compare against every reviewed seed, not just the ones shown, so a seed never reappears as "fresh".
    seen = list(CURATED_CURIOSITY)
    unique = []
    for article in eligible:
        if _is_duplicate(article, seen):
            continue
        seen.append(article)
        unique.append(article)
    # Keep any one company from filling the fresh shelf; its extra stories fill leftover space in rank order.
    per_company, fresh, overflow = {}, [], []
    for article in unique:
        company = _company(article)
        if per_company.get(company, 0) < CURIOSITY_COMPANY_FRESH_CAP:
            per_company[company] = per_company.get(company, 0) + 1
            fresh.append(article)
        else:
            overflow.append(article)
    return (fresh + overflow)[:limit]


def featured_seeds():
    """Reviewed seeds in a theme-balanced order: one from each primary theme in turn."""
    queues = {}
    # Within a theme, the deepest pieces (postmortems, talks, papers, case studies with numbers) lead.
    for article in sorted(CURATED_CURIOSITY, key=quality_score, reverse=True):
        queues.setdefault(card_themes(article)[0], []).append(article)
    order = [ident for ident, _, _ in THEMES if ident in queues]
    ordered = []
    while any(queues[ident] for ident in order):
        for ident in order:
            if queues[ident]:
                ordered.append(queues[ident].pop(0))
    return ordered


def _interleave(seeds, fresh):
    """Show a fresh discovery after every two evergreen seeds, then whatever is left."""
    ordered = []
    seeds, fresh = list(seeds), list(fresh)
    while seeds or fresh:
        ordered.extend(seeds[:2])
        del seeds[:2]
        if fresh:
            ordered.append(fresh.pop(0))
    return ordered


def build_curiosity_cards(store, *, limit=24):
    """Blend verified evergreen seeds with high-signal records in the archive."""
    limit = max(1, min(int(limit), MAX_CURIOSITY_CARDS))
    reserve = min(MAX_FRESH_CARDS, max(1, limit // FRESH_SLOT_SHARE)) if limit > 1 else 0
    fresh = _fresh_discoveries(store, max(reserve, limit - len(CURATED_CURIOSITY)))
    seed_count = min(len(CURATED_CURIOSITY), limit - min(len(fresh), reserve))
    fresh = fresh[:limit - seed_count]
    selected = _interleave([deepcopy(article) for article in featured_seeds()[:seed_count]], fresh)

    summaries = {}
    summary_targets = [article for article in selected if not article.get("curiosity_seed")]
    if summary_targets:
        try:
            from app.web_digest import build_digest
            digest = build_digest(summary_targets, "Reader", "Engineering systems and lessons learned", store=store,
                                  pinned_ids=[article["id"] for article in summary_targets], persona="engineer",
                                  style="technical", all_pool=summary_targets)
            summaries = {article["digest_id"]: article for article in digest.get("articles", [])}
        except Exception as error:
            # Preserve the source excerpt if model routing or response validation fails.
            import logging
            logging.getLogger(__name__).warning("curiosity_summary_unavailable error_type=%s", type(error).__name__)
    cards = [_card(article, summaries) for article in selected]
    return cards + _evergreen_library(store, cards, selected, limit - len(cards))


def _evergreen_library(store, cards, selected, room):
    """Save the strongest fresh cards, then add saved cards whose articles have left the archive."""
    if not store:
        return []
    import logging
    keep = [(card, quality_score(article)) for card, article in zip(cards, selected)
            if not card["seed"] and quality_score(article) >= KEEP_SCORE]
    try:
        if keep:
            store.keep_curiosity_cards(keep)
        saved = store.curiosity_library(MAX_LIBRARY_CARDS) if room > 0 else []
    except Exception as error:
        logging.getLogger(__name__).warning("curiosity_library_unavailable error_type=%s", type(error).__name__)
        return []
    shown = list(cards)
    extra = []
    for card in saved:
        if len(extra) >= min(room, MAX_LIBRARY_CARDS) or _is_duplicate(card, shown):
            continue
        card = {**card, "seed": True, "archived": True}
        shown.append(card)
        extra.append(card)
    return extra


def saved_curiosity_article(store, ident):
    """A saved evergreen card as a brief-ready article (attribution and link preserved)."""
    if not store or not isinstance(ident, str):
        return None
    try:
        card = store.curiosity_saved_card(ident)
    except Exception:
        return None
    if not card or not card.get("url") or not card.get("title"):
        return None
    source = BY_ID.get(card.get("source_id"))
    summary = sanitize_text(card.get("summary") or card.get("description"), 900)
    return {**card, "description": summary, "summary": summary, "curiosity_seed": True, "archived": True,
            "source": source.group if source else "curiosity", "category": "Engineering",
            "published_at": card.get("published_at") or ""}


def resolve_curiosity_cards(store, ids):
    """Resolve only reviewed seeds or currently eligible archive articles, without AI calls."""
    requested = list(dict.fromkeys(ids))
    selected = []
    missing = []
    for ident in requested:
        seed = curiosity_article(ident)
        if seed:
            selected.append(seed)
        else:
            missing.append(ident)
    if missing and store:
        rows = store.pinned_articles(missing)
        by_id = {article["id"]: article for article in rows}
        for ident in missing:
            article = by_id.get(ident)
            if article and is_curiosity_candidate(restore_metadata(article)):
                selected.append(_card(restore_metadata(article), {}))
            elif saved := saved_curiosity_article(store, ident):
                selected.append(saved)
    by_id = {card["id"]: card for card in selected}
    return [by_id[ident] for ident in requested if ident in by_id]


def seed_article_ids():
    return set(SEEDS_BY_ID)
