"""The existing summarizer, curator, and email agent as a stateless web flow."""
import copy
import hashlib
import html
import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from app.agent.curator_agent import CuratorAgent
from app.agent.digest_agent import DigestAgent
from app.agent.email_agent import EmailDigestResponse, EmailIntroduction, RankedArticleDetail
from app.agent.openai_client import get_openai_model
from app.coverage import public_article
from app.news import canonical_url
from app.profiles.user_profile import USER_PROFILE
from app.sanitation import sanitize_text
from app.selection import words

logger = logging.getLogger(__name__)

SUMMARY_LABELS = {
    "ai_feed_summary": "AI summary of publisher feed",
    "publisher_excerpt": "Publisher excerpt",
    "headline_only": "Headline only",
}
COVERAGE_LABELS = {
    "reporting": "Independent reporting",
    "publisher": "Publisher update",
    "preprint": "Research preprint",
    "advisory": "Security advisory",
    "status": "Provider status",
    "discussion": "Community discussion",
}


def story_attribution(article):
    publisher = article.get("publisher") or article.get("sourceName") or article.get("article_type", "Source")
    region = article.get("region", "")
    status = article.get("research_status") or article.get("coverage")
    return " · ".join(part for part in (
        publisher, region if region != "Global" else "", (article.get("published_at") or "")[:10],
        COVERAGE_LABELS.get(status, ""), SUMMARY_LABELS.get(article.get("summary_basis"), ""),
    ) if part)


def safe_href(value):
    try:
        return canonical_url(value)
    except ValueError:
        return "#"

PERSONA_GUIDANCE = {
    "executive": "Connect the news to strategy, investment, ROI, and partnerships.",
    "engineer": "Explain reported architecture, benchmarks, SDK changes, and latency tradeoffs.",
    "security": "Cover reported risks, mitigations, compliance, and governance. Omit exploit instructions.",
    "product": "Focus on user impact, competitive positioning, adoption, and rollout decisions.",
}


