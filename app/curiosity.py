"""Source-grounded engineering stories for the Curiosity Cards collection."""
from copy import deepcopy
from functools import lru_cache
from math import gcd
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
          kind="engineering", question="", problems=(), breakdown=None):
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
        "question": question,
        "themes": list(themes),
        "problems": list(problems),
        "breakdown": dict(zip(("problem", "approach", "result"), breakdown)) if breakdown else None,
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
    # --- Agentic AI in production (each link checked 2026-11-23) ------------------------------------------
    _seed("cognition-dont-build-multi-agents", "Don’t Build Multi-Agents",
          "https://cognition.ai/blog/dont-build-multi-agents", "Cognition", "Cognition", 2025,
          "The team behind the Devin coding agent argues that splitting work across parallel sub-agents breaks down when they cannot share context, and sets out two context-engineering principles: share full context, and remember that actions carry implicit decisions.",
          ("Multi-agent systems", "Context engineering", "Coding agents"), 12, None, published="2025-06-12",
          authors="Walden Yan", publisher_detail="Cognition blog",
          why="A sharp counterpoint to multi-agent hype from a team running agents on real codebases.",
          question="When do multi-agent architectures fail, and why?", themes=("agents", "ai-engineering")),
    _seed("manus-context-engineering", "Context Engineering for AI Agents: Lessons from Building Manus",
          "https://manus.im/blog/Context-Engineering-for-AI-Agents-Lessons-from-Building-Manus", "Manus", "Manus", 2025,
          "Lessons from building the Manus agent: design around the KV-cache, mask tools instead of removing them, use the file system as context, steer attention through recitation, keep mistakes in context, and avoid getting stuck in few-shot patterns.",
          ("AI agents", "Context engineering", "KV-cache", "Tool calling"), 15, None, published="2025-07-18",
          authors="Yichao ‘Peak’ Ji", publisher_detail="Manus blog",
          why="Concrete, hard-won rules for agents that run hundreds of tool calls without losing the plot.",
          question="How do production agents manage context across long tool-calling loops?", themes=("agents",)),
    _seed("simonw-prompt-injection-design-patterns", "Design Patterns for Securing LLM Agents against Prompt Injections",
          "https://simonwillison.net/2025/Jun/13/prompt-injection-design-patterns/", "Simon Willison’s Weblog",
          "Simon Willison", 2025,
          "Simon Willison walks through a paper by researchers from IBM, Invariant Labs, ETH Zurich, Google and Microsoft that describes design patterns for LLM agents that limit what a prompt injection can make an agent do.",
          ("Prompt injection", "Agent security", "LLMs"), 14, "simon-willison", published="2025-06-13",
          authors="Simon Willison", publisher_detail="Independent analysis",
          why="Practical architecture patterns for one of the hardest unsolved problems in agent security.",
          question="How can AI agents be designed to resist prompt injection?", themes=("agents", "security")),
    _seed("hamel-your-ai-product-needs-evals", "Your AI Product Needs Evals",
          "https://hamel.dev/blog/posts/evals/", "Hamel’s Blog", "Hamel Husain", 2024,
          "Hamel Husain explains how to build domain-specific evaluation systems for LLM products, from unit-test-style assertions to human and model-based review, drawing on years of building language-model tools.",
          ("Evals", "LLMs", "Testing"), 20, "hamel-husain", published="2024-03-29", authors="Hamel Husain",
          publisher_detail="Independent engineering blog",
          why="The most cited practical guide to measuring whether an LLM product actually works.",
          question="How do teams evaluate and debug LLM products?", themes=("agents", "ai-engineering")),
    _seed("anthropic-model-context-protocol", "Introducing the Model Context Protocol",
          "https://www.anthropic.com/news/model-context-protocol", "Anthropic", "Anthropic", 2024,
          "Anthropic introduces the Model Context Protocol (MCP), an open standard for connecting AI assistants to the systems where data lives, such as content repositories, business tools and development environments.",
          ("MCP", "Tool calling", "AI agents"), 6, "anthropic-news", published="2024-11-25", publisher_detail="Anthropic",
          why="The origin of the protocol most agent tooling now builds on.",
          question="What is MCP and why did agents need a common protocol?", themes=("agents",)),
    _seed("anthropic-code-execution-with-mcp", "Code execution with MCP: Building more efficient agents",
          "https://www.anthropic.com/engineering/code-execution-with-mcp", "Anthropic", "Anthropic", 2025,
          "Anthropic’s engineers describe having agents call MCP tools by writing and running code, rather than loading every tool definition and intermediate result into the model’s context, to make connected agents more efficient.",
          ("MCP", "Code execution", "Context engineering"), 12, "anthropic-engineering", published="2025-11-04",
          publisher_detail="Anthropic engineering",
          why="A design pattern for agents connected to hundreds of tools without drowning in context.",
          question="How do agents scale to many tools without exhausting their context window?", themes=("agents",)),
    _seed("anthropic-claude-code-sandboxing", "Beyond permission prompts: making Claude Code more secure and autonomous",
          "https://www.anthropic.com/engineering/claude-code-sandboxing", "Anthropic", "Anthropic", 2025,
          "How Anthropic used sandboxing to give its Claude Code coding agent more autonomy while containing the risks of broad codebase and command access, including prompt injection.",
          ("Sandboxing", "Coding agents", "Agent security"), 10, "anthropic-engineering", published="2025-10-20",
          publisher_detail="Anthropic engineering",
          why="Shows how isolation, not just permission prompts, makes autonomous coding agents safer.",
          question="How do you let a coding agent run commands safely?", themes=("agents", "security")),
    _seed("openai-practical-guide-to-agents", "A practical guide to building agents",
          "https://openai.com/business/guides-and-resources/a-practical-guide-to-building-ai-agents/", "OpenAI", "OpenAI", 2026,
          "OpenAI’s guide for product and engineering teams building their first agents, covering when agents fit, how to choose models and tools, orchestration patterns and guardrails.",
          ("AI agents", "Orchestration", "Guardrails"), 25, "openai-news", published="2026-01-15", publisher_detail="OpenAI guide",
          why="A vendor’s own playbook for single-agent and multi-agent designs, with the trade-offs stated.",
          question="How should teams structure, orchestrate and guard production agents?", themes=("agents",)),
    _seed("slack-long-running-agent-context", "Managing context in long-run agentic applications",
          "https://slack.engineering/managing-context-in-long-run-agentic-applications/", "Engineering at Slack", "Slack", 2026,
          "Slack describes how a team of AI agents investigates security alerts, with a Director orchestrating, specialist Experts gathering evidence and a Critic reviewing findings, and the techniques used to keep them coherent over long investigations.",
          ("Multi-agent systems", "Agent memory", "Security operations"), 14, "engineering-slack", published="2026-04-13",
          authors="Dominic Marks", publisher_detail="Engineering at Slack",
          why="A rare inside look at a production multi-agent system with explicit roles and long-running state.",
          question="How do teams of agents stay coherent over long-running tasks?", themes=("agents", "security")),
    _seed("slack-agentic-e2e-testing", "Agentic Testing: Where Agents Fit in the E2E Testing Stack",
          "https://slack.engineering/agentic-testing-where-agents-fit-in-the-e2e-testing-stack/", "Engineering at Slack", "Slack", 2026,
          "Slack ran more than 200 agent-driven end-to-end test workflows with the Playwright MCP, Playwright CLI and agent-generated tests to see whether goal-based agentic tests should complement or replace deterministic ones.",
          ("Agentic testing", "Playwright", "MCP"), 12, "engineering-slack", published="2026-06-11",
          authors="Sergii Gorbachov", publisher_detail="Engineering at Slack",
          why="Measured results on where agents help in testing and where deterministic tests still win.",
          question="Can AI agents replace end-to-end tests?", themes=("ai-engineering", "agents")),

    # --- AI-native engineering and software factories ------------------------------------------------------
    _seed("stripe-minions-coding-agents", "Minions: Stripe’s one-shot, end-to-end coding agents",
          "https://stripe.dev/blog/minions-stripes-one-shot-end-to-end-coding-agents", "Stripe Dot Dev Blog", "Stripe", 2026,
          "Stripe’s homegrown, fully unattended coding agents start from a Slack message and end in a pull request that passes CI and is ready for human review. Over a thousand merged pull requests a week are written entirely by them.",
          ("Coding agents", "CI/CD", "Developer productivity"), 8, "stripe-engineering", published="2026-02-09",
          authors="Alistair Gray", publisher_detail="Stripe Dot Dev Blog", read_time_basis="publisher",
          why="A working AI software factory at a payments company, with humans reviewing every change.",
          question="How does a company run unattended coding agents at scale?", themes=("ai-engineering", "agents")),
    _seed("spotify-honk-background-coding-agent", "1,500+ PRs Later: Spotify’s Journey with Our Background Coding Agent (Honk, Part 1)",
          "https://engineering.atspotify.com/2025/11/spotifys-background-coding-agent-part-1", "Spotify Engineering", "Spotify", 2025,
          "How Spotify extended its Fleet Management platform, which applies code changes across all of its repositories, with background coding agents, and what more than 1,500 merged AI-generated pull requests taught it about large-scale maintenance.",
          ("Coding agents", "Fleet management", "Code migrations"), 12, "spotify-engineering", published="2025-11-06",
          publisher_detail="Spotify Engineering · part 1 of 4",
          why="Fleet-wide code changes by agents, with the failure modes and guardrails spelled out.",
          question="How do coding agents maintain thousands of repositories?", themes=("ai-engineering", "engineering-practice")),
    _seed("google-ai-in-software-engineering", "AI in software engineering at Google: Progress and the path ahead",
          "https://research.google/blog/ai-in-software-engineering-at-google-progress-and-the-path-ahead/", "Google Research",
          "Google", 2024,
          "Google’s engineers review how AI assistance has spread through its internal developer tools, what it has changed for engineers, and where they expect it to go next.",
          ("AI-assisted coding", "Developer tools", "Code completion"), 12, "google-research", published="2024-06-06",
          authors="Satish Chandra · Maxim Tabachnyk", publisher_detail="Google Research blog",
          why="Measured adoption data from one of the largest internal engineering organizations.",
          question="How is AI changing software engineering inside Google?", themes=("ai-engineering",)),
    _seed("meta-ach-llm-bug-catchers", "Revolutionizing software testing: Introducing LLM-powered bug catchers",
          "https://engineering.fb.com/2025/02/05/security/revolutionizing-software-testing-llm-powered-bug-catchers-meta-ach/",
          "Engineering at Meta", "Meta", 2025,
          "Meta’s Automated Compliance Hardening (ACH) tool uses LLMs to generate realistic faults (mutants) in a chosen area of concern, such as privacy, and then generates tests that catch them.",
          ("Mutation testing", "LLM test generation", "Privacy"), 10, "meta-engineering", published="2025-02-05",
          publisher_detail="Engineering at Meta",
          why="An unusual, mutation-guided use of LLMs to harden code against regressions.",
          question="How can LLMs write tests that catch real bugs?", themes=("ai-engineering", "security")),
    _seed("airbnb-llm-test-migration", "Accelerating large-scale test migration with LLMs",
          "https://medium.com/airbnb-engineering/accelerating-large-scale-test-migration-with-llms-9565c208023b",
          "The Airbnb Tech Blog", "Airbnb", 2025,
          "Airbnb used frontier models and automation to migrate nearly 3,500 React component test files from Enzyme to React Testing Library, work it had estimated at a year and a half of engineering time by hand.",
          ("Code migrations", "LLMs", "Testing"), 7, "airbnb-engineering", published="2025-03-13",
          authors="Charles Covey-Brandt", publisher_detail="The Airbnb Tech Blog · Medium publisher estimate",
          read_time_basis="publisher",
          why="A concrete playbook for LLM-driven migrations across thousands of files.",
          question="How do you migrate thousands of files with an LLM pipeline?", themes=("ai-engineering", "engineering-practice")),
    _seed("shopify-roast-structured-ai-workflows", "Introducing Roast: Structured AI workflows made easy",
          "https://shopify.engineering/introducing-roast", "Shopify Engineering", "Shopify", 2025,
          "Shopify’s Augmented Engineering team found that breaking complex developer tasks such as flaky tests and low coverage into discrete steps made AI agents reliable, and open-sourced Roast to structure those workflows.",
          ("AI workflows", "Developer productivity", "Open source"), 10, "engineering-shopify", published="2025-06-18",
          authors="Obie Fernandez", publisher_detail="Shopify Engineering",
          why="Why structure beats free-form autonomy for agents doing routine engineering work.",
          question="How do you make AI agents reliable for routine engineering tasks?", themes=("ai-engineering", "agents")),

    # --- How massive systems actually work -----------------------------------------------------------------
    _seed("discord-elixir-5m-concurrent", "How Discord Scaled Elixir to 5,000,000 Concurrent Users",
          "https://discord.com/blog/how-discord-scaled-elixir-to-5-000-000-concurrent-users", "Discord Blog", "Discord", 2017,
          "Discord explains how it built its real-time system on Elixir and the Erlang VM, and the work needed to keep it fast as concurrent users grew into the millions.",
          ("Elixir", "Erlang VM", "Real-time systems", "Concurrency"), 10, "engineering-discord", published="2017-07-06",
          authors="Stanislav Vishnevskiy", publisher_detail="Discord Engineering",
          why="A classic on scaling a real-time chat backend on the BEAM.",
          question="How does Discord handle millions of concurrent users?", themes=("distributed-systems", "performance")),
    _seed("figma-multiplayer", "How Figma’s multiplayer technology works",
          "https://www.figma.com/blog/how-figmas-multiplayer-technology-works/", "Figma Blog", "Figma", 2019,
          "Figma’s co-founder explains the homegrown system behind live collaborative editing in Figma, and why the team chose its own approach over operational transformation.",
          ("Real-time collaboration", "CRDTs", "Multiplayer"), 15, "figma-blog", published="2019-10-16",
          authors="Evan Wallace", publisher_detail="Figma Blog",
          why="The design reasoning behind one of the best-known real-time collaboration engines.",
          question="How does real-time collaborative editing work at Figma?", themes=("distributed-systems",)),
    _seed("stripe-docdb-zero-downtime-migrations", "How Stripe’s document databases supported 99.999% uptime with zero-downtime data migrations",
          "https://stripe.com/blog/how-stripes-document-databases-supported-99.999-uptime-with-zero-downtime-data-migrations",
          "Stripe Dot Dev Blog", "Stripe", 2024,
          "How Stripe moves data between database shards without downtime while keeping its document databases at 99.999% uptime for a payments platform that processed $1 trillion in 2023.",
          ("Databases", "Sharding", "Data migrations", "Reliability"), 11, "stripe-engineering", published="2024-06-06",
          authors="Jimmy Morzaria · Suraj Narkhede", publisher_detail="Stripe Dot Dev Blog", read_time_basis="publisher",
          why="Payment-grade reliability while the data underneath is constantly moving.",
          question="How does Stripe keep payments reliable while migrating data?", themes=("databases", "reliability")),
    _seed("pinterest-mysql-sharding", "Sharding Pinterest: How we scaled our MySQL fleet",
          "https://medium.com/pinterest-engineering/sharding-pinterest-how-we-scaled-our-mysql-fleet-3f341e96ca6f",
          "Pinterest Engineering Blog", "Pinterest", 2015,
          "A technical dive into how Pinterest split its data across many MySQL servers, an approach launched in 2012 that still stored its core data years later.",
          ("MySQL", "Sharding", "Databases"), 11, "engineering-pinterest", published="2015-08-17",
          authors="Marty Weiner", publisher_detail="Pinterest Engineering · Medium publisher estimate", read_time_basis="publisher",
          why="A clear, durable sharding design that many teams still copy.",
          question="How do you shard a relational database for a fast-growing product?", themes=("databases", "distributed-systems")),
    _seed("vllm-pagedattention", "vLLM: Easy, Fast, and Cheap LLM Serving with PagedAttention",
          "https://blog.vllm.ai/2023/06/20/vllm.html", "vLLM Blog", "vLLM (UC Berkeley)", 2023,
          "The vLLM team introduces PagedAttention, which manages the attention key-value cache like virtual memory pages so LLM serving wastes far less GPU memory and can batch many more requests.",
          ("LLM serving", "PagedAttention", "GPU", "KV-cache"), 8, None, published="2023-06-20", kind="research",
          authors="Woosuk Kwon and co-authors", publisher_detail="vLLM project blog",
          why="The idea behind much of today’s open-source LLM inference.",
          question="How do AI companies serve millions of LLM requests efficiently?", themes=("ai", "performance")),
    _seed("bytedance-monolith-recommendations", "Monolith: Real Time Recommendation System With Collisionless Embedding Table",
          "https://arxiv.org/abs/2209.07663", "arXiv", "ByteDance", 2022,
          "ByteDance researchers describe Monolith, a recommendation system for time-sensitive feedback such as short-video ranking, with collisionless embedding tables and real-time online training.",
          ("Recommendation systems", "Embeddings", "Online training"), 30, "arxiv-cs-ir", published="2022-09-16",
          authors="Zhuoran Liu and co-authors", publisher_detail="arXiv research paper",
          why="A public look at the kind of real-time recommender behind short-video feeds.",
          question="How do short-video apps personalise feeds in real time?", themes=("ai", "distributed-systems")),
    _seed("slack-ai-multi-cloud", "Slack AI: The Path to Multi-Cloud",
          "https://slack.engineering/slack-ai-the-path-to-multi-cloud/", "Engineering at Slack", "Slack", 2026,
          "How Slack’s LLM serving evolved over three years from a SageMaker start to a multi-cloud, multi-vendor architecture built to survive regional outages and GPU scarcity at enterprise scale.",
          ("LLM serving", "Multi-cloud", "GPU capacity"), 17, "engineering-slack", published="2026-05-28",
          authors="Shaurya Kethireddy", publisher_detail="Engineering at Slack",
          why="An honest timeline of what serving LLMs to enterprises actually required.",
          question="How do companies serve LLM features reliably at enterprise scale?", themes=("ai", "cloud")),
    # --- Real-world incidents and how teams handled them (each page read in full before writing) ---------------
    _seed("gitlab-database-outage-2017", "Postmortem of database outage of January 31",
          "https://about.gitlab.com/blog/postmortem-of-database-outage-of-january-31/", "GitLab Blog", "GitLab", 2017,
          "Data was accidentally removed from GitLab.com’s primary database, and the daily pg_dump backups turned out to be missing because of a version mismatch. GitLab explains its single-primary setup, the recovery from an LVM snapshot taken hours earlier, the changes to roughly 5,000 projects that were lost, and what it changed afterwards.",
          ("Postmortem", "PostgreSQL", "Backups", "Data loss"), 20, "gitlab-blog", published="2017-02-10",
          publisher_detail="GitLab incident postmortem", read_time_basis="publisher",
          why="The canonical lesson that an untested backup is not a backup.",
          question="What happens when every backup fails at once?", themes=("reliability", "databases")),
    _seed("atlassian-outage-2022", "Post-Incident Review on the Atlassian April 2022 outage",
          "https://www.atlassian.com/blog/how-we-build/post-incident-review-april-2022-outage", "Inside Atlassian", "Atlassian", 2022,
          "A cleanup script was given the IDs of entire customer sites instead of one app, and the deletion API accepted them, so 775 Atlassian customers lost access on April 5, 2022, some for up to 14 days. The review covers the communication gap behind it, why restoring individual sites took so long, and what Atlassian changed.",
          ("Postmortem", "Data recovery", "Multi-tenancy", "Incident communication"), 35, "atlassian-engineering",
          published="2022-04-29", publisher_detail="Atlassian post-incident review",
          why="A rare look at an outage measured in days, and at restoring one tenant at a time.",
          question="Why can restoring some customers take two weeks?", themes=("reliability", "cloud")),
    _seed("aws-s3-outage-2017", "Summary of the Amazon S3 Service Disruption in the Northern Virginia (US-EAST-1) Region",
          "https://aws.amazon.com/message/41926/", "Amazon Web Services", "Amazon", 2017,
          "During debugging on February 28, 2017, a command meant to remove a few S3 billing servers was entered with the wrong input and removed far more, including servers for S3’s index and placement subsystems. AWS explains why both needed full restarts, which services depending on S3 failed with it, and why the tool now removes capacity slowly and refuses to go below a subsystem’s minimum.",
          ("Postmortem", "Amazon S3", "Operational safety"), 8, None, published="2017-03-02",
          publisher_detail="AWS post-event summary",
          why="One mistyped input, a region-wide outage, and the tooling limits that followed.",
          question="How did one command take down S3 in us-east-1?", themes=("reliability", "cloud")),
    _seed("aws-us-east-1-2021", "Summary of the AWS Service Event in the Northern Virginia (US-EAST-1) Region",
          "https://aws.amazon.com/message/12721/", "Amazon Web Services", "Amazon", 2021,
          "On December 7, 2021, an automated scaling activity triggered a surge of connections from clients on AWS’s internal network that overwhelmed the devices linking it to the main network. AWS describes how a latent issue stopped clients from backing off, how the congestion hid the monitoring data operators needed, and what it changed.",
          ("Postmortem", "Networking", "Retry storms", "AWS"), 12, None, published="2021-12-10",
          publisher_detail="AWS post-event summary",
          why="A textbook retry storm inside the world’s largest cloud.",
          question="How can an internal network take down a cloud region?", themes=("reliability", "cloud", "distributed-systems")),
    _seed("meta-outage-2021", "More details about the October 4 outage",
          "https://engineering.fb.com/2021/10/05/networking-traffic/outage-details/", "Engineering at Meta", "Meta", 2021,
          "A command meant to check backbone capacity disconnected all of Facebook’s data centers, and a bug in the audit tool failed to stop it. Meta explains why its DNS servers then withdrew their BGP routes, making every app unreachable, and why recovery needed engineers on site.",
          ("Postmortem", "BGP", "DNS", "Networking"), 6, "engineering-meta", published="2021-10-05",
          authors="Santosh Janardhan", publisher_detail="Engineering at Meta",
          why="How a safety mechanism turned a network outage into a total disappearance from the internet.",
          question="Why did Facebook vanish from the internet for six hours?", themes=("reliability", "cloud")),
    _seed("github-october-2018-incident", "October 21 post-incident analysis",
          "https://github.blog/news-insights/company-news/oct21-post-incident-analysis/", "The GitHub Blog", "GitHub", 2018,
          "Forty-three seconds of lost connectivity between GitHub’s East Coast hub and data center led Orchestrator to fail MySQL primaries over to the West Coast, leaving writes split across two sites. GitHub explains the 24 hours and 11 minutes of degraded service that followed and how it reconciled the data.",
          ("Postmortem", "MySQL", "Failover", "Raft"), 14, "github-engineering", published="2018-10-30",
          authors="Jason Warner", publisher_detail="GitHub post-incident analysis", read_time_basis="publisher",
          why="A short network partition, an automated failover, and a day of consistency repair.",
          question="How did a 43-second network blip cause a 24-hour outage?", themes=("reliability", "databases", "distributed-systems")),
    _seed("cloudflare-outage-june-2022", "Cloudflare outage on June 21, 2022",
          "https://blog.cloudflare.com/cloudflare-outage-on-june-21-2022/", "Cloudflare Blog", "Cloudflare", 2022,
          "A network configuration change in Cloudflare’s project to make its 19 busiest data centers more resilient took those same locations offline for about an hour. The post walks through the new mesh routing design, the change that broke it, and why it reached production.",
          ("Postmortem", "BGP", "Networking", "Change management"), 7, "cloudflare-blog", published="2022-06-21",
          authors="Tom Strickx · Jeremy Hartman", publisher_detail="Cloudflare Blog", read_time_basis="publisher",
          why="A resilience project that briefly made things worse, and how the change slipped through.",
          themes=("reliability", "cloud")),
    _seed("cloudflare-control-plane-2023", "Post mortem on the Cloudflare Control Plane and Analytics Outage",
          "https://blog.cloudflare.com/post-mortem-on-cloudflare-control-plane-and-analytics-outage/", "Cloudflare Blog",
          "Cloudflare", 2023,
          "A power failure at a data center operator in Oregon took down part of the three-site cluster behind Cloudflare’s dashboard, APIs and analytics. Cloudflare explains why services that should have survived did not, because of non-obvious dependencies, and what it changed in its high-availability design.",
          ("Postmortem", "High availability", "Disaster recovery", "Data centers"), 17, "cloudflare-blog",
          published="2023-11-04", authors="Matthew Prince", publisher_detail="Cloudflare Blog", read_time_basis="publisher",
          why="Proof that a high-availability design is only as strong as its untested dependencies.",
          question="Why did a three-data-center design still fail?", themes=("reliability", "cloud")),
    _seed("fastly-outage-june-2021", "Summary of June 8 outage",
          "https://www.fastly.com/blog/summary-of-june-8-outage", "Fastly Blog", "Fastly", 2021,
          "A bug shipped weeks earlier was triggered by one customer’s valid configuration change and caused 85% of Fastly’s network to return errors. Fastly gives the minute-by-minute timeline, the 49 minutes to recover most traffic, and how the bug was fixed.",
          ("Postmortem", "CDN", "Configuration"), 5, "fastly-blog", published="2021-06-08",
          authors="Nick Rockwell", publisher_detail="Fastly Blog",
          why="A dormant bug, a perfectly valid config change, and much of the web going down.",
          themes=("reliability", "cloud")),
    _seed("datadog-outage-march-2023", "2023-03-08 Incident: Infrastructure connectivity issue affecting multiple regions",
          "https://www.datadoghq.com/blog/2023-03-08-multiregion-infrastructure-connectivity-issue/", "Datadog Blog",
          "Datadog", 2023,
          "An automatic systemd security update restarted systemd-networkd on many machines, which deleted the routes Cilium uses for container networking, taking down several Datadog regions at once. Datadog explains why no normal test reproduced it and how hundreds of responders brought the platform back.",
          ("Postmortem", "Kubernetes", "systemd", "Cilium"), 10, "datadog-blog", published="2023-05-16",
          authors="Alexis Lê-Quôc", publisher_detail="Datadog incident report", read_time_basis="publisher",
          why="An OS update that looked routine and broke networking across regions.",
          question="How did a security patch take down a monitoring company?", themes=("reliability", "cloud")),
    _seed("slack-incident-2-22-22", "Slack’s Incident on 2-22-22",
          "https://slack.engineering/slacks-incident-on-2-22-22/", "Engineering at Slack", "Slack", 2022,
          "Many users could not connect to Slack after problems in its memcached tier pushed load onto the Vitess databases behind client boot. Slack’s incident commander explains how the cache and database failures fed each other in a cascading failure, and how the team recovered.",
          ("Postmortem", "Caching", "Vitess", "Cascading failures"), 14, "engineering-slack", published="2022-04-26",
          authors="Laura Nolan", publisher_detail="Engineering at Slack", read_time_basis="publisher",
          why="A textbook complex-systems failure where cache and database made each other worse.",
          themes=("reliability", "databases", "distributed-systems")),
    _seed("crowdstrike-falcon-pir-2024", "Preliminary Post Incident Review: Content Configuration Update Impacting the Falcon Sensor and the Windows Operating System",
          "https://www.crowdstrike.com/en-us/blog/falcon-content-update-preliminary-post-incident-report/", "CrowdStrike Blog",
          "CrowdStrike", 2024,
          "A bug in CrowdStrike’s Content Validator let a faulty content update through, which triggered an out-of-bounds memory read and crashed Windows machines running its sensor. The review explains the two kinds of security content updates and commits to staggered, canary-first rollouts.",
          ("Postmortem", "Windows", "Deployment", "Canary releases"), 10, None, published="2024-07-24",
          publisher_detail="CrowdStrike preliminary post-incident review",
          why="The case for staged rollouts, even for ‘just content’.",
          question="How did one content update crash millions of Windows machines?", themes=("reliability", "security")),
    # --- Case studies: how teams solved hard scaling problems -------------------------------------------------
    _seed("notion-sharding-postgres", "Herding elephants: Lessons learned from sharding Postgres at Notion",
          "https://www.notion.com/blog/sharding-postgres-at-notion", "Notion Blog", "Notion", 2021,
          "Notion split its PostgreSQL monolith into 480 logical shards across 32 physical databases. The post explains when to shard, how the layout was chosen, and how the team double-wrote, backfilled and verified data before a five-minute switchover.",
          ("PostgreSQL", "Sharding", "Data migrations"), 15, None, published="2021-10-06",
          authors="Garrett Fidalgo", publisher_detail="Notion engineering blog",
          why="A practical, numbers-first walkthrough of a database sharding migration.",
          question="How do you shard a live database with five minutes of downtime?", themes=("databases",)),
    _seed("uber-postgres-to-mysql", "Why Uber Engineering Switched from Postgres to MySQL",
          "https://www.uber.com/blog/postgres-to-mysql-migration/", "Uber Engineering", "Uber", 2016,
          "Uber explains the Postgres limitations it hit at scale, including write amplification, replication and upgrade pain, by comparing how Postgres and MySQL’s InnoDB lay out data on disk, and why it built its Schemaless sharding layer on MySQL instead.",
          ("PostgreSQL", "MySQL", "Replication", "Storage engines"), 20, "uber-engineering", published="2016-07-26",
          authors="Evan Klitzke", publisher_detail="Uber Engineering",
          why="A famous, much-debated database decision explained through on-disk internals.",
          themes=("databases",)),
    _seed("github-partitioning-mysql", "Partitioning GitHub’s relational databases to handle scale",
          "https://github.blog/engineering/infrastructure/partitioning-githubs-relational-databases-scale/", "The GitHub Blog",
          "GitHub", 2021,
          "GitHub broke up mysql1, the single cluster behind most of its core features, by grouping tables into schema domains, enforcing their boundaries with SQL linters, and moving them to new clusters. The result was a 50% load reduction and fewer database incidents.",
          ("MySQL", "Partitioning", "Ruby on Rails"), 10, "github-engineering", published="2021-09-27",
          authors="Thomas Maurer", publisher_detail="GitHub engineering blog", read_time_basis="publisher",
          why="How to split a monolithic database without rewriting the application first.",
          themes=("databases", "engineering-practice")),
    _seed("slack-vitess-migration", "Scaling Datastores at Slack with Vitess",
          "https://slack.engineering/scaling-datastores-at-slack-with-vitess/", "Engineering at Slack", "Slack", 2020,
          "How Slack moved from active-active MySQL clusters to Vitess, which by late 2020 served 99% of its query load at 2.3 million queries per second at peak, and the design choices and migration problems along the way.",
          ("Vitess", "MySQL", "Sharding", "Data migrations"), 16, "engineering-slack", published="2020-12-01",
          authors="Arka Ganguli · Guido Iaquinti · Maggie Zhou · Rafael Chacón", publisher_detail="Engineering at Slack",
          read_time_basis="publisher", why="A multi-year datastore migration under a real-time messaging product.",
          themes=("databases", "distributed-systems")),
    _seed("segment-goodbye-microservices", "Goodbye Microservices: From 100s of problem children to 1 superstar",
          "https://www.twilio.com/en-us/blog/developers/best-practices/goodbye-microservices", "Twilio Blog", "Twilio Segment",
          2018,
          "Segment had grown to more than 140 microservices and queues, one per destination. It explains why that became unmanageable and how it consolidated them into one service in a monorepo, with Centrifuge replacing the queues and Traffic Recorder making tests fast and reliable.",
          ("Microservices", "Monolith", "Monorepo", "Testing"), 12, None, published="2018-07-10",
          authors="Alexandra Noonan", publisher_detail="Twilio Segment engineering", read_time_basis="publisher",
          why="An honest account of microservices costs outweighing their benefits, and the trade-offs of going back.",
          question="When should you merge microservices back into one?", themes=("engineering-practice", "distributed-systems")),
    _seed("dropbox-magic-pocket", "Inside the Magic Pocket",
          "https://dropbox.tech/infrastructure/inside-the-magic-pocket", "Dropbox Tech", "Dropbox", 2016,
          "An architectural overview of Magic Pocket, the in-house multi-exabyte system Dropbox built to store file content: how files are split into blocks, replicated for durability and spread across regions, and the design goals behind it.",
          ("Storage", "Durability", "Replication"), 12, "engineering-dropbox", published="2016-05-06",
          authors="James Cowling", publisher_detail="Dropbox Tech Blog",
          why="What it takes to leave the cloud and run exabyte-scale storage yourself.",
          themes=("distributed-systems", "cloud")),

    # --- Round 10: recent outages, security incidents, leaving the cloud, migrations and AI products -----------
    _seed("aws-dynamodb-dns-2025", "Amazon DynamoDB service disruption in US-EAST-1, October 2025",
          "https://aws.amazon.com/message/101925/", "Amazon Web Services", "Amazon", 2025,
          "On October 19 and 20, 2025, a latent race condition between two DNS Enactors left DynamoDB’s regional endpoint with an empty DNS record. AWS explains how that one record knocked on to EC2 instance launches and Network Load Balancer health checks.",
          ("Postmortem", "DynamoDB", "DNS", "Race conditions"), 15, None,
          publisher_detail="AWS post-event summary",
          why="A race condition in automation, an empty DNS record, and a whole region feeling it.",
          question="How did one empty DNS record ripple across us-east-1?", themes=("reliability", "cloud")),
    _seed("cloudflare-outage-november-2025", "Cloudflare outage on November 18, 2025",
          "https://blog.cloudflare.com/18-november-2025-outage/", "Cloudflare Blog", "Cloudflare", 2025,
          "A database permissions change doubled the size of the Bot Management feature file, pushing it past the size limit Cloudflare’s proxy allowed. Cloudflare first suspected a DDoS attack, then rolled back to an earlier version of the file; core traffic was flowing normally by 14:30 UTC.",
          ("Postmortem", "Configuration", "Bot Management", "Proxy"), 12, "cloudflare-blog", published="2025-11-18",
          authors="Matthew Prince", publisher_detail="Cloudflare Blog", read_time_basis="publisher",
          why="A generated config file grew past a hard limit, and the symptoms looked like an attack.",
          question="How did a permissions change take down Cloudflare’s proxy?", themes=("reliability", "cloud")),
    _seed("google-cloud-service-control-2025", "Multiple GCP products are experiencing Service issues",
          "https://status.cloud.google.com/incidents/ow5i3PPK96RduMcb1SsW", "Google Cloud Service Health", "Google", 2025,
          "A Service Control feature added on May 29 had no error handling and was not behind a feature flag. When a policy with blank fields was written to Spanner, the new code hit a null pointer and crashed the binary. The incident report covers the outage from 10:51 to 18:18 US/Pacific.",
          ("Postmortem", "Feature flags", "Spanner", "Error handling"), 12, None,
          publisher_detail="Google Cloud incident report",
          why="Unflagged code, a globally replicated policy and a null pointer.",
          question="How did one blank policy field crash Google Cloud’s API layer?", themes=("reliability", "cloud")),
    _seed("openai-december-2024-incident", "API, ChatGPT & Sora Facing Issues",
          "https://status.openai.com/incidents/ctrsv3lwd797", "OpenAI Status", "OpenAI", 2024,
          "A new telemetry service rolled out to OpenAI’s clusters put heavy load on the Kubernetes API in its largest clusters, overwhelming their control planes and breaking DNS-based service discovery. DNS caching hid the failure long enough for the rollout to continue; ChatGPT fully recovered at 7:01 PM PST and the API at 7:38 PM.",
          ("Postmortem", "Kubernetes", "DNS", "Control planes"), 8, None,
          publisher_detail="OpenAI incident report",
          why="A monitoring change that took down what it was meant to watch.",
          question="How did a telemetry service take down ChatGPT?", themes=("reliability", "cloud")),
    _seed("github-ddos-2018", "February 28th DDoS Incident Report",
          "https://github.blog/news-insights/company-news/ddos-incident-report/", "The GitHub Blog", "GitHub", 2018,
          "On February 28, 2018, GitHub was hit by a memcached amplification attack that peaked at 1.35 Tbps. GitHub.com was unavailable from 17:21 to 17:26 UTC; the team moved traffic to Akamai by withdrawing its BGP announcements through ChatOps.",
          ("DDoS", "Memcached", "BGP"), 3, "github-engineering", published="2018-03-01",
          authors="Sam Kottler", publisher_detail="GitHub incident report", read_time_basis="publisher",
          why="Five minutes of downtime during a 1.35 Tbps attack, and the playbook that kept it short.",
          question="How did GitHub absorb a 1.35 Tbps attack?", themes=("security", "reliability")),
    _seed("cloudflare-leap-second-2017", "How and why the leap second affected Cloudflare DNS",
          "https://blog.cloudflare.com/how-and-why-the-leap-second-affected-cloudflare-dns/", "Cloudflare Blog", "Cloudflare",
          2017,
          "At midnight UTC on New Year’s Day 2017, the leap second produced a negative value in Cloudflare’s Go DNS server, RRDNS, which caused a panic. Only CNAME lookups were affected, about 0.2% of DNS queries at peak; most machines were patched within 90 minutes.",
          ("Postmortem", "Go", "DNS", "Time"), 5, "cloudflare-blog", published="2017-01-01",
          authors="John Graham-Cumming", publisher_detail="Cloudflare Blog", read_time_basis="publisher",
          why="Why code should never assume time only moves forward.",
          question="How did one extra second break DNS?", themes=("reliability", "cloud")),
    _seed("letsencrypt-caa-rechecking-bug", "2020.02.29 CAA Rechecking Bug",
          "https://community.letsencrypt.org/t/2020-02-29-caa-rechecking-bug/114591", "Let’s Encrypt Community",
          "Let’s Encrypt", 2020,
          "A bug in Boulder, Let’s Encrypt’s CA software, rechecked CAA records for one domain N times instead of checking each of a certificate’s N domains once. The team found it on February 29, 2020, halted issuance two minutes later, and deployed a fix by 05:22 UTC; the bug had been live since July 2019.",
          ("Incident report", "PKI", "Go", "Compliance"), 6, None,
          publisher_detail="Let’s Encrypt incident report",
          why="A small loop bug in software the whole web’s certificates depend on.",
          question="How did a loop bug force a certificate authority to stop issuing?",
          themes=("security", "reliability")),
    _seed("knight-capital-sec-2013", "SEC Charges Knight Capital With Violations of Market Access Rule",
          "https://www.sec.gov/newsroom/press-releases/2013-222", "U.S. Securities and Exchange Commission",
          "Knight Capital", 2013,
          "In the first 45 minutes of trading on August 1, 2012, Knight Capital’s router sent more than 4 million orders while trying to fill 212 customer orders, after a deployment left old, unused code active. The SEC’s findings describe the deployment, the missing safeguards and a loss of more than $460 million.",
          ("Deployment", "Trading systems", "Dead code"), 6, None, published="2013-10-16",
          publisher_detail="SEC press release and findings",
          why="The most expensive deployment mistake on record, told by the regulator.",
          question="How did a bad deploy lose $460 million in 45 minutes?", themes=("reliability", "engineering-practice")),
    _seed("xz-utils-backdoor-2024", "backdoor in upstream xz/liblzma leading to ssh server compromise",
          "https://www.openwall.com/lists/oss-security/2024/03/29/4", "oss-security mailing list", "xz Utils", 2024,
          "Andres Freund’s original report of the backdoor in xz 5.6.0 and 5.6.1. He noticed ssh logins using unusual amounts of CPU and valgrind errors, and traced them to an obfuscated build step injected into the release tarballs.",
          ("Supply chain", "Open source", "SSH", "Linux"), 15, None, published="2024-03-29",
          authors="Andres Freund", publisher_detail="oss-security disclosure",
          why="A supply-chain attack caught because one engineer chased odd CPU use during ssh logins.",
          question="How was the xz backdoor found?", themes=("security",)),
    _seed("circleci-security-incident-2023", "CircleCI Jan 4, 2023 security incident report",
          "https://circleci.com/blog/jan-4-2023-incident-report/", "CircleCI Blog", "CircleCI", 2023,
          "Malware on an engineer’s laptop stole a valid, 2FA-backed SSO session, which an attacker used to reach production systems and exfiltrate data. The data was encrypted at rest, but the attacker pulled the keys from a running process. CircleCI explains the timeline and why it asked customers to rotate every secret.",
          ("Security incident", "Session hijacking", "Secrets management"), 13, "circleci-blog", published="2023-01-12",
          authors="Rob Zuber", publisher_detail="CircleCI incident report", read_time_basis="publisher",
          why="2FA did not help once the session cookie itself was stolen.",
          question="How did one stolen session cookie expose customer secrets?", themes=("security",)),
    _seed("cloudflare-thanksgiving-2023", "Thanksgiving 2023 security incident",
          "https://blog.cloudflare.com/thanksgiving-2023-security-incident/", "Cloudflare Blog", "Cloudflare", 2024,
          "An attacker used one access token and three service account credentials that Cloudflare had failed to rotate after the October 2023 Okta compromise to reach its Atlassian wiki, bug tracker and source code. Cloudflare then rotated more than 5,000 production credentials and reimaged every machine in its network.",
          ("Security incident", "Credential rotation", "Atlassian"), 14, "cloudflare-blog", published="2024-02-01",
          authors="Matthew Prince · John Graham-Cumming · Grant Bourzikas", publisher_detail="Cloudflare Blog",
          read_time_basis="publisher",
          why="Credentials that were not rotated after someone else’s breach.",
          question="How did a breach at Okta reach Cloudflare’s source code?", themes=("security",)),
    _seed("okta-support-system-rca-2023", "Unauthorized Access to Okta's Support Case Management System: Root Cause and Remediation",
          "https://sec.okta.com/articles/2023/11/unauthorized-access-oktas-support-case-management-system-root-cause/",
          "Okta Security", "Okta", 2023,
          "From September 28 to October 17, 2023, an attacker read support files for 134 Okta customers; some were HAR files with session tokens, which were used to hijack sessions of 5 customers. The service account behind it had its password saved in an employee’s personal Google profile on a work laptop.",
          ("Security incident", "Session tokens", "Identity"), 10, None, published="2023-11-03",
          authors="David Bradbury", publisher_detail="Okta root cause analysis",
          why="A saved password in a personal browser profile, and session tokens left in debug files.",
          question="How did a browser HAR file become an attack path?", themes=("security",)),
    _seed("cloudflare-log4j-cve-2021-44228", "Inside the Log4j2 vulnerability (CVE-2021-44228)",
          "https://blog.cloudflare.com/inside-the-log4j2-vulnerability-cve-2021-44228/", "Cloudflare Blog", "Cloudflare",
          2021,
          "Written the day after Log4Shell was disclosed: how a JNDI lookup feature added to Log4j in 2013 let attackers execute code on servers just by getting a string logged, which versions were affected, and how Cloudflare protected its own systems and customers.",
          ("Log4j", "Java", "Vulnerabilities", "WAF"), 6, "cloudflare-blog", published="2021-12-10",
          authors="John Graham-Cumming", publisher_detail="Cloudflare Blog", read_time_basis="publisher",
          why="An eight-year-old convenience feature that became one of the worst vulnerabilities on the internet.",
          question="How could logging one string run code on a server?", themes=("security",)),
    _seed("37signals-left-the-cloud", "We have left the cloud",
          "https://world.hey.com/dhh/we-have-left-the-cloud-251760fb", "HEY World", "37signals", 2023,
          "After six months of work, 37signals moved HEY, Basecamp Classic and other apps from AWS onto its own Dell servers, running KVM, Docker and Kamal. About $500,000 of hardware added 4,000 vCPUs, and David Heinemeier Hansson estimates savings of at least $1.5 million a year.",
          ("Cloud exit", "KVM", "Docker", "Kamal"), 5, None, published="2023-06-23",
          authors="David Heinemeier Hansson", publisher_detail="37signals co-founder’s blog",
          why="The numbers behind a well-known cloud exit, and why containers made it easier.",
          question="Is owning servers cheaper than renting the cloud?", themes=("cloud", "engineering-practice")),
    _seed("stack-overflow-architecture-2016", "Stack Overflow: The Architecture - 2016 Edition",
          "https://nickcraver.com/blog/2016/02/17/stack-overflow-the-architecture-2016-edition/", "Nick Craver",
          "Stack Overflow", 2016,
          "How Stack Overflow served 209 million HTTP requests a day from its own hardware: 11 IIS web servers, 4 SQL Servers, 2 Redis servers and Elasticsearch, with enough headroom that it could run on one web server. Nick Craver explains the choices behind running so lean.",
          ("Architecture", "SQL Server", "Redis", ".NET"), 20, None, published="2016-02-17",
          authors="Nick Craver", publisher_detail="Stack Overflow architect’s blog",
          why="One of the busiest sites on the web on a handful of servers, and why that worked.",
          question="How did Stack Overflow run on so few servers?", themes=("performance", "databases")),
    _seed("discord-indexing-trillions", "How Discord Indexes Trillions of Messages",
          "https://discord.com/blog/how-discord-indexes-trillions-of-messages", "Discord Blog", "Discord", 2025,
          "Discord’s search system began dropping messages when its Redis indexing queue backed up during Elasticsearch failures. The team moved the queue to PubSub, batched writes per destination cluster, and ran many smaller Elasticsearch clusters in ‘cells’ on Kubernetes.",
          ("Elasticsearch", "Kubernetes", "PubSub", "Search"), 15, "engineering-discord", published="2025-04-24",
          authors="Vicki Niu", publisher_detail="Discord engineering blog",
          why="What breaks when a search index grows from billions to trillions of documents.",
          question="How do you search trillions of chat messages?", themes=("databases", "distributed-systems")),
    _seed("github-rails-upgrade-2018", "Upgrading GitHub from Rails 3.2 to 5.2",
          "https://github.blog/engineering/infrastructure/upgrading-github-from-rails-3-2-to-5-2/", "The GitHub Blog", "GitHub",
          2018,
          "GitHub’s main application moved from Rails 3.2 to 5.2 in a project that took a year and a half. Instead of a long-running branch, the team made the app dual boot with two Gemfile locks, so changes for the next version shipped to production continuously.",
          ("Ruby on Rails", "Upgrades", "Monolith"), 8, "github-engineering",
          authors="Eileen M. Uchitelle", publisher_detail="GitHub engineering blog",
          why="How to upgrade a framework under a huge monolith without freezing development.",
          question="How do you upgrade Rails under one of the largest Rails apps?", themes=("engineering-practice",)),
    _seed("figma-webassembly-load-time", "WebAssembly cut Figma's load time by 3x",
          "https://www.figma.com/blog/webassembly-cut-figmas-load-time-by-3x/", "Figma Blog", "Figma", 2017,
          "Figma’s editor is written in C++ and had been compiled to asm.js. Switching to WebAssembly, released only months earlier, cut load time by three times, because WebAssembly parses about 20 times faster and browsers can cache its compiled code.",
          ("WebAssembly", "C++", "Browsers"), 8, "figma-blog", published="2017-06-08",
          authors="Evan Wallace", publisher_detail="Figma co-founder",
          why="An early real-world WebAssembly result from a large C++ codebase.",
          question="How did WebAssembly make Figma load three times faster?", themes=("performance",)),
    _seed("canva-counting-billions", "Scaling to Count Billions",
          "https://www.canva.dev/blog/engineering/scaling-to-count-billions/", "Canva Engineering Blog", "Canva", 2024,
          "Canva pays creators based on billions of content uses each month. The counting service started on MySQL with worker services and moved to an OLAP database with an ELT pipeline, which now aggregates billions of usage events in a few minutes.",
          ("OLAP", "MySQL", "ELT", "Data pipelines"), 12, "canva-engineering", published="2024-04-12",
          authors="Sangzhuoyang Yu", publisher_detail="Canva engineering blog",
          why="When counting things correctly at scale outgrows a transactional database.",
          question="How do you count billions of events accurately enough to pay people?", themes=("databases",)),
    _seed("khan-academy-goliath", "Go + Services = One Goliath Project",
          "https://blog.khanacademy.org/go-services-one-goliath-project/", "Khan Academy Blog", "Khan Academy", 2019,
          "With Python 2 reaching end of life, Khan Academy chose to rebuild its Python 2 monolith as services in Go rather than port it to Python 3. Kevin Dangoor explains the options they weighed, including Kotlin, and why Go’s performance and long-term support won.",
          ("Go", "Python", "Monolith", "Services"), 8, "khan-academy-engineering", published="2019-12-20",
          authors="Kevin Dangoor", publisher_detail="Khan Academy engineering",
          why="A rewrite decision explained up front, with the alternatives that lost.",
          question="Why rewrite in Go instead of porting to Python 3?", themes=("engineering-practice",)),
    _seed("stripe-sorbet", "Sorbet: Stripe’s type checker for Ruby",
          "https://stripe.dev/blog/sorbet-stripes-type-checker-for-ruby", "Stripe Dot Dev Blog", "Stripe", 2022,
          "By 2017 hundreds of Stripe engineers had written millions of lines of Ruby, and changes were getting risky. Stripe built and open sourced Sorbet, a fast type checker for Ruby; it now covers more than 15 million lines in 150,000 files.",
          ("Ruby", "Type checking", "Developer productivity"), 11, "stripe-dev-blog", published="2022-03-28",
          authors="Jake Zimmerman", publisher_detail="Stripe developer blog", read_time_basis="publisher",
          why="Adding types to a huge dynamic codebase without stopping the company.",
          question="How do you add static types to millions of lines of Ruby?", themes=("engineering-practice",)),
    _seed("uber-querygpt", "QueryGPT – Natural Language to SQL Using Generative AI",
          "https://www.uber.com/blog/query-gpt/", "Uber Blog", "Uber", 2024,
          "Uber runs about 1.2 million interactive queries a month. QueryGPT turns a question into SQL using workspaces of curated tables and examples plus an intent agent that routes each question, cutting the time to write a query from about 10 minutes to about 3.",
          ("LLMs", "SQL", "Agents", "RAG"), 12, "uber-engineering", published="2024-09-19",
          authors="Jeffrey Johnson · Callie Busch · Abhi Khune", publisher_detail="Uber engineering blog",
          why="The design choices that make text-to-SQL usable on a huge data warehouse.",
          question="How do you get an LLM to write correct SQL for a huge data warehouse?", themes=("ai", "agents")),
    _seed("linkedin-genai-product-musings", "Musings on building a Generative AI product",
          "https://www.linkedin.com/blog/engineering/generative-ai/musings-on-building-a-generative-ai-product",
          "LinkedIn Engineering Blog", "LinkedIn", 2024,
          "LinkedIn’s team on building an AI assistant with routing, retrieval and generation steps across dozens of agents. Reaching 80% quality was fast; the last 20% took most of the work, and evaluating answers was harder than expected.",
          ("LLMs", "RAG", "Agents", "Evaluation"), 15, None, published="2024-04-25",
          authors="Juan Pablo Bottaro · Karthik R", publisher_detail="LinkedIn engineering blog",
          why="An honest list of what worked and where a real generative AI product struggled.",
          question="Why is the last 20% of an LLM product so hard?", themes=("ai", "agents")),
    _seed("github-copilot-llms", "Inside GitHub: Working with the LLMs behind GitHub Copilot",
          "https://github.blog/ai-and-ml/github-copilot/inside-github-working-with-the-llms-behind-github-copilot/",
          "The GitHub Blog", "GitHub", 2023,
          "How GitHub engineers went from first trying GPT-3 in 2020 to shipping Copilot on OpenAI’s Codex model, and how prompt crafting and fine-tuning raise completion, the share of suggestions developers keep.",
          ("Copilot", "LLMs", "Prompt engineering"), 10, "github-engineering", published="2023-05-17",
          authors="Sara Verdi", publisher_detail="GitHub blog", read_time_basis="publisher",
          why="An early look at turning a document-completion model into a coding tool.",
          question="How did GitHub turn an LLM into Copilot?", themes=("ai-engineering", "ai")),
    _seed("shopify-bfcm-scale-testing", "Performance Testing At Scale—for BFCM and Beyond",
          "https://shopify.engineering/scale-performance-testing", "Shopify Engineering", "Shopify", 2023,
          "How Shopify prepares for Black Friday Cyber Monday: scaling the platform up, running full-scale load tests that stack browsing, checkout and flash-sale flows to target request rates, then analysing the results and repeating through the year.",
          ("Load testing", "Capacity planning", "Ecommerce"), 10, "engineering-shopify", published="2023-01-27",
          authors="Jordan Neufeld", publisher_detail="Shopify engineering blog",
          why="Rehearsing the busiest weekend of the year on production.",
          question="How does Shopify make sure Black Friday doesn’t take it down?", themes=("performance", "reliability")),
    _seed("hotstar-scaling-for-50m", "Scaling the Hotstar Platform for 50M",
          "https://blog.hotstar.com/scaling-the-hotstar-platform-for-50m-a7f96a019add", "JioHotstar Tech Blog", "Hotstar",
          2019,
          "After serving 25 million concurrent cricket viewers, Hotstar prepared for 50 million. Autoscaling had not worked for it in 2018, so it stepped capacity up and down static ‘ladders’, tuned layers doing generic processing it did not need, and ran harsh traffic simulations that exposed a cascading failure.",
          ("Load testing", "Capacity planning", "Live streaming", "CDN"), 6, "hotstar-tech", published="2019-10-01",
          authors="Akash Saxena", publisher_detail="Hotstar engineering blog", read_time_basis="publisher",
          why="Why autoscaling was not the answer for the biggest live-streaming peaks.",
          question="How do you get ready for 50 million people watching one match?",
          themes=("performance", "cloud", "reliability")),
    _seed("spotify-tech-migrations", "Tech Migrations, the Spotify Way",
          "https://engineering.atspotify.com/2020/6/tech-migrations-the-spotify-way", "Spotify Engineering", "Spotify", 2020,
          "Migrations at Spotify started fast and stalled in a long tail of systems on old versions. The platform team’s answer had three parts: one prioritised, company-wide migrations map, treating migrations as products, and automating as much of the work as possible, with progress shown in Backstage.",
          ("Migrations", "Backstage", "Platform engineering"), 8, "spotify-engineering",
          authors="Saunak “Jai” Chakrabarti · Jenni Lee", publisher_detail="Spotify engineering blog",
          why="The organisational side of migrations, which is usually what makes them drag on.",
          question="Why do migrations stall in a long tail, and how do you finish them?",
          themes=("engineering-practice",)),
    _seed("airbnb-great-migration-soa", "The Great Migration: from Monolith to Service-Oriented",
          "https://www.infoq.com/presentations/airbnb-soa-migration/", "InfoQ", "Airbnb", 2018,
          "Jessica Tai explains why Airbnb moved off Monorail, its Ruby on Rails monolith, to services: the design tenets it set, its layers of data, derived data, middle-tier and presentation services, and the lessons and practices from the migration.",
          ("Microservices", "Ruby on Rails", "Monolith", "SOA"), 45, None, published="2018-12-05",
          authors="Jessica Tai", publisher_detail="QCon San Francisco 2018 talk",
          why="A layered service design and the lessons from moving a large Rails app onto it.",
          question="How did Airbnb break up its Rails monolith?", themes=("distributed-systems", "engineering-practice")),
    _seed("honeycomb-hard-stuff-llms", "All the Hard Stuff Nobody Talks About when Building Products with LLMs",
          "https://www.honeycomb.io/blog/hard-stuff-nobody-talks-about-llm", "Honeycomb Blog", "Honeycomb", 2024,
          "Phillip Carter on shipping Query Assistant, which turns natural language into Honeycomb queries: schemas with over 5,000 fields that will not fit in a context window, latency of two to 15+ seconds that rules out chaining calls, and queries that must be both correct and helpful.",
          ("LLMs", "Prompt engineering", "Context windows"), 15, "honeycomb-blog",
          authors="Phillip Carter", publisher_detail="Honeycomb blog",
          why="The practical problems a demo never shows, from a team that shipped an LLM feature.",
          question="What makes an LLM feature hard to ship?", themes=("ai",)),
    _seed("google-cloud-europe-west2-power-2026", "Multiple services were experiencing issues in the europe-west2 region",
          "https://status.cloud.google.com/incidents/Xs2XTHzAVC9YnafnPyzj", "Google Cloud Service Health", "Google", 2026,
          "A utility cable fault cut power to the data center behind europe-west2-b while its second feed was open for repairs. The generator controller sensed live voltage upstream of that open breaker, decided utility power was healthy and never started the generators, so the zone went dark when its UPS batteries ran out.",
          ("Postmortem", "Data centers", "Power", "Failover"), 12, None,
          publisher_detail="Google Cloud incident report",
          why="Redundant power that failed because a sensor was wired on the wrong side of a breaker.",
          question="How did a data center with backup generators lose power?", themes=("reliability", "cloud")),
    _seed("github-availability-september-2026", "GitHub availability report: September 2026",
          "https://github.blog/news-insights/company-news/github-availability-report-september-2026/", "The GitHub Blog",
          "GitHub", 2026,
          "GitHub’s report on two incidents and its reliability work: moving services and MySQL databases to Azure, taking load off its oldest shared database, overload controls that shed lower-priority requests, and a planned failover whose automated emergency process disconnected database copies.",
          ("Availability report", "MySQL", "Azure", "Load shedding"), 7, "github-availability", published="2026-10-14",
          authors="Jakub Oleksy", publisher_detail="GitHub availability report", read_time_basis="publisher",
          why="An unusually open progress report on a large migration, including the targets that were missed.",
          question="What does GitHub’s move to Azure look like from the inside?",
          themes=("reliability", "databases", "cloud")),
    # --- Round 11: engineering at India scale, and making web and mobile apps fast -------------------------
    _seed("zerodha-scaling-common-sense", "Scaling with common sense",
          "https://zerodha.tech/blog/scaling-with-common-sense/", "Zerodha Tech Blog", "Zerodha", 2020,
          "Zerodha’s CTO argues that scaling is a set of practices unique to each organisation, not a recipe. He explains why a well-partitioned Postgres node can hold hundreds of billions of records, how Kite serves every screen from a hot Redis cache filled by separate services, and why HTTP caching with E-Tags still pays off.",
          ("Postgres", "Redis", "Caching", "Architecture"), 15, "zerodha-tech", published="2020-06-14",
          authors="Kailash Nadh", publisher_detail="Zerodha CTO",
          why="A stockbroker serving millions with plain Postgres and Redis, and a strong case for boring technology.",
          question="Do you really need a distributed database?", themes=("databases", "performance")),
    _seed("phonepe-technology-journey", "Chronicling our Technology Journey",
          "https://tech.phonepe.com/engineeringphonepe-chronicling-our-technology-journey/", "PhonePe Tech Blog", "PhonePe",
          2019,
          "Three years in, with 150 million users and 10 million transactions a day, Rahul Chari lays out the rules its payments platform was built on: asynchronous flows by default, shared-nothing storage, every database sharded from day one, no scatter-gather queries in the user path and no service caching another service’s data.",
          ("Payments", "UPI", "Sharding", "MySQL"), 10, "phonepe-engineering", published="2019-05-03",
          authors="Rahul Chari", publisher_detail="PhonePe engineering",
          why="Design rules for scale, written down early by a fast-growing payments company.",
          question="What rules let a payments app grow to 10 million transactions a day?",
          themes=("distributed-systems", "databases")),
    _seed("flipkart-tidb-active-passive", "Deploying Active-Passive topology in TiDB",
          "https://blog.flipkart.tech/deploying-active-passive-topology-in-tidb-cd5b8e9a8fc9", "Flipkart Tech Blog", "Flipkart",
          2023,
          "Flipkart needed databases that stay available across regions and recover quickly from a disaster. It chose TiDB, a MySQL-compatible NewSQL database, and runs an active cluster in one data center replicating asynchronously to a passive one through TiCDC. The post explains the setup and its replication guarantees.",
          ("TiDB", "MySQL", "Disaster recovery", "Replication"), 10, "flipkart-tech", published="2023-02-14",
          authors="Lalit Kant Roul", publisher_detail="Flipkart engineering blog",
          why="Multi-region disaster recovery for a MySQL-compatible database, with the trade-offs spelled out.",
          question="How does Flipkart keep databases recoverable across regions?", themes=("databases", "reliability")),
    _seed("swiggy-serviceability-platform", "Designing the Serviceability Platform at Swiggy for High Scale — Part 1",
          "https://medium.com/swiggy-bytes/designing-the-serviceability-platform-at-swiggy-for-high-scale-part-1-751a631f0379",
          "Swiggy Bytes", "Swiggy", 2021,
          "Every listing, search and checkout at Swiggy first asks whether a restaurant or store can deliver to you. At 100,000 app visits a minute that is about 200 million evaluations a minute, with a p99 under 200ms. Swiggy explains its GeoHash index for point-in-polygon search, in-memory caches and fault tolerance.",
          ("Geospatial", "Caching", "Latency", "Food delivery"), 10, "swiggy-bytes", published="2021-06-28",
          authors="Somsubhra Bairi", publisher_detail="Swiggy engineering blog", read_time_basis="publisher",
          why="If this one service fails, Swiggy cannot take orders, so it has to be both fast and resilient.",
          question="How does Swiggy decide in milliseconds who can deliver to you?",
          themes=("distributed-systems", "performance")),
    _seed("dream11-ipl-2023-concurrency", "IPL Fever: How Dream11 serves 10.56 MILLION+ users during the TATA IPL 2023",
          "https://tech.dream11.in/blog/ipl-fever-how-dream11-serves-10-56-million-users-during-the-tata-ipl-2023",
          "Dream11 Engineering", "Dream11", 2023,
          "Dream11 reached 10.56 million concurrent users in the opening match of IPL 2023, up from 7 million the year before, and handled over 308 million requests a minute. It prepared with an operational maturity assessment, failure-mode fire drills and runbooks, automated scaling and incident response, and load tests of every critical service.",
          ("Load testing", "Autoscaling", "Incident response", "Fantasy sports"), 6, None, published="2023-05-02",
          publisher_detail="Dream11 engineering blog",
          why="How a sports app gets ready for the minutes when the whole country opens it at once.",
          question="How do you prepare for 10 million people opening your app at the toss?",
          themes=("reliability", "performance")),
    _seed("meesho-rollout-service", "Scaling Deployments at Meesho: How We Built a Custom Rollout Service to Replace Our Existing System",
          "https://www.meesho.io/blog/scaling-deployments-at-meesho-how-we-built-a-custom-rollout-service-to-replace-our-existing-system",
          "Meesho Tech Blog", "Meesho", 2025,
          "Even with canary deployments, failures slipped through at Meesho, rollbacks waited behind a sequential pipeline and the deployment tool choked under load. Because production traffic depended on that tool, Meesho built Rollout Service, an in-house deployment manager, and explains why it could not simply rip out the old tool.",
          ("Deployment", "Canary releases", "Rollbacks", "Platform engineering"), 5, None, published="2025-07-30",
          authors="Naveen Vellingiri · Vignesh Ganesan", publisher_detail="Meesho engineering blog", read_time_basis="publisher",
          why="Why canary releases alone were not enough, and how to replace a deployment tool everything depends on.",
          question="How do you replace the deployment system production depends on?",
          themes=("engineering-practice", "reliability")),
    _seed("airbnb-sunsetting-react-native", "Sunsetting React Native",
          "https://medium.com/airbnb-engineering/sunsetting-react-native-1868ba28e30a", "The Airbnb Tech Blog", "Airbnb", 2018,
          "The last post in Airbnb’s series on React Native: when it worked, engineers moved at unparalleled speed, but technical and organisational problems kept the company from its goals, so it moved all mobile work back to native. An update notes that it reflects React Native as of late 2017.",
          ("React Native", "iOS", "Android", "Mobile"), 6, "airbnb-engineering", published="2018-06-19",
          authors="Gabriel Peal", publisher_detail="Airbnb engineering blog", read_time_basis="publisher",
          why="A candid account of a cross-platform bet that did not pay off, from a team that tried hard.",
          question="Why did Airbnb walk away from React Native?", themes=("engineering-practice",)),
    _seed("shopify-react-native-future", "React Native is the Future of Mobile at Shopify",
          "https://shopify.engineering/react-native-future-mobile-shopify", "Shopify Engineering", "Shopify", 2020,
          "After years of native development, Shopify chose React Native for all new mobile apps. Trials on three apps found the Arrive team felt twice as productive, and code shared between iOS and Android reached 95% in Arrive and 99% in Compass, well above the 80% they had estimated. Existing native apps were not rewritten automatically.",
          ("React Native", "Mobile", "Code sharing"), 8, "engineering-shopify", published="2020-01-29",
          authors="Farhan Thawar", publisher_detail="Shopify engineering blog",
          why="The opposite decision to Airbnb’s, made later and with measured results.",
          question="Why did Shopify bet on React Native when Airbnb left it?", themes=("engineering-practice",)),
    _seed("discord-ios-react-native-performance", "How Discord achieves native iOS performance with React Native",
          "https://discord.com/blog/how-discord-achieves-native-ios-performance-with-react-native", "Discord Blog", "Discord",
          2019,
          "Discord’s iOS app, built by three core iOS engineers on React Native, had slowly grown sluggish. A mobile performance squad worked through Flux store updates, React rendering, main-thread work and RAM bundles; one message-loading action fell from 500ms to 30ms on an iPhone XS and from 1,000ms to 90ms on an iPhone 6s.",
          ("React Native", "iOS", "Profiling", "Performance"), 10, "engineering-discord", published="2019-11-07",
          authors="Miguel Gaeta", publisher_detail="Discord engineering blog",
          why="A step-by-step profiling story with before and after numbers on real phones.",
          question="Can a React Native app feel as fast as a native one?", themes=("performance",)),
    _seed("netflix-faster-website", "Making Netflix.com Faster",
          "https://netflixtechblog.com/making-netflix-com-faster-f95d15f2e972", "Netflix TechBlog", "Netflix", 2015,
          "Netflix rebuilt its website on Node.js and React with universal JavaScript, so the same code renders on the server and in the browser, and cut its JavaScript payload. Together the changes reduced startup time by 70%.",
          ("JavaScript", "Server-side rendering", "Node.js", "React"), 4, "netflix-techblog", published="2015-08-05",
          authors="Kristofer Baxter", publisher_detail="Netflix TechBlog", read_time_basis="publisher",
          why="An early, influential case for server and client rendering sharing one codebase.",
          question="How did Netflix cut its website’s startup time by 70%?", themes=("performance",)),
    _seed("slack-rebuilding-desktop", "When a rewrite isn’t: rebuilding Slack on the desktop",
          "https://slack.engineering/rebuilding-slack-on-the-desktop/", "Engineering at Slack", "Slack", 2019,
          "Slack’s desktop client, built in 2012 with jQuery and manual DOM updates, loaded every workspace in its own Electron process. Slack rebuilt it in React inside the running product, using strict legacy-interop rules so old code never imported new code directly, until the modern version could run on the new code alone.",
          ("React", "Electron", "Rewrite", "Frontend"), 10, "engineering-slack", published="2019-07-22",
          authors="Mark Christian · Johnny Rodgers", publisher_detail="Engineering at Slack", read_time_basis="publisher",
          why="How to rewrite a large app piece by piece instead of starting over.",
          question="How do you rewrite an app without stopping to rewrite it?",
          themes=("engineering-practice", "performance")),
    _seed("pinterest-pwa-retrospective", "A one year PWA retrospective",
          "https://medium.com/pinterest-engineering/a-one-year-pwa-retrospective-f4a2f4129e05", "Pinterest Engineering Blog",
          "Pinterest", 2018,
          "Pinterest rebuilt its mobile website as a progressive web app, kept its bundle in check with size alerts and lint rules, and cached an app shell in a service worker for near-instant reloads. After a year, weekly active users on mobile web were up 103%, and 312% in India.",
          ("Progressive Web Apps", "Service workers", "JavaScript", "Mobile web"), 7, "engineering-pinterest",
          published="2018-07-20", authors="Zack Argyle", publisher_detail="Pinterest engineering blog", read_time_basis="publisher",
          why="Proof that a fast mobile website can matter as much as an app in fast-growing markets.",
          question="What happened when Pinterest made its mobile website fast?", themes=("performance",)),
    _seed("uber-rider-app-architecture", "Engineering the Architecture Behind Uber’s New Rider App",
          "https://www.uber.com/blog/new-rider-app-architecture/", "Uber Blog", "Uber", 2016,
          "Uber rewrote its rider app from scratch with two goals: 99.99% availability for the core ride flow and room for hundreds of teams to experiment safely. It moved from MVC to Riblets, an architecture derived from VIPER and shared by its iOS and Android engineers.",
          ("Mobile architecture", "iOS", "Android", "Riblets"), 10, "uber-engineering", published="2016-12-20",
          authors="Vivian Tran · Yixin Zhu", publisher_detail="Uber engineering blog",
          why="What a mobile architecture needs when thousands of engineers work in one app.",
          question="Why did Uber rebuild its rider app from scratch?", themes=("engineering-practice", "reliability")),
    # --- Round 12: data and ML platforms, observability, and security engineering -----------------------------
    _seed("uber-michelangelo", "Meet Michelangelo: Uber’s Machine Learning Platform",
          "https://www.uber.com/blog/michelangelo-machine-learning-platform/", "Uber Blog", "Uber", 2017,
          "Before Michelangelo, Uber had no reliable way to build training data, models could not outgrow a data scientist’s desktop, experiments were not tracked, and every team built its own serving path. Michelangelo standardised the whole workflow, from managing data to training, deploying and monitoring predictions.",
          ("Machine learning", "ML platform", "Feature store"), 15, "uber-engineering", published="2017-09-05",
          publisher_detail="Uber engineering blog",
          why="The platform that made ‘ML-as-a-service’ inside a company a common pattern.",
          question="What does it take to let every team ship machine learning?", themes=("ai", "distributed-systems")),
    _seed("doordash-feature-store-redis", "Building a Gigascale ML Feature Store with Redis, Binary Serialization, String Hashing, and Compression",
          "https://careersatdoordash.com/blog/building-a-gigascale-ml-feature-store-with-redis/", "DoorDash Engineering",
          "DoorDash", 2020,
          "DoorDash’s Redis feature store, holding billions of records for model inference, was close to running out of capacity. After benchmarking five key-value stores, the team kept Redis and changed how features are stored, with string hashing, protocol buffers and Snappy compression, tripling capacity and cutting Redis latency by 38%.",
          ("Redis", "Feature store", "Machine learning", "Compression"), 14, "doordash-engineering", published="2020-11-19",
          authors="Arbaz Khan · Zohaib Sibte Hassan", publisher_detail="DoorDash engineering blog",
          why="A data-layout fix that beat a database migration.",
          question="How do you fit billions of ML features in Redis?", themes=("databases", "ai", "performance")),
    _seed("linkedin-kafka-benchmark", "Benchmarking Apache Kafka: 2 Million Writes Per Second (On Three Cheap Machines)",
          "https://engineering.linkedin.com/kafka/benchmarking-apache-kafka-2-million-writes-second-three-cheap-machines",
          "LinkedIn Engineering", "LinkedIn", 2014,
          "Jay Kreps benchmarks Kafka, LinkedIn’s central log for integrating data, stream processing and Hadoop ingestion, and shows two million writes a second on three modest machines. He explains why a persistent, partitioned log shared by every consumer makes that throughput possible.",
          ("Kafka", "Logs", "Benchmarks", "Stream processing"), 12, None, published="2014-04-27",
          authors="Jay Kreps", publisher_detail="LinkedIn engineering blog",
          why="Why a simple append-only log became the backbone of data infrastructure.",
          question="How can three cheap machines take two million writes a second?",
          themes=("distributed-systems", "performance")),
    _seed("netflix-personalization-architecture", "System Architectures for Personalization and Recommendation",
          "https://netflixtechblog.com/system-architectures-for-personalization-and-recommendation-e081aa94b5d8",
          "Netflix TechBlog", "Netflix", 2013,
          "Netflix splits recommendation work into offline batch jobs, nearline computation that reacts to events without serving in real time, and online computation that answers requests as they happen. The post explains the trade-offs of each and how signals and models move between them.",
          ("Recommendations", "Machine learning", "Hadoop", "Architecture"), 11, "netflix-techblog", published="2013-03-27",
          authors="Xavier Amatriain · Justin Basilico", publisher_detail="Netflix TechBlog", read_time_basis="publisher",
          why="The offline, nearline and online split that still shapes recommendation systems.",
          question="How does Netflix compute recommendations at different speeds?", themes=("ai", "distributed-systems")),
    _seed("google-sre-monitoring", "Monitoring Distributed Systems",
          "https://sre.google/sre-book/monitoring-distributed-systems/", "Site Reliability Engineering (Google)", "Google",
          2016,
          "Chapter 6 of Google’s SRE book: the four golden signals, white-box versus black-box monitoring, symptoms versus causes, and why the parts of monitoring that page a human must be very simple and robust.",
          ("Monitoring", "Alerting", "SRE", "On-call"), 25, None,
          authors="Rob Ewaschuk", publisher_detail="O’Reilly book, free online edition",
          why="The chapter most monitoring and alerting practices still trace back to.",
          question="What should actually page an engineer?", themes=("reliability",)),
    _seed("netflix-observability-lessons", "Lessons from Building Observability Tools at Netflix",
          "https://netflixtechblog.com/lessons-from-building-observability-tools-at-netflix-7cfafed6ab17",
          "Netflix TechBlog", "Netflix", 2018,
          "As Netflix grew, storing every device and server log stopped scaling, so it streamed logs through Mantis and kept only what matched a query. Netflix also found request tracing was not enough without application context, and that anomaly detection and metric correlation beat plain threshold alerts.",
          ("Observability", "Logging", "Tracing", "Alerting"), 9, "netflix-techblog", published="2018-06-04",
          publisher_detail="Netflix TechBlog", read_time_basis="publisher",
          why="Three hard-won lessons about logs, traces and alerts at scale.",
          question="What happens when you can no longer afford to keep every log?", themes=("reliability", "cloud")),
    _seed("slack-tracing-causal-graphs", "Tracing at Slack: Thinking in Causal Graphs",
          "https://slack.engineering/tracing-at-slack-thinking-in-causal-graphs/", "Engineering at Slack", "Slack", 2020,
          "“Why is it slow?” is the hardest question in a distributed system. Existing tracing tools did not suit Slack’s clients and scripts and kept traces locked in a UI, so Slack models traces as causal graphs of SpanEvents that engineers can also query with SQL.",
          ("Distributed tracing", "Observability", "SQL"), 19, "engineering-slack", published="2020-08-28",
          authors="Suman Karumuri", publisher_detail="Engineering at Slack", read_time_basis="publisher",
          why="Treating traces as data to query, not just pictures to look at.",
          question="How do you find out why a request was slow?", themes=("reliability", "distributed-systems")),
    _seed("datadog-husky-event-store", "Introducing Husky, Datadog’s third-generation event store",
          "https://www.datadoghq.com/blog/engineering/introducing-husky/", "Datadog Blog", "Datadog", 2022,
          "Logs keep every event with its context, which metrics databases avoid by pre-aggregating. To store that volume, Datadog built Husky, a columnar event store that separates compute from storage: stateless writers, compactors and readers on top of blob storage, with FoundationDB holding the metadata.",
          ("Storage", "Columnar", "Object storage", "Logs"), 14, "datadog-blog", published="2022-05-17",
          authors="Richard Artoul · Cecilia Watt", publisher_detail="Datadog engineering blog", read_time_basis="publisher",
          why="How an observability company stores logs at scale by separating compute from storage.",
          question="Where do all the logs go?", themes=("databases", "distributed-systems")),
    _seed("uber-m3-metrics", "M3: Uber’s Open Source, Large-scale Metrics Platform for Prometheus",
          "https://www.uber.com/blog/m3/", "Uber Blog", "Uber", 2018,
          "Uber stores billions of metrics, beyond what a single Prometheus node can handle. It built M3, open sourced as a remote storage backend for Prometheus, with M3DB as a distributed time series store and M3 Coordinator for global queries, downsampling and retention rules.",
          ("Metrics", "Prometheus", "Time series"), 12, "uber-engineering", published="2018-08-07",
          authors="Rob Skillington", publisher_detail="Uber engineering blog",
          why="What metrics infrastructure looks like once one Prometheus server is not enough.",
          question="How do you store billions of metrics?", themes=("databases", "reliability")),
    _seed("cloudflare-phishing-hardware-keys", "The mechanics of a sophisticated phishing scam and how we stopped it",
          "https://blog.cloudflare.com/2022-07-sms-phishing-attacks/", "Cloudflare Blog", "Cloudflare", 2022,
          "In under a minute, at least 76 Cloudflare employees received texts linking to a fake Okta login that relayed credentials to attackers in real time. Some employees fell for it, but the attack failed because every employee must use a physical security key to reach company applications.",
          ("Phishing", "Security keys", "FIDO2", "Zero trust"), 11, "cloudflare-blog", published="2022-08-09",
          authors="Matthew Prince · Daniel Stinson-Diess · Sourov Zaman", publisher_detail="Cloudflare Blog",
          read_time_basis="publisher",
          why="A clear case that hardware keys stop phishing even when people click.",
          question="Why didn’t a successful phishing attack get in?", themes=("security",)),
    _seed("google-slsa-supply-chain", "Introducing SLSA, an End-to-End Framework for Supply Chain Integrity",
          "https://security.googleblog.com/2021/06/introducing-slsa-end-to-end-framework.html", "Google Online Security Blog",
          "Google", 2021,
          "After attacks like SolarWinds and Codecov, Google proposed SLSA, levels of assurance for how software is built, inspired by its internal Binary Authorization for Borg, used for over eight years on all production workloads. Each threat in the supply chain is mapped to the control that would have stopped it.",
          ("Supply chain", "Provenance", "Build systems"), 8, "google-security", published="2021-06-16",
          authors="Kim Lewandowski · Mark Lodato", publisher_detail="Google Online Security Blog",
          why="A practical map of where software can be tampered with between commit and production.",
          question="How do you prove a binary came from the code you reviewed?", themes=("security", "engineering-practice")),
    _seed("dropbox-password-storage", "How Dropbox securely stores your passwords",
          "https://dropbox.tech/security/how-dropbox-securely-stores-your-passwords", "Dropbox Tech", "Dropbox", 2016,
          "Dropbox protects passwords in three layers: SHA512 first, then bcrypt with a cost of 10 and a per-user salt, then AES256 encryption with a separately stored key, the pepper. The post explains what each layer defends against.",
          ("Passwords", "Cryptography", "bcrypt"), 6, "engineering-dropbox", published="2016-09-21",
          authors="Devdatta Akhawe", publisher_detail="Dropbox Tech Blog",
          why="A short, precise answer to a question every product team faces.",
          question="How should you store passwords?", themes=("security",)),
    _seed("google-beyondcorp", "BeyondCorp: A New Approach to Enterprise Security",
          "https://research.google/pubs/beyondcorp-a-new-approach-to-enterprise-security/", "Google Research", "Google", 2014,
          "Firewalls protect a perimeter, and once that perimeter is breached an attacker reaches the whole intranet. Google instead removed the privileged intranet and moved its corporate applications to the Internet.",
          ("Zero trust", "Network security", "Identity"), 12, "google-research",
          authors="Rory Ward · Betsy Beyer", publisher_detail=";login: magazine paper",
          why="An early, influential account of dropping the trusted corporate network.",
          question="What if there were no trusted internal network?", themes=("security", "cloud")),
)
# Reviewed themes where keyword evidence alone would mislabel a classic.
for _ident, _themes in {
    "google-mapreduce": ("distributed-systems", "cloud"),
    "google-borg": ("cloud", "distributed-systems"),
    "paloalto-unified-data-platform": ("databases", "distributed-systems", "cloud"),
    "uber-big-data-platform": ("databases", "distributed-systems"),
    "anthropic-teams-claude-code": ("ai-engineering", "agents"),
    "claude-code-best-practices": ("ai-engineering", "agents"),
    "anthropic-building-effective-agents": ("agents", "ai"),
    "anthropic-multi-agent-research": ("agents", "ai"),
    "anthropic-context-engineering": ("agents", "ai"),
    "anthropic-writing-tools": ("agents", "ai"),
    "microsoft-learn-mcp": ("agents", "ai"),
    "anthropic-opus-4-6": ("ai",),
    "cloudflare-pingora": ("performance", "cloud"),
}.items():
    next(article for article in CURATED_CURIOSITY if article["id"] == _ident)["themes"] = list(_themes)

