"""The existing summarizer, curator, and email agent as a stateless web flow."""
import copy
import hashlib
import html
import json
import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from app.agent.curator_agent import CuratorAgent
from app.agent.digest_agent import DigestAgent
from app.agent.email_agent import EmailDigestResponse, EmailIntroduction, RankedArticleDetail
from app.agent.openai_client import get_openai_model, route_model
from app.brand import BRIEF_SUBJECT, HEADLINE, NAME, PILLARS, PUBLIC_SITE, TAGLINE
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
    "ai_evidence_explanation": "AI explanation of publisher evidence",
}
COVERAGE_LABELS = {
    "reporting": "Independent reporting",
    "publisher": "Publisher update",
    "preprint": "Research preprint",
    "journal": "Research journal",
    "advisory": "Security advisory",
    "status": "Provider status",
    "discussion": "Community discussion",
    "article": "Article or tutorial",
    "release": "Official release notes",
}


def story_attribution(article):
    publisher = article.get("publisher") or article.get("sourceName") or article.get("article_type", "Source")
    region = article.get("region", "")
    status = article.get("research_status") or article.get("coverage")
    return " · ".join(part for part in (
        publisher, article.get("author"), region if region != "Global" else "", (article.get("published_at") or "")[:10],
        COVERAGE_LABELS.get(status, ""), SUMMARY_LABELS.get(article.get("summary_basis"), ""),
    ) if part)


def safe_href(value):
    try:
        return canonical_url(value)
    except ValueError:
        return "#"


def public_site():
    url = safe_href(os.getenv("PUBLIC_ORIGIN", PUBLIC_SITE))
    return PUBLIC_SITE if url == "#" else url.rstrip("/")


MARKDOWN_LITERAL = re.compile(r"([\\\x60\[\]*_!<>~|])")


def markdown_text(value):
    return MARKDOWN_LITERAL.sub(r"\\\1", " ".join(str(value or "").split()))


def markdown_link(value):
    url = safe_href(value)
    return "" if url == "#" else "<" + url.replace("<", "%3C").replace(">", "%3E") + ">"


def change_label(item):
    notice = {"correction": "Publisher correction", "retraction": "Publisher retraction"}.get(item.get("editorial_notice"))
    return " · ".join(part for part in (notice or item.get("change_label"), item["title"], item["publisher"]) if part)


def brief_evidence(article):
    if claims := article.get("claim_evidence"):
        return claims
    if article.get("summary_basis") == "ai_feed_summary" and article.get("publisher_excerpt"):
        return [{**article, "excerpt": article["publisher_excerpt"]}]
    return []


def development_url(article):
    ident = article.get("development_id", "")
    return f"{public_site()}/development.html?id={ident}" if re.fullmatch(r"[a-f0-9]{32}", ident) else ""


def evidence_label(item):
    return " · ".join(part for part in (item.get("publisher") or "Original source",
        COVERAGE_LABELS.get(item.get("coverage"), ""), (item.get("published_at") or "")[:10]) if part)