def build_digest(articles: list[dict], name: str, focus: str, *, store=None,
                 pinned_ids: list[str] | None = None, style: str = "executive",
                 persona: str = "executive", all_pool: list[dict] | None = None, progress=None) -> dict:
    profile = copy.deepcopy(USER_PROFILE)
    profile["name"] = name
    profile["interests"] = [focus] if focus else ["Global technology news"]
    framing = PERSONA_GUIDANCE[persona]
    profile["background"] = "Technology news reader"
    profile["expertise_level"] = "Technical" if persona == "engineer" else "General"
    profile["preferences"] = {"Editorial angle": framing}

    pinned_set = set(pinned_ids or [])

    def summarize(article):
        source = public_article(article)
        excerpt = source["cleanSummary"] if source["has_excerpt"] else ""
        fallback = dict(article, summary=excerpt or "Read the publisher for details.", keyTakeaway="", whyItMatters="",
                        summary_basis="publisher_excerpt" if excerpt else "headline_only")
        if not excerpt:
            return fallback
        status = source.get("research_status")
        prompt_version = "summary-preprint-v1" if status == "preprint" else "summary-v5"
        key = hashlib.sha256(json.dumps([prompt_version, get_openai_model(), article["id"], article["title"],
                                         article["description"][:2500], style, persona], ensure_ascii=False).encode()).hexdigest()
        if store and (cached := store.get_summary(key)):
            return dict(article, **cached)

        style_instruction = {
            "executive": "Use two concise sentences on the reported change and its impact.",
            "technical": "Preserve the technical details directly reported in the excerpt.",
            "skim": "Use one concise sentence that explains the reported change.",
        }.get(style, "Provide a concise 2-sentence editorial summary.")

        research_instruction = (" Describe preprint findings as the authors' claims. Avoid implying peer review."
                                if status == "preprint" else "")
        result = DigestAgent().generate_digest(
            article["title"],
            f"Summarize the supplied title and feed excerpt. For security news, describe impact and defenses and omit exploit steps. "
            f"{style_instruction} {framing}{research_instruction}\n"
            + json.dumps({"title": article["title"], "excerpt": article["description"][:2500]}),
            article["source"],
        )
        summary = sanitize_text(result.summary, 900) if result else ""
        if not summary:
            return dict(fallback, synthesis_failed=True)

        saved = {
            "summary": summary,
            "whyItMatters": sanitize_text(result.whyItMatters, 300),
            "keyTakeaway": sanitize_text(result.keyTakeaway, 300),
            "summary_basis": "ai_feed_summary",
        }
        if store:
            store.save_summary(key, saved)
        return dict(article, **saved)

    if progress:
        progress(2)
    with ThreadPoolExecutor(max_workers=5) as pool:
        summaries = list(pool.map(summarize, articles))
    candidates = [dict(a, article_type=a["source"]) for a in summaries]
    unpinned = [row for row in candidates if row["id"] not in pinned_set]
    provider_down = all(item.get("synthesis_failed") or item["summary_basis"] == "headline_only" for item in summaries)
    ranked = CuratorAgent(profile).rank_digests(unpinned) if len(unpinned) > 1 and not provider_down else []
    ranking_failed = len(unpinned) > 1 and not provider_down and not ranked
    ranks = {row.digest_id: row for row in ranked}
    by_id = {a["id"]: a for a in summaries}
    order = list(pinned_ids or []) + ([row.digest_id for row in ranked] if ranked else [row["id"] for row in unpinned])

    details = []
    for rank_idx, ident in enumerate(order, start=1):
        item = by_id[ident]
        rank = ranks.get(ident)
        source = public_article(item)
        details.append(RankedArticleDetail(
            digest_id=ident,
            rank=rank_idx,
            relevance_score=rank.relevance_score if rank else (10.0 if ident in pinned_set else None),
            title=item["title"],
            summary=item["summary"],
            url=item["url"],
            article_type=item["source"],
            reasoning=sanitize_text(rank.reasoning, 300) if rank else None,
            publisher=item.get("publisher", ""),
            topic=source["topic"],
            topic_label=source["topic_label"],
            coverage=source["coverage"],
            region=source["region"],
            region_id=source["region_id"],
            language=source["language"],
            research_status=source.get("research_status"),
            published_at=item.get("published_at", ""),
            whyItMatters=item.get("whyItMatters", ""),
            keyTakeaway=item.get("keyTakeaway", ""),
            summary_basis=item["summary_basis"],
        ))

    # Prefer distinct publisher regions and skip near-duplicates of selected stories.
    used = set(order)
    titles = [words(by_id[ident]["title"]) for ident in order]
    quick_candidates = []
    quick_regions = set()
    recent_pool = sorted(all_pool or [], key=lambda article: (article["published_at"], article["id"]), reverse=True)
    for unique_region in (True, False):
        for item in recent_pool:
            if len(quick_candidates) == 3:
                break
            if item["id"] in used:
                continue
            article = public_article(item)
            if unique_region and article["region_id"] in quick_regions:
                continue
            tokens = words(article["title"])
            if any(tokens and old and len(tokens & old) / len(tokens | old) >= .72 for old in titles):
                continue
            quick_candidates.append(article)
            quick_regions.add(article["region_id"])
            titles.append(tokens)
            used.add(article["id"])
    quick_hits = [
        {
            "title": q["title"],
            "url": q["url"],
            "publisher": q.get("publisher", ""),
            "region": q.get("region", "Global"),
            "region_id": q["region_id"],
            "topic": q["topic"],
        }
        for q in quick_candidates
    ]

    if progress:
        progress(3)
    topic_labels = list(dict.fromkeys(article.topic_label for article in details))[:3]
    digest = EmailDigestResponse(
        introduction=EmailIntroduction(greeting=f"Your tech brief, {name}",
                                       introduction=f"In this edition: {', '.join(topic_labels)}."),
        articles=details, total_ranked=len(details), top_n=len(details),
    )
    result = digest.model_dump()
    result["generated_at"] = datetime.now(timezone.utc).isoformat()
    result["quick_hits"] = quick_hits
    result["style"] = style
    result["persona"] = persona
    result["synthesis"] = {
        "degraded": ranking_failed or any(item.get("synthesis_failed") for item in summaries),
        "ranking": "ai" if ranked else "selection_order",
        "ai_summaries": sum(item["summary_basis"] == "ai_feed_summary" for item in summaries),
    }
    if result["synthesis"]["degraded"]:
        logger.info("brief_synthesis_degraded stories=%d ai_summaries=%d ranking_failed=%s",
                    len(details), result["synthesis"]["ai_summaries"], ranking_failed)

    # Compose rich markdown
    md_lines = [f"# {digest.introduction.greeting}\n", f"{digest.introduction.introduction}\n\n---"]
    for art in details:
        attribution = story_attribution(art.model_dump())
        md_lines.append(f"## {art.rank}. {art.title}\n{art.topic_label or 'Tech'} · {attribution}\n\n{art.summary}\n")
        if art.keyTakeaway:
            md_lines.append(f"* **Key Takeaway:** {art.keyTakeaway}\n")
        elif art.whyItMatters:
            md_lines.append(f"* **Why It Matters:** {art.whyItMatters}\n")
        md_lines.append(f"Source: {safe_href(art.url)}\n\n---")

    if quick_hits:
        md_lines.append("### Quick Hits Around the World")
        for qh in quick_hits:
            md_lines.append(f"- {qh['title']} · {qh['publisher']} ({qh['region']}) · <{safe_href(qh['url'])}>")

    result["markdown"] = "\n\n".join(md_lines)
    result["html"] = safe_email_html(result)
    return result