# Reviewed problem → approach → result lines for postmortems and case studies, written from each source.
REVIEWED_BREAKDOWNS = {
    "gitlab-database-outage-2017": (
        "Data was removed from GitLab.com’s only primary database, and the daily pg_dump backups were missing.",
        "The team restored from an LVM snapshot that had been taken hours earlier for staging.",
        "About six hours of database changes were lost, and GitLab committed to fixing its backup and recovery procedures."),
    "atlassian-outage-2022": (
        "A cleanup script received whole-site IDs instead of app IDs, and the deletion API accepted them.",
        "Engineers restored the deleted sites progressively between April 8 and April 18.",
        "775 customers lost access to their Atlassian products, some for up to 14 days."),
    "aws-s3-outage-2017": (
        "A mistyped input removed far more S3 servers than intended, including the index and placement subsystems.",
        "Both subsystems had to be restarted from scratch while dependent services waited.",
        "The tool now removes capacity slowly and will not take a subsystem below its minimum."),
    "aws-us-east-1-2021": (
        "An automated scaling activity caused a surge of connections that overwhelmed AWS’s internal network devices.",
        "Operators worked with little monitoring data, because the congestion hid it, while clients failed to back off.",
        "Latency and errors lasted for hours across services in the region."),
    "meta-outage-2021": (
        "A backbone maintenance command disconnected every Facebook data center, and an audit-tool bug failed to stop it.",
        "DNS servers withdrew their BGP routes as designed; engineers had to reach data centers in person to restore them.",
        "Facebook and its apps were unreachable from the whole internet until engineers restored the backbone."),
    "github-october-2018-incident": (
        "A 43-second network partition made Orchestrator fail MySQL primaries over to the West Coast.",
        "GitHub chose data integrity over availability, holding back webhooks and Pages builds while it reconciled writes.",
        "24 hours and 11 minutes of degraded service; no user data was lost."),
    "cloudflare-outage-june-2022": (
        "A network change in Cloudflare’s resilience project broke routing in its 19 busiest data centers.",
        "Engineers reverted the change, bringing locations back between 06:58 and 07:42 UTC.",
        "About 75 minutes of outage in 19 locations that carry a large share of Cloudflare’s traffic."),
    "cloudflare-control-plane-2023": (
        "A power failure at one Oregon data center took down part of the three-site control plane cluster.",
        "Cloudflare brought most of the control plane up at its disaster recovery facility within about six hours.",
        "Network traffic was unaffected, but some control plane and logging services were down until November 4."),
    "fastly-outage-june-2021": (
        "A bug shipped in May was triggered by one customer’s valid configuration change.",
        "Fastly identified and disabled the configuration, then deployed a permanent fix.",
        "85% of the network returned errors; 95% recovered within 49 minutes."),
    "datadog-outage-march-2023": (
        "An automatic systemd update deleted the Cilium routes containers use to talk to each other.",
        "Hundreds of responders brought services back over more than a day, then backfilled historical data.",
        "Five regions were affected; Datadog disabled the automatic update that triggered it."),
    "slack-incident-2-22-22": (
        "Cache tier problems pushed load onto the databases that client boot depends on.",
        "The team throttled client boot requests so already-connected users kept working, then raised the limit step by step.",
        "Service recovered gradually; the write-up explains how scatter queries and retries kept the system overloaded."),
    "crowdstrike-falcon-pir-2024": (
        "A bug in the Content Validator let a faulty content update reach Windows sensors.",
        "CrowdStrike reverted the faulty update 78 minutes after releasing it.",
        "Commitments to more testing and staggered, canary-first rollouts for content updates."),
    "notion-sharding-postgres": (
        "Notion’s single Postgres database was approaching its limits as usage grew.",
        "The team sharded data into 480 logical shards on 32 databases, double-writing and backfilling before switching.",
        "The switchover took five minutes of scheduled downtime and made Notion noticeably faster."),
    "uber-postgres-to-mysql": (
        "Postgres caused write amplification, replication and upgrade problems at Uber’s scale.",
        "Uber built Schemaless, a sharding layer, on MySQL’s InnoDB instead.",
        "Many Postgres workloads moved to MySQL-based storage."),
    "github-partitioning-mysql": (
        "Most of GitHub’s core data lived in a single MySQL cluster, mysql1.",
        "Tables were grouped into schema domains, boundaries enforced with SQL linters, then moved to new clusters.",
        "50% less load on the hosts that held mysql1 data, and fewer database incidents."),
    "slack-vitess-migration": (
        "Slack’s active-active MySQL clusters were hard to scale for new features.",
        "Slack migrated workloads to Vitess, a horizontal sharding system for MySQL, over three years.",
        "Vitess serves 99% of the query load at 2.3 million queries per second at peak."),
    "segment-goodbye-microservices": (
        "More than 140 per-destination microservices and queues had become unmanageable.",
        "Segment merged them into one service in a monorepo, with Centrifuge and Traffic Recorder.",
        "Faster, more reliable tests and far less operational overhead, at the cost of some isolation."),
    "dropbox-magic-pocket": (
        "Dropbox needed its own system to store exabytes of file content durably.",
        "It built Magic Pocket, which splits files into blocks replicated across regions.",
        "An in-house storage system holding Dropbox’s file content."),
    "aws-dynamodb-dns-2025": (
        "A latent race condition between two DNS Enactors left DynamoDB’s regional endpoint with an empty DNS record.",
        "AWS walks through the recovery and the knock-on failures in EC2 launches and load balancer health checks.",
        "The disruption ran from 11:48 PM on October 19 to 2:20 PM PDT on October 20."),
    "cloudflare-outage-november-2025": (
        "A database permissions change doubled the Bot Management feature file past the proxy’s size limit.",
        "After first suspecting a DDoS attack, Cloudflare rolled back to an earlier version of the file.",
        "Core traffic was normal by 14:30 UTC and all systems by 17:06 UTC."),
    "google-cloud-service-control-2025": (
        "Service Control code added on May 29 had no error handling and was not behind a feature flag.",
        "A policy with blank fields reached that code path, hit a null pointer and crashed the binary.",
        "Multiple Google Cloud products were affected from 10:51 to 18:18 US/Pacific."),
    "openai-december-2024-incident": (
        "A new telemetry service overloaded the Kubernetes API in OpenAI’s largest clusters.",
        "DNS caching delayed visible failures, so the rollout continued and broke DNS-based service discovery.",
        "ChatGPT fully recovered at 7:01 PM PST and the API at 7:38 PM."),
    "github-ddos-2018": (
        "A memcached amplification attack peaked at 1.35 Tbps against GitHub.com.",
        "GitHub withdrew its BGP announcements through ChatOps so Akamai could absorb the traffic.",
        "GitHub.com was down from 17:21 to 17:26 UTC and intermittently unavailable until 17:30."),
    "cloudflare-leap-second-2017": (
        "The leap second produced a negative value in RRDNS, Cloudflare’s Go DNS server, which panicked.",
        "Engineers patched RRDNS and rolled the fix out worldwide, finishing by 06:45 UTC.",
        "About 0.2% of DNS queries failed at peak; most machines were patched within 90 minutes."),
    "letsencrypt-caa-rechecking-bug": (
        "Boulder rechecked CAA for one domain N times instead of each of a certificate’s N domains.",
        "Let’s Encrypt halted issuance two minutes after finding the bug and deployed a fix.",
        "A fix was deployed at 05:22 UTC; the bug had been live since July 25, 2019."),
    "knight-capital-sec-2013": (
        "A faulty deployment left old, unused code live in Knight Capital’s order router.",
        "The router sent more than 4 million orders in 45 minutes while trying to fill 212 customer orders.",
        "A loss of more than $460 million and a $12 million SEC penalty over missing safeguards."),
    "xz-utils-backdoor-2024": (
        "The xz 5.6.0 and 5.6.1 release tarballs carried an obfuscated backdoor in their build step.",
        "Andres Freund traced slow, CPU-heavy ssh logins and valgrind errors back to liblzma.",
        "His report to oss-security made the backdoor public on March 29, 2024."),
    "circleci-security-incident-2023": (
        "Malware on an engineer’s laptop stole a valid, 2FA-backed SSO session.",
        "CircleCI rotated tokens, investigated, and asked customers to rotate every secret stored with it.",
        "Data was exfiltrated on December 22, 2022, and the attacker pulled encryption keys from a running process."),
    "cloudflare-thanksgiving-2023": (
        "Credentials not rotated after the October 2023 Okta compromise let an attacker into Cloudflare’s Atlassian server.",
        "Cloudflare cut off access and ran ‘Code Red’, rotating more than 5,000 credentials and reimaging every machine.",
        "The attacker saw some documentation and a limited amount of source code; production beyond Atlassian was not reached."),
    "okta-support-system-rca-2023": (
        "A service account’s password, saved in an employee’s personal Google profile, was used to enter Okta’s support system.",
        "Okta investigated, notified affected customers and changed how the support system handles access and data.",
        "Files of 134 customers were accessed and session tokens were used against 5 of them."),
    "cloudflare-log4j-cve-2021-44228": (
        "A JNDI lookup feature added to Log4j in 2013 let a logged string make a server load and run remote code.",
        "Cloudflare checked and mitigated its own Java systems and rolled out firewall rules for customers.",
        "The flaw affects Log4j 2.0-beta-9 to 2.14.1 and is patched in later releases."),
    "37signals-left-the-cloud": (
        "37signals was spending millions a year renting cloud servers for long-running apps.",
        "It moved its apps onto its own Dell servers, using KVM, Docker and Kamal, over six months.",
        "About $500,000 of hardware and estimated savings of at least $1.5 million a year."),
    "discord-indexing-trillions": (
        "Discord’s Redis indexing queue dropped messages whenever Elasticsearch failures backed it up.",
        "The team moved to PubSub, batched writes per destination cluster and ran smaller clusters in cells on Kubernetes.",
        "Elasticsearch failures now slow indexing down instead of losing messages."),
    "github-rails-upgrade-2018": (
        "GitHub’s main application was still on Rails 3.2.",
        "The app was made to dual boot two Rails versions, so upgrade work shipped without a long-running branch.",
        "After a year and a half, GitHub ran on Rails 5.2.1 from August 15, 2018."),
    "figma-webassembly-load-time": (
        "Figma’s C++ editor ran in the browser as asm.js, which was slow to load.",
        "Figma compiled it to WebAssembly, which parses about 20 times faster and can be cached.",
        "Load time fell by three times."),
    "canva-counting-billions": (
        "Canva’s MySQL-based counting service struggled with billions of monthly content uses.",
        "Canva moved to an OLAP database and an ELT pipeline that computes the counts end to end.",
        "Billions of usage events are aggregated in a few minutes."),
    "khan-academy-goliath": (
        "Python 2 was reaching end of life under Khan Academy’s monolith.",
        "After weighing Python 3 and Kotlin, the team chose to rebuild as services in Go.",
        "A multi-year rewrite, named Goliath, aimed at better performance and long-term support."),
    "stripe-sorbet": (
        "Millions of lines of Ruby had become hard for new engineers to learn and risky to change.",
        "Stripe built and open sourced Sorbet, a fast type checker for Ruby.",
        "Sorbet now checks more than 15 million lines across 150,000 files."),
    "uber-querygpt": (
        "Writing SQL for Uber’s data platform took about 10 minutes per query, across 1.2 million queries a month.",
        "QueryGPT narrows the LLM’s focus with workspaces of curated tables and examples and an intent agent.",
        "Queries are generated in about 3 minutes."),
    "linkedin-genai-product-musings": (
        "LinkedIn set out to build a new AI-powered experience for its members.",
        "A fixed routing, retrieval and generation pipeline across many agents, with shared prompts and evaluation.",
        "80% quality came quickly; the last 20% and reliable evaluation took most of the work."),
    "shopify-bfcm-scale-testing": (
        "Shopify’s platform has to handle the traffic peak of Black Friday Cyber Monday.",
        "The team scales up and stacks browsing, checkout and flash-sale load tests to target request rates.",
        "Findings drive performance fixes, and the test is repeated several times a year."),
    "hotstar-scaling-for-50m": (
        "Hotstar needed to serve far more concurrent cricket viewers than its record 25 million.",
        "Static capacity ‘ladders’ instead of autoscaling, tuning of over-generic processing layers, and harsh traffic simulations.",
        "Simulations exposed a hot spot that triggered a cascading failure before a real match could."),
    "spotify-tech-migrations": (
        "Spotify’s migrations stalled in a long tail of systems left on old versions.",
        "A prioritised company-wide migrations map, migrations run like products, and automation, tracked in Backstage.",
        "Engineering teams see scheduled migrations and their progress in one place instead of a flood of emails."),
    "airbnb-great-migration-soa": (
        "Airbnb set out to move off Monorail, its Ruby on Rails monolith, onto services.",
        "It defined service tenets and layers: data, derived data, middle-tier and presentation services.",
        "A migration to services with documented lessons and best practices."),
    "honeycomb-hard-stuff-llms": (
        "Turning natural language into a valid Honeycomb query is hard with huge schemas and slow models.",
        "Query Assistant sends one prompt with the schema, examples and instructions, then parses and corrects the output.",
        "A shipped feature, and a list of problems that had no complete solution."),
    "google-cloud-europe-west2-power-2026": (
        "Utility feed A failed while feed B’s breaker was open for repairs, and the generator controller saw voltage upstream of it.",
        "The PLC never started the generators; the team moved the load to the standby utility source, then fixed the PLC logic.",
        "europe-west2-b lost power once its UPS batteries ran out; the main impact was resolved within 6 hours and 8 minutes."),
    "github-availability-september-2026": (
        "Two September incidents hit GitHub while it moved production services and databases to Azure.",
        "GitHub reduced load on shared databases, added overload controls and paused regional ramps when capacity was uneven.",
        "By October 7, 120 of 160 services ran in Central US and 13 of 51 primary MySQL databases had moved."),
    "zerodha-scaling-common-sense": (
        "Zerodha had to serve millions of traders through market hours without overbuilding.",
        "Partitioned Postgres with replicas, a hot Redis cache filled by separate services, and HTTP caching with E-Tags.",
        "Kite serves every screen from memory, with a few hundred GB of data for millions of users."),
    "phonepe-technology-journey": (
        "PhonePe set out to design every system for millions of users from the start.",
        "Rules from day one: asynchronous flows, shared-nothing storage, sharded databases, no cross-service caching.",
        "50 million daily app sessions and 2 billion data events a day on the same principles."),
    "flipkart-tidb-active-passive": (
        "Flipkart’s database clusters span regions and need fast disaster recovery.",
        "An active TiDB cluster replicates asynchronously to a passive cluster in another data center through TiCDC.",
        "A documented two-region topology with known replication guarantees."),
    "swiggy-serviceability-platform": (
        "Swiggy must check about 200 million restaurant-to-customer pairs a minute at peak, with p99 under 200ms.",
        "GeoHash-indexed point-in-polygon search over in-memory caches, replicated to scale horizontally.",
        "A pre-order check fast and fault-tolerant enough to sit in front of every listing and checkout."),
    "dream11-ipl-2023-concurrency": (
        "IPL 2023 was expected to bring far more simultaneous users than the 7 million Dream11 saw in 2022.",
        "Maturity assessments, fire drills and runbooks, automated scaling and load tests of every critical service.",
        "10.56 million concurrent users and over 308 million requests a minute in the opening match."),
    "meesho-rollout-service": (
        "Failures slipped past canary checks and urgent rollbacks waited behind a sequential deployment tool.",
        "Meesho built Rollout Service, an in-house deployment manager designed for faster, safer rollouts.",
        "Rollout Service now orchestrates production deployments across Meesho."),
    "airbnb-sunsetting-react-native": (
        "React Native at Airbnb delivered speed when it worked, but technical and organisational problems kept piling up.",
        "After a long trial across many teams, Airbnb decided to stop investing in React Native.",
        "All mobile work moved back to native iOS and Android."),
    "shopify-react-native-future": (
        "Shopify wanted to build mobile apps faster across iOS and Android.",
        "It trialled React Native on three apps, including a full rewrite of Arrive.",
        "95% to 99% shared code, and React Native for every new Shopify mobile app."),
    "discord-ios-react-native-performance": (
        "Discord’s React Native iOS app had developed frame drops, battery drain and slow interactions.",
        "A performance squad optimised Flux stores, React components, main-thread work and bundle loading.",
        "One action fell from 500ms to 30ms on an iPhone XS and from 1,000ms to 90ms on an iPhone 6s."),
    "netflix-faster-website": (
        "Netflix.com rendered on the server and then patched pages with jQuery, which slowed startup.",
        "Universal JavaScript on Node.js and React, plus a smaller JavaScript payload.",
        "Startup time fell by 70%."),
    "slack-rebuilding-desktop": (
        "Slack’s desktop app updated the DOM by hand, loaded everything eagerly and ran one Electron process per workspace.",
        "A new React codebase grew inside the old app, kept apart by strict legacy-interop rules.",
        "A rebuilt desktop app that runs every workspace in one process, shipped without a big-bang rewrite."),
    "pinterest-pwa-retrospective": (
        "Pinterest’s mobile website was slow and converted far fewer people than its apps.",
        "A progressive web app with bundle-size alerts, lint rules and a service-worker app shell.",
        "Weekly active mobile web users up 103% in a year, and 312% in India."),
    "uber-rider-app-architecture": (
        "Uber’s MVC rider app could not give the core ride flow 99.99% availability while many teams built on it.",
        "Uber rewrote the app on Riblets, a VIPER-derived architecture shared by iOS and Android.",
        "A new rider app built for reliability and safe experimentation by hundreds of teams."),
    "uber-michelangelo": (
        "Uber had no standard way to build training data, train beyond a laptop, track experiments or serve models.",
        "Michelangelo standardised the end-to-end workflow: data, training, evaluation, deployment, prediction and monitoring.",
        "It became the default ML system for Uber’s engineers and data scientists, with dozens of teams on it."),
    "doordash-feature-store-redis": (
        "DoorDash’s Redis feature store, with billions of records, was close to running out of capacity.",
        "After benchmarking five key-value stores, it kept Redis and changed storage: string hashing, protobufs, Snappy.",
        "Three times the capacity and 38% lower Redis latency."),
    "netflix-observability-lessons": (
        "Storing every device and server log made costs balloon and queries slow.",
        "Netflix streamed logs through Mantis, kept only matching events, and enriched traces with application context.",
        "Scalable log analysis, and alerts based on anomalies and correlations rather than fixed thresholds."),
    "slack-tracing-causal-graphs": (
        "Existing tracing tools did not suit Slack’s clients and scripts and kept traces inside a UI.",
        "Slack models traces as causal graphs of a new data structure, the SpanEvent.",
        "Traces engineers can view and also query with SQL."),
    "datadog-husky-event-store": (
        "Datadog’s log storage could not scale ingestion, storage and queries independently.",
        "Husky separates compute from storage: stateless writers, compactors and readers over blob storage and FoundationDB.",
        "A third-generation event store for logs and other event products."),
    "uber-m3-metrics": (
        "Uber needed to store billions of metrics; a single Prometheus node could not.",
        "It built M3, with M3DB for distributed time series storage and M3 Coordinator for queries and retention.",
        "M3 runs Uber’s metrics and is open source as a Prometheus storage backend."),
    "cloudflare-phishing-hardware-keys": (
        "At least 76 employees received texts linking to a fake Okta page that relayed logins in real time.",
        "Every employee must use a physical security key to access company applications.",
        "Some employees entered credentials, but the attackers could not get in."),
    "google-slsa-supply-chain": (
        "Supply chain attacks such as SolarWinds tampered with software between source and release.",
        "Google proposed SLSA, levels of build integrity modelled on its internal Binary Authorization for Borg.",
        "An open framework that maps each supply chain threat to a control."),
    "dropbox-password-storage": (
        "Stored passwords must survive a database leak.",
        "Three layers: SHA512, then bcrypt with a per-user salt, then AES256 with a separately stored pepper.",
        "Each layer covers a weakness of the others."),
    "google-beyondcorp": (
        "Perimeter firewalls give an attacker easy access to the intranet once breached.",
        "Google removed the privileged intranet and moved corporate applications to the Internet.",
        "Corporate applications that no longer rely on a trusted internal network."),
}
REVIEWED_PROBLEMS = {
    "gitlab-database-outage-2017": ("outages", "data-integrity"), "atlassian-outage-2022": ("outages", "data-integrity"),
    "aws-s3-outage-2017": ("outages",), "aws-us-east-1-2021": ("outages", "scaling-traffic"),
    "meta-outage-2021": ("outages",), "github-october-2018-incident": ("outages", "data-integrity"),
    "cloudflare-outage-june-2022": ("outages",), "cloudflare-control-plane-2023": ("outages",),
    "fastly-outage-june-2021": ("outages",), "datadog-outage-march-2023": ("outages",),
    "slack-incident-2-22-22": ("outages", "performance"), "crowdstrike-falcon-pir-2024": ("outages", "security-incidents"),
    "notion-sharding-postgres": ("scaling-data", "migrations"), "uber-postgres-to-mysql": ("migrations", "scaling-data"),
    "github-partitioning-mysql": ("scaling-data", "migrations"), "slack-vitess-migration": ("scaling-data", "migrations"),
    "segment-goodbye-microservices": ("migrations", "dev-productivity"), "dropbox-magic-pocket": ("scaling-data",),
    "aws-dynamodb-dns-2025": ("outages",), "cloudflare-outage-november-2025": ("outages",),
    "google-cloud-service-control-2025": ("outages",), "openai-december-2024-incident": ("outages", "scaling-traffic"),
    "github-ddos-2018": ("outages", "security-incidents", "scaling-traffic"), "cloudflare-leap-second-2017": ("outages",),
    "letsencrypt-caa-rechecking-bug": ("outages", "security-incidents"), "knight-capital-sec-2013": ("outages",),
    "xz-utils-backdoor-2024": ("security-incidents",), "circleci-security-incident-2023": ("outages", "security-incidents"),
    "cloudflare-thanksgiving-2023": ("security-incidents",), "okta-support-system-rca-2023": ("outages", "security-incidents"),
    "cloudflare-log4j-cve-2021-44228": ("security-incidents",), "37signals-left-the-cloud": ("cost", "migrations"),
    "stack-overflow-architecture-2016": ("performance", "cost"), "discord-indexing-trillions": ("scaling-data", "data-integrity"),
    "github-rails-upgrade-2018": ("migrations", "dev-productivity"), "figma-webassembly-load-time": ("performance", "migrations"),
    "canva-counting-billions": ("scaling-data", "migrations"), "khan-academy-goliath": ("migrations",),
    "stripe-sorbet": ("dev-productivity",), "uber-querygpt": ("dev-productivity",),
    "linkedin-genai-product-musings": ("dev-productivity",), "github-copilot-llms": ("dev-productivity",),
    "shopify-bfcm-scale-testing": ("scaling-traffic", "performance"),
    "hotstar-scaling-for-50m": ("scaling-traffic", "performance"), "spotify-tech-migrations": ("migrations",),
    "airbnb-great-migration-soa": ("migrations",), "honeycomb-hard-stuff-llms": ("performance", "dev-productivity"),
    "google-cloud-europe-west2-power-2026": ("outages",), "github-availability-september-2026": ("outages", "migrations"),
    "zerodha-scaling-common-sense": ("scaling-data", "cost"), "phonepe-technology-journey": ("scaling-data", "scaling-traffic"),
    "flipkart-tidb-active-passive": ("data-integrity", "scaling-data"), "swiggy-serviceability-platform": ("performance", "scaling-traffic"),
    "dream11-ipl-2023-concurrency": ("scaling-traffic",), "meesho-rollout-service": ("dev-productivity", "migrations"),
    "airbnb-sunsetting-react-native": ("migrations", "dev-productivity"), "shopify-react-native-future": ("dev-productivity",),
    "discord-ios-react-native-performance": ("performance",), "netflix-faster-website": ("performance",),
    "slack-rebuilding-desktop": ("migrations", "performance"), "pinterest-pwa-retrospective": ("performance",),
    "uber-rider-app-architecture": ("migrations",),
    "uber-michelangelo": ("dev-productivity",), "doordash-feature-store-redis": ("scaling-data", "cost"),
    "linkedin-kafka-benchmark": ("performance", "scaling-data"), "netflix-personalization-architecture": ("performance",),
    "google-sre-monitoring": ("outages",), "netflix-observability-lessons": ("cost", "scaling-data"),
    "slack-tracing-causal-graphs": ("performance",), "datadog-husky-event-store": ("scaling-data", "cost"),
    "uber-m3-metrics": ("scaling-data",), "cloudflare-phishing-hardware-keys": ("security-incidents",),
    "google-slsa-supply-chain": ("security-incidents",), "dropbox-password-storage": ("security-incidents", "data-integrity"),
    "google-beyondcorp": ("security-incidents",),
}
for _seed_card in CURATED_CURIOSITY:
    if _seed_card["id"] in REVIEWED_BREAKDOWNS:
        _seed_card["breakdown"] = dict(zip(("problem", "approach", "result"), REVIEWED_BREAKDOWNS[_seed_card["id"]]))
    if _seed_card["id"] in REVIEWED_PROBLEMS:
        _seed_card["problems"] = list(REVIEWED_PROBLEMS[_seed_card["id"]])