def digest_markdown(digest):
    intro = digest["introduction"]
    lines = [f"# {NAME}", markdown_text(intro.get("greeting")), markdown_text(intro.get("introduction"))]
    for article in digest["articles"]:
        detail = " · ".join(part for part in (article.get("topic_label"), story_attribution(article)) if part)
        lines.extend([
            f"## {article['rank']}. {markdown_text(article.get('title'))}",
            markdown_text(detail),
            markdown_text(article.get("summary")),
        ])
        if takeaway := article.get("keyTakeaway"):
            lines.append(f"**Key takeaway.** {markdown_text(takeaway)}")
        if impact := article.get("whyItMatters"):
            if impact != article.get("keyTakeaway"):
                lines.append(f"**Why it matters.** {markdown_text(impact)}")
        if source := markdown_link(article.get("url")):
            lines.append(f"Source: {source}")
        if development := development_url(article):
            lines.append(f"Follow the development: {markdown_link(development)}")
        for item in brief_evidence(article):
            lines.append(f"**Publisher evidence** · {markdown_text(evidence_label(item))} {markdown_link(item.get('url'))}"
                         f"\n> {markdown_text(item.get('excerpt'))}")
        if changes := article.get("change_sources"):
            lines.append("**New since your last brief**\n" + "\n".join(
                f"- {markdown_text(change_label(item))} {markdown_link(item['url'])}\n  {markdown_text(item.get('excerpt'))}"
                for item in changes))

    if quick_hits := digest.get("quick_hits"):
        lines.append("### Quick hits")
        hits = []
        for item in quick_hits:
            detail = " · ".join(part for part in (item.get("title"), item.get("publisher"), item.get("region")) if part)
            hits.append(f"- {markdown_text(detail)} {markdown_link(item.get('url'))}".rstrip())
        lines.append("\n".join(hits))
    if digest.get("edition") == "catchup":
        lines.append(f"Manage or mute follows: {public_site()}/research.html#radar-title")
    return "\n\n".join(filter(None, lines))


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
        key = hashlib.sha256(json.dumps([prompt_version, route_model("digest"), article["id"], article["title"],
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
            author=source.get("author", ""),
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
            publisher_excerpt=(source["cleanSummary"][:650] if item["summary_basis"] == "ai_feed_summary"
                               and source["has_excerpt"] else ""),
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
                                       introduction=f"This brief covers {', '.join(topic_labels)}."),
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

    result["markdown"] = digest_markdown(result)
    result["html"] = safe_email_html(result)
    return result


def safe_email_html(digest: dict, unsubscribe_url: str | None = None, *, scheduled: bool = False) -> str:
    escape = html.escape
    intro = digest.get("introduction", {})
    greeting = escape(intro.get("greeting", "Your technology brief"))
    overview = escape(intro.get("introduction", "Follow the source links for details."))
    origin = escape(public_site(), quote=True)
    unsubscribe_href = safe_href(unsubscribe_url)
    unsubscribe = (
        f'<a class="email-link" href="{escape(unsubscribe_href, quote=True)}" style="color:#375e48;">Unsubscribe</a> · '
        if unsubscribe_href != "#" else ""
    )

    article_cards = []
    articles = digest.get("articles", [])
    for article in articles:
        title = escape(article.get("title", ""))
        url = escape(safe_href(article.get("url")), quote=True)
        summary = escape(article.get("summary", ""))
        topic_label = escape(article.get("topic_label") or article.get("category", "Technology"))
        attribution = escape(story_attribution(article))
        language = escape(article.get("language") or "en", quote=True)
        heading_link = (
            f'<a class="email-link" href="{url}" style="color:#252e29;text-decoration:none;">{title}</a>'
            if url != "#" else title
        )

        card_html = f"""
        <table class="email-card" role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:18px;border:1px solid #d9e1db;border-radius:8px;background-color:#ffffff;">
          <tr>
            <td style="padding:18px;">
              <div class="email-text" style="font-size:12px;font-weight:600;color:#506158;margin-bottom:8px;">
                <span style="background-color:#e8eddf;color:#294a3b;padding:3px 7px;border-radius:3px;">{topic_label}</span>
                <span style="margin-left:8px;">{attribution}</span>
              </div>
              <h2 class="email-heading" lang="{language}" style="font-family:Georgia,serif;font-size:19px;line-height:1.3;margin:8px 0 10px;color:#252e29;">
                {heading_link}
              </h2>
              <p class="email-text" style="font-size:13px;line-height:1.6;color:#4a534e;margin:0 0 12px;">{summary}</p>
              """
        insights = (("Key takeaway", article.get("keyTakeaway")), ("Why it matters", article.get("whyItMatters")))
        for heading, insight in insights:
            if not insight or (heading == "Why it matters" and insight == article.get("keyTakeaway")):
                continue
            card_html += f"""
              <div class="takeaway-box" style="font-size:12px;line-height:1.5;color:#294a3b;background-color:#f4f6f0;border-left:3px solid #294a3b;padding:8px 12px;margin-bottom:12px;border-radius:0 4px 4px 0;">
                <strong>{heading}.</strong> {escape(insight)}
              </div>
            """
        if changes := article.get("change_sources"):
            change_items = []
            for item in changes:
                href = escape(safe_href(item["url"]), quote=True)
                label = escape(change_label(item))
                excerpt = escape(item.get("excerpt") or "")
                change_items.append(f'<li><a class="email-link" href="{href}">{label}</a><br>{excerpt}</li>')
            card_html += '<div class="email-text"><strong>New since your last brief</strong><ul>' + "".join(change_items) + '</ul></div>'
        for item in brief_evidence(article):
            href = escape(safe_href(item.get("url")), quote=True)
            label = escape(evidence_label(item))
            excerpt = escape(item.get("excerpt") or "")
            card_html += (f'<div class="email-text" style="font-size:12px;margin-bottom:12px;">'
                          f'<strong>Publisher evidence</strong> · <a class="email-link" href="{href}">{label}</a>'
                          f'<blockquote style="margin:6px 0 0 0;">{excerpt}</blockquote></div>')
        if development := development_url(article):
            card_html += (f'<p><a class="email-link" href="{escape(development, quote=True)}">'
                          "Open the development timeline →</a></p>")
        if url != "#":
            card_html += f"""
              <div>
                <a class="email-link" href="{url}" style="font-size:12px;font-weight:600;color:#294a3b;text-decoration:none;">Read original source →</a>
              </div>
            """
        card_html += """
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
            q_label = (
                f'<a class="email-link" href="{q_url}" style="color:#252e29;text-decoration:underline;">{q_title}</a>'
                if q_url != "#" else q_title
            )
            quick_hits_items.append(
                f'<li style="margin-bottom:8px;font-size:12px;line-height:1.5;">'
                f'{q_label} '
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
  <title>{BRIEF_SUBJECT}</title>
  <meta name="color-scheme" content="light dark">
  <style>
    :root {{ color-scheme: light dark; supported-color-schemes: light dark; }}
    @media (prefers-color-scheme: dark) {{
      body, .email-bg {{ background-color: #101916 !important; color: #e6eee9 !important; }}
      .email-card {{ background-color: #18241f !important; border-color: #344941 !important; }}
      .email-text {{ color: #c3d2c9 !important; }}
      .email-heading {{ color: #eef5f1 !important; }}
      .email-link {{ color: #a3ddbb !important; }}
      .takeaway-box {{ background-color: #243c30 !important; border-color: #8dcfab !important; color: #ddf2e5 !important; }}
    }}
  </style>
</head>
<body style="margin:0;padding:24px 12px;background-color:#f3f6f4;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;color:#172721;line-height:1.6;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
    <tr>
      <td align="center">
        <!-- 600px Max-Width Single Column Container -->
        <table role="presentation" width="100%" style="max-width:600px;text-align:left;" cellpadding="0" cellspacing="0">
          <tr>
            <td style="padding-bottom:18px;border-bottom:1px solid #d9e1db;">
              <p class="email-heading" style="font-family:Georgia,serif;font-size:24px;font-weight:bold;color:#193f2d;letter-spacing:-0.5px;margin:0;">{NAME}</p>
              <p class="email-heading" style="font-size:14px;font-weight:650;margin:3px 0;color:#193f2d;">{HEADLINE}</p>
              <p class="email-text" style="font-size:13px;margin:4px 0;color:#506158;">{TAGLINE}</p>
              <p class="email-text" style="font-size:12px;margin:8px 0 0;color:#506158;">{PILLARS}</p>
            </td>
          </tr>

          <tr>
            <td style="padding:20px 0 17px;">
              <h1 class="email-heading" style="font-family:Georgia,serif;font-weight:normal;font-size:22px;line-height:1.35;margin:0 0 8px;color:#172721;">{greeting}</h1>
              <p class="email-text" style="font-size:14px;line-height:1.65;color:#506158;margin:0;white-space:pre-line;">{overview}</p>
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

          <tr>
            <td class="email-text" style="padding-top:16px;border-top:1px solid #d9e1db;font-size:12px;line-height:1.6;color:#506158;text-align:center;">
              {"<p style='margin:0 0 6px;'>You opted into morning updates from your follows.</p>" if scheduled and digest.get("followed_updates") else
               "<p style='margin:0 0 6px;'>You subscribed to the daily technology brief.</p>" if scheduled else ""}
              <p style="margin:0;">
                {unsubscribe}
                {f'<a class="email-link" href="{origin}/research.html#radar-title">Manage or mute follows</a> · ' if digest.get("edition") == "catchup" else ""}
                <a class="email-link" href="{origin}/sources.html" style="color:#375e48;text-decoration:underline;">Source directory</a> ·
                <a class="email-link" href="{origin}" style="color:#375e48;text-decoration:underline;">Web edition</a>
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
