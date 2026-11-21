"""Source-grounded engineering stories for the Curiosity Cards collection."""
from copy import deepcopy
from datetime import UTC, datetime, timedelta
import re

from app.article_language import is_english_article
from app.article_metadata import restore_metadata
from app.coverage import public_article
from app.discovery import search_text
from app.news import canonical_url
from app.sanitation import sanitize_text
from app.sources import BY_ID, DEFAULT_SOURCES


def _seed(ident, title, url, publisher, company, year, description, tags, read_minutes, source_id, *,
          authors="", publisher_detail="", read_time_basis="estimate"):
    return {
        "id": ident,
        "title": title,
        "url": url,
        "publisher": publisher,
        "company": company,
        "published_at": "",
        "year": int(year),
        "description": description,
        "summary": description,
        "summary_basis": "editorial_source_summary",
        "tags": list(tags),
        "read_minutes": read_minutes,
        "read_time_basis": read_time_basis,
        "estimated_reading_minutes": read_minutes,
        "reading_time_basis": read_time_basis,
        "source_id": source_id,
        "source": BY_ID[source_id].group,
        "kind": BY_ID[source_id].kind,
        "category": "Research" if BY_ID[source_id].kind == "research" else "Engineering",
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
)
SEEDS_BY_ID = {article["id"]: article for article in CURATED_CURIOSITY}

_technical_signals = {
    "architecture": re.compile(r"\barchitect(?:ure|ural)\b", re.I),
    "infrastructure": re.compile(r"\binfrastructure\b", re.I),
    "distributed systems": re.compile(r"\bdistributed\b|\breplication\b", re.I),
    "scaling": re.compile(r"\bscal(?:e|ed|ing|ability)\b|\bthroughput\b|\bcapacity\b", re.I),
    "reliability": re.compile(r"\breliab\w*\b|\bfault[- ]tolerant\b|\bavailability\b|\bpostmortem\b", re.I),
    "software design": re.compile(r"\bdesign(?:ed|ing)?\b|\bbuild system\b|\bmonorepo\b|\bcodebase\b", re.I),
    "data systems": re.compile(r"\bdatabase\w*\b|\bstorage\b|\bpipeline\b|\bdata movement\b", re.I),
    "performance": re.compile(r"\blatency\b|\bmemory\b|\bkernel\b|\bperformance\b|\bgpu\b", re.I),
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
    label = source.label
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
        "read_minutes": read_minutes,
        "read_time_basis": read_basis,
        "url": public["url"],
        "source_id": article["source_id"],
        "kind": source.kind if source else article.get("kind", "engineering"),
        "description": article.get("description", ""),
        "seed": bool(article.get("curiosity_seed")),
    }


MAX_CURIOSITY_CARDS = 72
# Fresh archive discoveries get a reserved share so evergreen seeds never crowd them out.
FRESH_SLOT_SHARE = 3
MAX_FRESH_CARDS = 24


def _fresh_discoveries(store, limit):
    if not store or limit <= 0:
        return []
    candidates = store.curiosity_candidates(_candidate_sources(), hours=90 * 24, limit=200)
    eligible = [restore_metadata(article) for article in candidates if is_curiosity_candidate(article)]
    # Stable tie-breaks: higher technical signal, then newer publication, then ID.
    eligible.sort(key=lambda item: str(item.get("id", "")))
    eligible.sort(key=lambda item: str(item.get("published_at", "")), reverse=True)
    eligible.sort(key=curiosity_score, reverse=True)
    # Compare against every reviewed seed, not just the ones shown, so a seed never reappears as "fresh".
    seen = list(CURATED_CURIOSITY)
    fresh = []
    for article in eligible:
        if _is_duplicate(article, seen):
            continue
        seen.append(article)
        fresh.append(article)
        if len(fresh) == limit:
            break
    return fresh


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
    selected = _interleave([deepcopy(article) for article in CURATED_CURIOSITY[:seed_count]], fresh)

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
    return [_card(article, summaries) for article in selected]


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
    by_id = {card["id"]: card for card in selected}
    return [by_id[ident] for ident in requested if ident in by_id]


def seed_article_ids():
    return set(SEEDS_BY_ID)