del _seed_card
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
    ("agents", "AI agents", re.compile(
        r"\b(?:ai agents?|llm agents?|agents|agentic|multi-agents?|sub-?agents?|agent (?:framework|orchestration|memory|"
        r"routing|evaluation|security|loop|harness)|orchestrat\w*|tool (?:calling|use)|function calling|mcp|"
        r"model context protocol|langgraph|crewai|autogen|human[- ]in[- ]the[- ]loop|prompt injection|"
        r"context engineering|guardrails?|autonomous workflows?)\b", re.I)),
    ("ai-engineering", "AI-native engineering", re.compile(
        r"\b(?:coding agents?|background (?:coding )?agents?|ai[- ](?:assisted|generated|powered) (?:code|coding|tests?|"
        r"review|development)|llm[- ](?:driven|powered|based) (?:migration|testing|test generation|code)|code review bots?|"
        r"software factor(?:y|ies)|copilot|claude code|cursor|devin|codex|agentic (?:coding|testing|devops)|"
        r"test generation|automated (?:code|pull requests?)|developer productivity)\b", re.I)),
    ("ai", "AI & LLMs", re.compile(
        r"\b(?:llms?|large language models?|language models?|transformers?|rag|retrieval|embeddings?|"
        r"inference|fine[- ]tun\w*|training runs?|model serving|prompt\w*|claude|gpt[\w.-]*|"
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
# Real-world problems a story is about. Like themes, they are read only from the title, excerpt and
# reviewed tags; reviewed seeds can name them explicitly.
PROBLEMS = (
    ("outages", "Outages & incidents", re.compile(
        r"\b(?:postmortems?|post-mortems?|outages?|incidents?|downtime|degraded|availability reports?|root cause|"
        r"return to service|went down|service disruption|post-incident|what went wrong)\b", re.I)),
    ("scaling-data", "Scaling databases & storage", re.compile(
        r"\b(?:shard\w*|partition\w*|vitess|read replicas?|database (?:scal\w*|growth|fleet)|scal\w* "
        r"(?:postgres\w*|mysql|databases?|storage)|exabytes?|petabytes?|storage systems?|data stores?|"
        r"trillions? of (?:messages|rows|records))\b", re.I)),
    ("migrations", "Migrations & rewrites", re.compile(
        r"\b(?:migrat\w*|rewr(?:ite|ote|iting)\w*|switch(?:ed|ing)? from|moved? (?:from|off)|re-?platform\w*|"
        r"moderni[sz]\w*|monoliths?|from \w+ to \w+|deprecat\w*|cut ?over)\b", re.I)),
    ("performance", "Latency & performance", re.compile(
        r"\b(?:latency|p9[59]|tail latency|throughput|faster|speed(?:ed)? ?up|performance|optimi[sz]\w*|"
        r"bottlenecks?|slow\w*)\b", re.I)),
    ("scaling-traffic", "Scaling traffic & real-time", re.compile(
        r"\b(?:concurrent (?:users|connections|players)|traffic|load balanc\w*|rate limit\w*|"
        r"(?:millions?|billions?) of (?:users|requests|connections|events)|requests per second|qps|rps|"
        r"real-time|peak load|autoscal\w*)\b", re.I)),
    ("data-integrity", "Data loss & consistency", re.compile(
        r"\b(?:data loss|lost (?:data|writes)|consisten\w*|corrupt\w*|backups?|restor\w*|reconcil\w*|"
        r"split[- ]brain|durab\w*|idempoten\w*|exactly[- ]once|deleted)\b", re.I)),
    ("cost", "Cost & efficiency", re.compile(
        r"\b(?:costs?|cheaper|spend\w*|savings?|saved|efficien\w*|(?:cut|reduc\w*) (?:our )?(?:bill|spend|costs?))\b",
        re.I)),
    ("security-incidents", "Security incidents", re.compile(
        r"\b(?:breach\w*|vulnerabilit\w*|exploit\w*|attacks?|leak\w*|compromis\w*|zero[- ]day|cves?|"
        r"memory leak|incident response)\b", re.I)),
    ("dev-productivity", "Developer productivity", re.compile(
        r"\b(?:developer productivity|build times?|ci(?:/cd)?|test suites?|flaky|merge queues?|code review|"
        r"monorepos?|deploy\w* (?:faster|safely|reliably)|release process|developer experience)\b", re.I)),
)
PROBLEM_LABELS = {ident: label for ident, label, _ in PROBLEMS}
# Language that marks a story about a real problem and how it was handled, rather than a feature tour.
_problem_signal = re.compile(
    r"\b(?:postmortems?|post-mortems?|outages?|incidents?|root cause|what went wrong|lessons learned|"
    r"availability reports?|we (?:migrated|moved|rebuilt|rewrote|reduced|cut|fixed|scaled|eliminated|replaced)|"
    r"how we (?:migrated|scaled|fixed|reduced|cut|survived|debugged|handled|tackled|solved)|bottlenecks?|"
    r"debugg\w*|from \d[\d,.]*\s?\w* to \d|\d+\s?% (?:faster|fewer|less|lower|reduction|cheaper))\b", re.I)


def card_problems(article, limit=2):
    """Problems a story deals with, ranked by evidence (a title match counts three times)."""
    reviewed = [problem for problem in article.get("problems") or () if problem in PROBLEM_LABELS]
    if reviewed:
        return reviewed[:limit]
    title = str(article.get("title", ""))
    body = f"{article.get('description') or article.get('cleanSummary') or ''} " \
           f"{' '.join(str(tag) for tag in article.get('tags') or ())}"
    scored = []
    for order, (ident, _, matcher) in enumerate(PROBLEMS):
        score = 3 * len(matcher.findall(title)) + len(matcher.findall(body))
        if score >= 2 or matcher.search(title):
            scored.append((-score, order, ident))
    return [ident for _, _, ident in sorted(scored)[:limit]]


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

_PRIORITY_THEMES = frozenset({"game-engineering", "agents", "ai-engineering"})

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
    if any(matcher.search(title) for ident, _, matcher in THEMES if ident in _PRIORITY_THEMES):
        score += 1  # Game engineering, agents and AI-native engineering are rare in feeds; give them a little room.
    # Real problems and how they were handled lead the shelf: postmortems, migrations, measured fixes.
    score += min(3, 2 * bool(_problem_signal.search(title)) + bool(_problem_signal.search(description)))
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


def _breakdown(article):
    """The reviewed problem → approach → result lines, only for cards an editor has checked."""
    value = article.get("breakdown") if article.get("curiosity_seed") else None
    if not isinstance(value, dict):
        return None
    lines = {key: sanitize_text(value.get(key), 320) for key in ("problem", "approach", "result")}
    return lines if all(lines.values()) else None


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
        "problems": card_problems(article),
        "breakdown": _breakdown(article),
        "level": card_level(article),
        "technologies": card_technologies(article),
        "why_read": sanitize_text(article.get("why_read") or summary.get("whyItMatters"), 300),
        "question": sanitize_text(article.get("question"), 200),
        "read_minutes": read_minutes,
        "read_time_basis": read_basis,
        "url": public["url"],
        "source_id": article["source_id"],
        "kind": source.kind if source else article.get("kind", "engineering"),
        "description": article.get("description", ""),
        "seed": bool(article.get("curiosity_seed")),
        "related": related_seeds(article["id"]) if article.get("curiosity_seed") and article["id"] in SEEDS_BY_ID else [],
    }


MAX_CURIOSITY_CARDS = 400
# Fresh archive discoveries get a reserved share so evergreen seeds never crowd them out.
FRESH_SLOT_SHARE = 3
MAX_FRESH_CARDS = 40


def _fresh_discoveries(store, limit):
    if not store or limit <= 0:
        return []
    # Up to four recent posts from every engineering and research publisher, so quieter blogs with
    # postmortems are considered alongside the busiest feeds.
    candidates = store.curiosity_candidates(_candidate_sources(), hours=90 * 24, limit=1500, per_source=4)
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
    # Fresh cards are summarised by a model, so their number is capped however large the shelf is.
    fresh = _fresh_discoveries(store, min(MAX_FRESH_CARDS, max(reserve, limit - len(CURATED_CURIOSITY))))
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


# --- Reading lists ------------------------------------------------------------------------------------
# Ordered paths through reviewed cards only, so every list links to pages an editor has read. Ten is the
# Brief Builder's pin limit, so a whole list always fits in one brief.
COLLECTIONS = (
    ("anatomy-of-a-global-outage", "Anatomy of a global outage",
     "How one command, one config change or one update took down services millions rely on, and what each "
     "company changed afterwards. Read in order: a mistyped command, a backbone change, an overloaded internal "
     "network, one regular expression, a dormant bug and a content update.",
     ("aws-s3-outage-2017", "meta-outage-2021", "aws-us-east-1-2021", "cloudflare-outage-2019",
      "fastly-outage-june-2021", "crowdstrike-falcon-pir-2024"), ("outages",)),
    ("when-backups-and-failover-fail", "When backups and failover fail",
     "Safety nets that did not catch the fall: missing backups, an automated failover that split writes across "
     "two coasts, a deletion script, a data center that took the ‘redundant’ control plane with it, a "
     "multi-day outage and backup generators that never started.",
     ("gitlab-database-outage-2017", "github-october-2018-incident", "atlassian-outage-2022",
      "cloudflare-control-plane-2023", "roblox-return-to-service", "google-cloud-europe-west2-power-2026"),
     ("outages", "data-integrity")),
    ("retries-overload-and-cascading-failures", "Retries, overload and cascading failures",
     "Why systems under stress make themselves worse, and the patterns that stop it: timeouts with jitter, "
     "rate limiters, tail-latency tricks, and two Slack incidents where load fed on itself.",
     ("aws-timeouts-retries-jitter", "stripe-rate-limiters", "google-tail-at-scale", "slack-outage-2021",
      "slack-incident-2-22-22", "aws-us-east-1-2021"), ("outages", "scaling-traffic")),
    ("scaling-postgres-and-mysql", "Scaling Postgres and MySQL in production",
     "How fast-growing companies kept relational databases alive: sharding, partitioning, Vitess, and one famous "
     "decision to leave Postgres, from Pinterest in 2012 to ChatGPT today.",
     ("pinterest-mysql-sharding", "notion-sharding-postgres", "figma-database-scaling", "github-partitioning-mysql",
      "slack-vitess-migration", "openai-postgres-chatgpt", "uber-postgres-to-mysql"), ("scaling-data",)),
    ("migrations-without-downtime", "Migrations without downtime",
     "Moving data and rewriting critical systems while customers keep using them: dual writes, backfills, "
     "careful cutovers and rewrites of core systems that shipped safely.",
     ("stripe-online-migrations", "stripe-docdb-zero-downtime-migrations", "notion-sharding-postgres",
      "discord-trillions-messages", "dropbox-sync-engine", "discord-go-to-rust"), ("migrations",)),
    ("monoliths-microservices-and-back", "Monoliths, microservices and back again",
     "The architecture debate told by teams who lived it: when microservices helped, when they hurt, and how "
     "Shopify, Uber, Netflix, Segment, Airbnb and Khan Academy drew their boundaries.",
     ("shopify-deconstructing-monolith", "uber-domain-microservices", "netflix-video-pipeline-microservices",
      "segment-goodbye-microservices", "airbnb-great-migration-soa", "khan-academy-goliath"), ("migrations", "dev-productivity")),
    ("real-time-at-massive-scale", "Real-time at massive scale",
     "Millions of live connections, voice calls and collaborative cursors: how WhatsApp, Discord, Figma and Meta "
     "built systems where every millisecond shows.",
     ("whatsapp-2-million-connections", "discord-elixir-5m-concurrent", "discord-webrtc-voice", "figma-multiplayer",
      "meta-threads-infrastructure", "hotstar-scaling-for-50m"), ("scaling-traffic", "performance")),
    ("security-incidents-up-close", "Security incidents up close",
     "How real attacks and vulnerabilities played out, told by the teams that handled them: a backdoor found by "
     "chance, a logging library that ran code, a stolen session cookie, a saved password, unrotated credentials and "
     "a record DDoS.",
     ("xz-utils-backdoor-2024", "cloudflare-log4j-cve-2021-44228", "circleci-security-incident-2023",
      "okta-support-system-rca-2023", "cloudflare-thanksgiving-2023", "github-ddos-2018", "cloudflare-cloudbleed",
      "letsencrypt-caa-rechecking-bug"), ("security-incidents",)),
    ("leaving-the-cloud-and-running-lean", "Leaving the cloud and running lean",
     "Teams that chose to own their hardware or simplify their systems, and what it saved: 37signals’ cloud exit, "
     "Dropbox’s own storage, Stack Overflow on a handful of servers, and Segment folding 140 services into one.",
     ("37signals-left-the-cloud", "dropbox-magic-pocket", "stack-overflow-architecture-2016",
      "segment-goodbye-microservices"), ("cost",)),
    ("recent-outages-2024-2025", "The big outages of 2024 and 2025",
     "The incidents that took down large parts of the internet recently: a telemetry rollout at OpenAI, an "
     "unflagged code path at Google Cloud, a DNS race at AWS, an oversized config file at Cloudflare and a content "
     "update at CrowdStrike.",
     ("openai-december-2024-incident", "google-cloud-service-control-2025", "aws-dynamodb-dns-2025",
      "cloudflare-outage-november-2025", "crowdstrike-falcon-pir-2024"), ("outages",)),
    ("building-ai-products-in-production", "Building AI products in production",
     "What it takes to ship LLM features people rely on: GitHub Copilot’s early prompt work, LinkedIn’s hard last "
     "20%, Uber’s text-to-SQL, and Anthropic’s patterns for agents.",
     ("github-copilot-llms", "linkedin-genai-product-musings", "uber-querygpt", "anthropic-building-effective-agents",
      "anthropic-multi-agent-research", "honeycomb-hard-stuff-llms"), ("dev-productivity",)),
    ("engineering-at-india-scale", "Engineering at India scale",
     "How Indian companies serve hundreds of millions of people: a stockbroker on plain Postgres and Redis, payments "
     "rules for UPI growth, 10 million people at an IPL toss, food delivery checks in milliseconds, and cricket "
     "streaming without autoscaling.",
     ("zerodha-scaling-common-sense", "phonepe-technology-journey", "dream11-ipl-2023-concurrency",
      "swiggy-serviceability-platform", "hotstar-scaling-for-50m", "flipkart-tidb-active-passive", "meesho-rollout-service"),
     ("scaling-traffic", "scaling-data")),
    ("making-apps-fast", "Making web and mobile apps fast",
     "Front-end and mobile engineering told by the teams who shipped it: Netflix’s 70% faster start, Pinterest’s "
     "progressive web app, Slack’s desktop rebuild, Discord’s React Native tuning and WebAssembly at Figma.",
     ("netflix-faster-website", "pinterest-pwa-retrospective", "slack-rebuilding-desktop",
      "discord-ios-react-native-performance", "figma-webassembly-load-time"), ("performance",)),
    ("cross-platform-mobile-bets", "Cross-platform mobile: the bets and the results",
     "One framework, three verdicts and a rebuild: Airbnb left React Native, Shopify went all in, Discord made it fast, "
     "and Uber rewrote its rider app for thousands of engineers.",
     ("airbnb-sunsetting-react-native", "shopify-react-native-future", "discord-ios-react-native-performance",
      "uber-rider-app-architecture"), ("migrations", "dev-productivity")),
    ("data-and-ml-platforms", "Data and machine learning platforms",
     "The infrastructure under data products: Kafka as a shared log, Netflix’s offline, nearline and online split, "
     "Uber’s Michelangelo for every team’s models, and DoorDash fitting billions of ML features in Redis.",
     ("linkedin-kafka-benchmark", "netflix-personalization-architecture", "uber-michelangelo",
      "doordash-feature-store-redis", "uber-big-data-platform"), ("scaling-data",)),
    ("observability-in-practice", "Observability in practice",
     "Knowing what is wrong and why: Google’s monitoring principles, Netflix’s lessons on logs and alerts, Slack’s "
     "queryable traces, and the storage systems Uber and Datadog built to hold it all.",
     ("google-sre-monitoring", "netflix-observability-lessons", "slack-tracing-causal-graphs", "uber-m3-metrics",
      "datadog-husky-event-store", "google-dapper"), ("outages", "performance")),
    ("security-engineering-foundations", "Security engineering foundations",
     "The defences that held: zero trust instead of a perimeter, hardware keys that defeated a working phishing "
     "attack, layered password storage, and supply chain integrity after SolarWinds.",
     ("google-beyondcorp", "cloudflare-phishing-hardware-keys", "dropbox-password-storage", "google-slsa-supply-chain",
      "xz-utils-backdoor-2024"), ("security-incidents",)),
)


def curiosity_collections():
    """Reading lists with their reviewed cards, in reading order. Static: built from seeds only."""
    result = []
    for ident, title, summary, card_ids, problems in COLLECTIONS:
        cards = [_card(deepcopy(SEEDS_BY_ID[card_id]), {}) for card_id in card_ids if card_id in SEEDS_BY_ID]
        result.append({
            "id": ident, "title": title, "summary": summary, "problems": list(problems),
            "card_ids": [card["id"] for card in cards], "cards": cards,
            "read_minutes": sum(card["read_minutes"] for card in cards),
            "companies": list(dict.fromkeys(card["company"] for card in cards)),
        })
    return result


def seed_article_ids():
    return set(SEEDS_BY_ID)


# --- Read next -----------------------------------------------------------------------------------------
RELATED_PER_CARD = 2


@lru_cache(maxsize=None)
def _seed_traits(ident):
    """Problems, themes and quality of a reviewed seed, computed once (they never change at runtime)."""
    seed = SEEDS_BY_ID[ident]
    return frozenset(card_problems(seed)), frozenset(card_themes(seed)), quality_score(seed)


@lru_cache(maxsize=None)
def _related_ids(ident):
    """Reviewed cards to read after this one: the next stop on its reading list, then the closest match."""
    seed = SEEDS_BY_ID[ident]
    chosen = []
    for _, _, _, card_ids, _ in COLLECTIONS:
        if ident in card_ids:
            index = card_ids.index(ident)
            follow = card_ids[index + 1] if index + 1 < len(card_ids) else card_ids[index - 1] if index else None
            if follow and follow in SEEDS_BY_ID and follow not in chosen:
                chosen.append(follow)
            break
    problems, themes, _ = _seed_traits(ident)
    company = seed.get("company")

    def closeness(other):
        other_problems, other_themes, _ = _seed_traits(other["id"])
        return (2 * len(problems & other_problems) + len(themes & other_themes)
                + (1 if company and other.get("company") == company else 0))

    others = [other for other in CURATED_CURIOSITY if other["id"] != ident and other["id"] not in chosen]
    others.sort(key=lambda other: other["id"])
    others.sort(key=lambda other: _seed_traits(other["id"])[2], reverse=True)
    others.sort(key=closeness, reverse=True)
    for other in others:
        if len(chosen) >= RELATED_PER_CARD or closeness(other) < 2:
            break
        chosen.append(other["id"])
    return tuple(chosen[:RELATED_PER_CARD])


def related_seeds(ident):
    return [{"id": other, "title": SEEDS_BY_ID[other]["title"], "company": SEEDS_BY_ID[other]["company"],
             "url": SEEDS_BY_ID[other]["url"]} for other in _related_ids(ident)]


# --- Lessons --------------------------------------------------------------------------------------------
# Recurring lessons, each grouping reviewed cards whose own write-ups make that point.
LESSONS = (
    ("stage-every-rollout", "Roll out every change in stages",
     "A content update, a telemetry service, a generated config file, a network change and a trading deployment each "
     "reached many machines at once. Releasing to a small slice first, and widening only after watching it, limits "
     "how far one bad change can spread.",
     ("crowdstrike-falcon-pir-2024", "openai-december-2024-incident", "cloudflare-outage-november-2025",
      "cloudflare-outage-june-2022", "knight-capital-sec-2013")),
    ("guard-new-code-paths", "Guard new code against unexpected input",
     "A blank policy field, a negative time value, a doubled config file and one regular expression: each crashed "
     "production code that had never seen that input. Feature flags, limits and error handling contain the damage.",
     ("google-cloud-service-control-2025", "cloudflare-leap-second-2017", "cloudflare-outage-november-2025",
      "cloudflare-outage-2019")),
    ("rotate-credentials-after-a-breach", "Rotate credentials after any breach, even someone else’s",
     "A stolen session, a password saved in a personal browser profile and credentials left unrotated after another "
     "company’s breach opened the door in these incidents. Treat any exposed secret or session as compromised.",
     ("cloudflare-thanksgiving-2023", "okta-support-system-rca-2023", "circleci-security-incident-2023")),
    ("test-backups-and-failover", "Test backups and failover before you need them",
     "Backups that were missing, an automatic failover that split writes, deleted sites that took days to restore, "
     "a ‘redundant’ control plane in one data center and generators that never got the signal to start: recovery only "
     "works if it has been rehearsed.",
     ("gitlab-database-outage-2017", "github-october-2018-incident", "atlassian-outage-2022",
      "cloudflare-control-plane-2023", "google-cloud-europe-west2-power-2026")),
    ("rehearse-peak-load", "Rehearse peak load before the real event",
     "Shopify and Hotstar both simulate their biggest day ahead of time, on purpose, so failures show up in a test "
     "rather than during Black Friday or a cricket final.",
     ("shopify-bfcm-scale-testing", "hotstar-scaling-for-50m")),
    ("migrate-in-small-reversible-steps", "Migrate in small, reversible steps",
     "Dual booting, dual writes, backfills and a migrations map: large moves succeed when each step ships on its "
     "own and can be checked or rolled back.",
     ("github-rails-upgrade-2018", "stripe-online-migrations", "notion-sharding-postgres", "slack-vitess-migration",
      "spotify-tech-migrations")),
    ("back-off-under-load", "Back off instead of retrying harder",
     "Retries without limits turn a slowdown into an outage. Jittered backoff, rate limits and throttling keep "
     "overloaded systems able to recover.",
     ("aws-timeouts-retries-jitter", "stripe-rate-limiters", "slack-incident-2-22-22", "aws-us-east-1-2021")),
)


def curiosity_lessons():
    result = []
    for ident, title, summary, card_ids in LESSONS:
        cards = [_card(deepcopy(SEEDS_BY_ID[card_id]), {}) for card_id in card_ids if card_id in SEEDS_BY_ID]
        result.append({"id": f"lesson-{ident}", "title": title, "summary": summary, "kind": "lesson",
                       "card_ids": [card["id"] for card in cards], "cards": cards,
                       "read_minutes": sum(card["read_minutes"] for card in cards),
                       "companies": list(dict.fromkeys(card["company"] for card in cards))})
    return result


# --- Postmortem of the week -----------------------------------------------------------------------------
WEEK_SECONDS = 7 * 86400
# Weeks counted from Monday 1970-01-05, so a new pick starts each Monday.
_FIRST_MONDAY = 4 * 86400


def weekly_postmortems():
    return sorted(ident for ident, article in SEEDS_BY_ID.items()
                  if card_format(article) == "postmortem" and article.get("breakdown"))


def postmortem_of_the_week(moment=None):
    moment = moment or datetime.now(UTC)
    candidates = weekly_postmortems()
    if not candidates:
        return None
    week = int((moment.timestamp() - _FIRST_MONDAY) // WEEK_SECONDS)
    # A fixed shuffle so consecutive weeks jump between companies rather than walking the alphabet.
    step = next(step for step in range(7, 7 + len(candidates) + 1) if gcd(step, len(candidates)) == 1)
    ident = candidates[(week * step) % len(candidates)]
    return _card(deepcopy(SEEDS_BY_ID[ident]), {})



# --- Postmortem review queue ----------------------------------------------------------------------------
# Publishers whose feeds regularly carry incident write-ups. Status pages post many short updates, so only
# items that read like a write-up (root cause, post-incident review, postmortem) are queued.
INCIDENT_SOURCES = ("cloudflare-postmortems", "cloudflare-blog", "github-availability", "github-engineering",
                    "aws-health", "google-cloud-status", "openai-status", "azure-status", "cloudflare-status",
                    "github-status", "slack-status", "atlassian-status", "vercel-status", "engineering-slack",
                    "datadog-blog", "fastly-blog", "gitlab-blog")
_write_up = re.compile(
    r"\b(?:postmortems?|post-mortems?|post[- ]incident (?:review|report|analysis)|incident reports?|root cause|"
    r"rca|what (?:went wrong|happened)|availability reports?|outage (?:on|of|report)|lessons learned)\b", re.I)


def postmortem_review_queue(store, *, days=30, limit=40):
    """Recent incident write-ups that are not yet reviewed cards, newest first, for an editor to approve.

    Reads the archive only. Nothing here is published: an approved item becomes a card only after its
    page is read and a reviewed seed is written.
    """
    if not store:
        return []
    sources = tuple(source for source in INCIDENT_SOURCES if source in BY_ID)
    rows = store.curiosity_candidates(sources, hours=days * 24, limit=600, per_source=25)
    seen, queue = list(CURATED_CURIOSITY), []
    for row in rows:
        article = restore_metadata(row)
        text = f"{article.get('title', '')} {article.get('description', '')}"
        if not _write_up.search(text) or not is_english_article(article) or _is_duplicate(article, seen):
            continue
        seen.append(article)
        source = BY_ID.get(article.get("source_id"))
        queue.append({"id": article.get("id"), "title": sanitize_text(article.get("title"), 300),
                      "url": article.get("url"), "source_id": article.get("source_id"),
                      "publisher": source.label if source else article.get("source_id"),
                      "published_at": str(article.get("published_at") or "")[:10],
                      "excerpt": sanitize_text(article.get("description"), 400),
                      "problems": card_problems(article), "score": quality_score(article)})
    queue.sort(key=lambda item: (item["published_at"], item["score"]), reverse=True)
    return queue[:limit]


# --- Server-side browsing: filters, search and facets (mirrors public/curiosity.js) ------------------------
ORIGINS = ("all", "fresh", "classic")
SORTS = ("featured", "newest")


def _card_company(card):
    return card.get("company") or card.get("publisher") or ""


def card_search_text(card):
    """Everything a reader can search on a card, lower-cased: the same fields the browser search uses."""
    breakdown = card.get("breakdown") if isinstance(card.get("breakdown"), dict) else {}
    parts = [card.get("title"), card.get("question"), _card_company(card), card.get("publisher"), LEVELS.get(card.get("level")),
             card.get("publisher_detail"), card.get("author"), card.get("summary"), card.get("why_read"),
             *(card.get("technologies") or []), *(card.get("tags") or []),
             *(THEME_LABELS.get(theme, theme) for theme in card.get("themes") or []),
             *(PROBLEM_LABELS.get(problem, problem) for problem in card.get("problems") or []), *breakdown.values()]
    return " ".join(part for part in parts if isinstance(part, str)).casefold()


def _date_key(card):
    published = str(card.get("published_at") or "")
    if re.match(r"\d{4}-\d{2}-\d{2}", published):
        return published[:10]
    return str(card.get("year") or "")


def filter_cards(cards, *, theme="all", problem="all", format="all", level="all", company="all", origin="all",
                 query="", sort="featured"):
    """Filter and order cards exactly as the collection page does, so paging never changes the result set."""
    terms = [term for term in str(query or "").casefold().split() if term]
    result = []
    for card in cards:
        if origin == "fresh" and card.get("seed") or origin == "classic" and not card.get("seed"):
            continue
        if company != "all" and _card_company(card) != company:
            continue
        if theme != "all" and theme not in (card.get("themes") or []):
            continue
        if format != "all" and card.get("format") != format:
            continue
        if level != "all" and card.get("level") != level:
            continue
        if problem != "all" and problem not in (card.get("problems") or []):
            continue
        if terms:
            text = card_search_text(card)
            if not all(term in text for term in terms):
                continue
        result.append(card)
    if sort == "newest":
        # Stable: equal dates keep the featured order.
        result = sorted(result, key=_date_key, reverse=True)
    return result


def curiosity_facets(cards):
    """Counts over the whole shelf for tabs, selects and the theme constellation."""
    themes, problems, formats, levels, companies, pairs, technologies = {}, {}, {}, {}, {}, {}, {}
    fresh = 0
    for card in cards:
        card_themes_ = list(dict.fromkeys(theme for theme in card.get("themes") or [] if theme in THEME_LABELS))
        for theme in card_themes_:
            themes[theme] = themes.get(theme, 0) + 1
        for index, first in enumerate(card_themes_):
            for second in card_themes_[index + 1:]:
                key = tuple(sorted((first, second)))
                pairs[key] = pairs.get(key, 0) + 1
        for problem in card.get("problems") or []:
            if problem in PROBLEM_LABELS:
                problems[problem] = problems.get(problem, 0) + 1
        if card.get("format") in FORMATS:
            formats[card["format"]] = formats.get(card["format"], 0) + 1
        if card.get("level") in LEVELS:
            levels[card["level"]] = levels.get(card["level"], 0) + 1
        name = _card_company(card)
        if name:
            companies[name] = companies.get(name, 0) + 1
        for label in dict.fromkeys(str(label) for label in card.get("technologies") or [] if len(str(label)) <= 24):
            technologies[label] = technologies.get(label, 0) + 1
        fresh += 0 if card.get("seed") else 1
    return {
        "total": len(cards), "fresh": fresh, "classic": len(cards) - fresh,
        "themes": themes, "problems": problems, "formats": formats, "levels": levels,
        "companies": sorted(([name, count] for name, count in companies.items()), key=lambda item: item[0].casefold()),
        "theme_pairs": [[first, second, count] for (first, second), count in sorted(pairs.items())],
        # Technologies named on at least three cards, most common first: one-tap searches.
        "technologies": [label for label, count in sorted(technologies.items(), key=lambda item: (-item[1], item[0]))
                         if count >= 3][:8],
    }
