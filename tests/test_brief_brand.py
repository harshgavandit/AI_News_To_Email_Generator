from datetime import UTC, datetime
from unittest.mock import Mock

from bs4 import BeautifulSoup
from markdown import markdown

from app.agent import email_agent
from app.agent.email_agent import EmailDigestResponse, EmailIntroduction, RankedArticleDetail
from app.brand import BRIEF_SUBJECT, HEADLINE, NAME, PILLARS, TAGLINE
from app.mail_schedule import with_unsubscribe
from app.services.email import digest_to_html
from app.web_digest import digest_markdown, safe_email_html
from app.workspace_delivery import message_payload
from app.world_edition import build_world


def test_legacy_newsletter_uses_the_shared_escaped_brand_template():
    brief = EmailDigestResponse(
        introduction=EmailIntroduction(greeting="<img src=x>", introduction="Brief overview."),
        articles=[RankedArticleDetail(
            digest_id="id", rank=1, relevance_score=None, title="[Untrusted link](javascript:alert(1))",
            summary="<script>bad()</script>", url="javascript:alert(1)", article_type="News",
        )],
        total_ranked=1,
        top_n=1,
    )
    page = digest_to_html(brief)
    assert page == safe_email_html(brief.model_dump())
    assert f"<title>{BRIEF_SUBJECT}</title>" in page
    assert page.count(HEADLINE) == page.count(TAGLINE) == page.count(PILLARS) == 1
    assert page.count(NAME) == 2  # Title and header.
    assert "INTELLIGENCE DOSSIER" not in page
    assert "<script" not in page and "<img" not in page and 'href="javascript:' not in page

    exported = BeautifulSoup(markdown(brief.to_markdown()), "html.parser")
    assert exported.find("script") is None and exported.find("img") is None
    assert exported.find("a") is None


def test_summary_basis_and_distinct_insights_carry_into_exports():
    article = {
        "rank": 1, "title": "A documented change", "summary": "The publisher announced a change.",
        "publisher": "Source", "url": "https://example.com/story",
        "topic_label": "Software & Cloud", "coverage": "reporting", "summary_basis": "ai_feed_summary",
        "keyTakeaway": "A new version is available.",
        "whyItMatters": "Existing integrations use the revised API.",
    }
    brief = {"introduction": {"greeting": "Your brief", "introduction": "Software update."}, "articles": [article]}
    for rendered in (safe_email_html(brief), digest_markdown(brief)):
        assert "Independent reporting" in rendered
        assert "AI summary of publisher feed" in rendered
        assert "Key takeaway." in rendered and "Why it matters." in rendered
        assert "https://example.com/story" in rendered
    slack = message_payload(brief, "slack")
    assert slack["text"] == BRIEF_SUBJECT
    assert "AI summary of publisher feed" in slack["blocks"][2]["text"]["text"]


def test_scheduled_email_places_unsubscribe_in_the_shared_footer(monkeypatch):
    monkeypatch.setenv("PUBLIC_ORIGIN", "https://brief.example.org")
    brief = {"introduction": {"greeting": "Your global technology brief"}, "articles": []}
    brief.update(markdown=digest_markdown(brief), html=safe_email_html(brief))
    url = "https://brief.example.org/api/mail/unsubscribe/abc"
    scheduled = with_unsubscribe(brief, url, scheduled=True)
    immediate = with_unsubscribe(brief, url)
    assert "You subscribed to the daily technology brief." in scheduled["html"]
    assert "You subscribed to the daily technology brief." not in immediate["html"]
    for rendered in (scheduled, immediate):
        assert rendered["html"].count(url) == 1 and rendered["markdown"].count(url) == 1
        assert "https://brief.example.org/sources.html" in rendered["html"]


def test_global_edition_explains_pins_and_excludes_unusable_excerpts():
    headline = {
        "id": "news", "title": "A story without an excerpt", "description": "Unusable feed description",
        "has_excerpt": False, "source": "bbc-tech", "publisher": "BBC Technology", "topic": "industry",
        "url": "https://example.com/story", "published_at": datetime.now(UTC).isoformat(),
        "coverage": "reporting", "region": "Global", "region_id": "Global", "language": "en",
    }
    brief = build_world([headline], 24, scope=("Industry & Policy",), includes_pins=True)
    assert "Pinned stories may be outside these filters." in brief["introduction"]["introduction"]
    assert brief["articles"][0]["summary_basis"] == "headline_only"
    assert "Unusable feed description" not in brief["html"]
    assert "Headline only" in brief["html"] and "AI summary" not in brief["html"]


def test_invalid_legacy_overview_has_a_grounded_fallback(monkeypatch):
    complete = Mock(return_value="Not valid structured output.")
    monkeypatch.setattr(email_agent, "generate_response", complete)
    intro = email_agent.EmailAgent({"name": "Reader"}).generate_introduction([
        {"title": "Story", "summary": "Publisher summary."},
    ])
    assert intro.greeting.startswith("Your technology brief for")
    assert "Follow the source links" in intro.introduction
    assert "Not valid" not in intro.introduction
    complete.assert_called_once()