def safe_email_html(digest: dict, unsubscribe_url: str | None = None) -> str:
    escape = html.escape
    intro = digest.get("introduction", {})
    greeting = escape(intro.get("greeting", "Your Informa AI"))
    overview = escape(intro.get("introduction", "The technology stories that matter, curated for your morning read."))
    origin = escape(safe_href(os.getenv("PUBLIC_ORIGIN", "https://ai-news-to-email-generator.vercel.app")).rstrip("/"), quote=True)
    unsubscribe = f'<a href="{escape(safe_href(unsubscribe_url), quote=True)}">Unsubscribe</a> · ' if unsubscribe_url else ""

    article_cards = []
    articles = digest.get("articles", [])
    for article in articles:
        title = escape(article.get("title", ""))
        url = escape(safe_href(article.get("url")), quote=True)
        summary = escape(article.get("summary", ""))
        topic_label = escape(article.get("topic_label") or article.get("category", "Technology"))
        takeaway = escape(article.get("keyTakeaway") or article.get("whyItMatters") or "")
        attribution = escape(story_attribution(article))
        language = escape(article.get("language") or "en", quote=True)

        card_html = f"""
        <table class="email-card" role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:24px;border:1px solid #dedfd5;border-radius:8px;background-color:#ffffff;padding:20px;">
          <tr>
            <td>
              <div style="font-size:10px;font-weight:700;letter-spacing:1px;text-transform:uppercase;color:#697169;margin-bottom:8px;">
                <span style="background-color:#e8eddf;color:#294a3b;padding:3px 7px;border-radius:3px;">{topic_label}</span>
                <span style="margin-left:8px;">{attribution}</span>
              </div>
              <h2 class="email-heading" lang="{language}" style="font-family:Georgia,serif;font-size:19px;line-height:1.3;margin:8px 0 10px;color:#252e29;">
                <a class="email-link" href="{url}" style="color:#252e29;text-decoration:none;">{title}</a>
              </h2>
              <p class="email-text" style="font-size:13px;line-height:1.6;color:#4a534e;margin:0 0 12px;">{summary}</p>
              """
        if takeaway:
            card_html += f"""
              <div class="takeaway-box" style="font-size:12px;line-height:1.5;color:#294a3b;background-color:#f4f6f0;border-left:3px solid #294a3b;padding:8px 12px;margin-bottom:12px;border-radius:0 4px 4px 0;">
                <strong>Key Takeaway:</strong> {takeaway}
              </div>
            """
        card_html += f"""
              <div>
                <a href="{url}" style="font-size:11px;font-weight:600;color:#294a3b;text-decoration:none;">Read original source →</a>
              </div>
            </td>
          </tr>
        </table>
        """
        article_cards.append(card_html)

    # Quick hits
    quick_hits_html = ""
    quick_hits = digest.get("quick_hits", [])
    if quick_hits:
        quick_hits_items = []
        for qh in quick_hits:
            q_title = escape(qh.get("title", ""))
            q_url = escape(safe_href(qh.get("url")), quote=True)
            q_pub = escape(qh.get("publisher", "Source"))
            q_reg = escape(qh.get("region", "Global"))
            quick_hits_items.append(
                f'<li style="margin-bottom:8px;font-size:12px;line-height:1.5;">'
                f'<a href="{q_url}" style="color:#252e29;text-decoration:underline;">{q_title}</a> '
                f'<span style="color:#697169;">— {q_pub} ({q_reg})</span></li>'
            )
        quick_hits_html = f"""
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin-top:28px;margin-bottom:28px;border-top:2px solid #dedfd5;padding-top:20px;">
          <tr>
            <td>
              <h3 style="font-family:Georgia,serif;font-size:16px;color:#252e29;margin:0 0 12px;">Quick Hits Around the World</h3>
              <ul style="padding-left:18px;margin:0;color:#4a534e;">
                {"".join(quick_hits_items)}
              </ul>
            </td>
          </tr>
        </table>
        """

    full_html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta name="color-scheme" content="light dark">
  <style>
    :root {{ color-scheme: light dark; supported-color-schemes: light dark; }}
    @media (prefers-color-scheme: dark) {{
      body, .email-bg {{ background-color: #1a1e1b !important; color: #e1e4dc !important; }}
      .email-card {{ background-color: #242925 !important; border-color: #38403a !important; }}
      .email-text {{ color: #c8ccc4 !important; }}
      .email-heading {{ color: #f0f2eb !important; }}
      .email-link {{ color: #8fa879 !important; }}
      .takeaway-box {{ background-color: #2d3630 !important; border-color: #8fa879 !important; color: #d6e2cb !important; }}
    }}
  </style>
</head>
<body style="margin:0;padding:24px 12px;background-color:#f6f4ee;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;color:#252e29;line-height:1.6;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
    <tr>
      <td align="center">
        <!-- 600px Max-Width Single Column Container -->
        <table role="presentation" width="100%" style="max-width:600px;text-align:left;" cellpadding="0" cellspacing="0">
          <!-- Header Branding -->
          <tr>
            <td style="padding-bottom:24px;border-bottom:1px solid #dedfd5;">
              <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
                <tr>
                  <td>
                    <span style="font-family:Georgia,serif;font-size:24px;font-weight:bold;color:#1e352b;letter-spacing:-0.5px;">Informa AI</span>
                    <div style="font-size:10px;letter-spacing:1px;text-transform:uppercase;color:#4f5a52;margin-top:3px;font-weight:600;">Your Personal AI News Intelligence Agent</div>
                    <div style="font-size:9px;letter-spacing:0.8px;color:#7c877e;margin-top:2px;">Discover · Analyze · Personalize · Automate</div>
                  </td>
                  <td align="right" style="vertical-align:top;">
                    <span style="display:inline-block;height:8px;width:8px;background-color:#10b981;border-radius:50%;margin-right:4px;"></span>
                    <span style="font-size:10px;color:#4f5a52;font-weight:700;letter-spacing:0.5px;">INTELLIGENCE DOSSIER</span>
                  </td>
                </tr>
              </table>
            </td>
          </tr>

          <!-- Intro & Macro Synthesis -->
          <tr>
            <td style="padding:24px 0 16px;">
              <p style="font-family:Georgia,serif;font-size:19px;line-height:1.35;margin:0 0 10px;color:#252e29;">{greeting}</p>
              <p style="font-size:13px;line-height:1.65;color:#5a625a;margin:0;">{overview}</p>
            </td>
          </tr>

          <!-- Story Cards -->
          <tr>
            <td>
              {"".join(article_cards)}
            </td>
          </tr>

          <!-- Quick Hits -->
          <tr>
            <td>
              {quick_hits_html}
            </td>
          </tr>

          <!-- Footer with CAN-SPAM Compliance & 1-Click Unsubscribe -->
          <tr>
            <td style="padding-top:24px;border-top:1px solid #dedfd5;font-size:11px;line-height:1.6;color:#80867f;text-align:center;">
              <p style="margin:0 0 8px;">
                You received this email on-demand from <a href="{origin}" style="color:#294a3b;text-decoration:none;font-weight:600;">Informa AI</a>.
              </p>
              <p style="margin:0 0 8px;">
                {unsubscribe}
                <a href="{origin}/sources.html" style="color:#697169;text-decoration:underline;">Source Directory</a> · 
                <a href="{origin}" style="color:#697169;text-decoration:underline;">Web Edition</a>
              </p>
              <p style="margin:0;font-size:11px;font-weight:600;color:#4f5a52;">
                Informa AI · Discover · Analyze · Personalize · Automate
              </p>
              <p style="margin:4px 0 0;font-size:10px;color:#7c877e;font-style:italic;">
                Discover what matters. Understand why it matters. Stay ahead without information overload.
              </p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""
    return full_html
