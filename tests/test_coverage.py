from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

import pytest

from app.coverage import REGION_LABELS, article_source, public_article, region_matches, topic_for
from app.sources import BY_ID
from app.web_digest import build_digest
from app.world_edition import build_world, select_world


def story(ident, source_id, title, *, minutes=5, description="Read the publisher's excerpt."):
    source = BY_ID[source_id]
    return {
        "id": ident,
        "source_id": source_id,
        "source": source.group,
        "kind": source.kind,
        "publisher": source.label,
        "title": title,
        "url": f"https://example.com/{ident}",
        "description": description,
        "published_at": (datetime.now(UTC) - timedelta(minutes=minutes)).isoformat(),
        "category": "News",
    }


@pytest.mark.parametrize(
    ("publisher", "title", "category", "topic"),
    [
        ("techcrunch", "Browser company fixes zero‑day flaw", "Technology", "security"),
        ("the-verge", "Start-up closes its Series A", "Business", "startups"),
        ("bbc-tech", "Publishers distrust agents who inflate traffic", "News", "industry"),
        ("tecnoblog", "Inteligência artificial chega às escolas", "Tecnologia", "ai"),
        ("heise-online", "Sicherheitslücke in Web-Apps", "News", "security"),
        ("xataka-mx", "Nuevos procesadores para portátiles", "Tecnología", "chips"),
        ("ars-technica", "Microsoft appoints a new CEO", "Technology", "bigtech"),
        ("bbc-tech", "The AI Act enters its next phase", "Technology", "industry"),
        ("the-verge", "Linux gains a new open-source runtime", "Technology", "software"),
        ("bbc-tech", "Scientists discover a faster quantum networking method", "News", "research"),
        ("arxiv-ai", "Layer-aware language models in domain adaptation", "AI", "research"),
        ("cloudflare-status", "Traffic delayed in Chicago", "Status", "outages"),
        ("bbc-tech", "EU ties to US suppliers face a setback", "News | Tech Policy", "industry"),
        ("bbc-tech", "Follow these new settings", "News | Cybersecurity", "security"),
    ],
)
def test_topic_hierarchy_and_word_boundaries(publisher, title, category, topic):
    article = dict(story("classification", publisher, title), category=category, topic="video")
    assert topic_for(article) == topic
    article.pop("topic")
    assert public_article(article)["topic"] == topic


def test_security_and_research_feed_provenance():
    row = story("advisory", "cert-eu", "A vendor fixes a security flaw",
                description="<script>do_not_publish()</script><p>Install the vendor's available patch.</p>")
    article = public_article(dict(row, search_title="archive detail", topic_rank=4))
    assert article["coverage"] == "advisory"
    assert article["has_excerpt"] is True
    assert article["cleanSummary"] == "Install the vendor's available patch."
    assert article["region_id"] == "EU"
    assert "search_title" not in article and "topic_rank" not in article

    report = public_article(story("preprint", "arxiv-ai", "Source attribution in long-context models"))
    assert report["research_status"] == "preprint" and report["coverage"] == "preprint"


def test_publisher_regions_keep_the_region_code_and_original_name():
    mena = story("mena", "entarabi", "A regional startup raises funding")
    france = story("europe", "heise-online", "Changes to browser settings")
    assert REGION_LABELS["MENA"] == "Middle East & North Africa"
    assert region_matches(mena, "MENA") and not region_matches(mena, "Africa")
    assert public_article(mena)["region"] == "Middle East & North Africa"
    assert article_source(france).language == "de"
    assert public_article(france)["language"] == "en"
    assert public_article(france)["region_id"] == "EU"


def test_world_digest_diversifies_stories_and_eligible_quick_hits():
    rows = [
        story("lead", "bbc-tech", "OpenAI expands access to its latest ChatGPT model"),
        story("duplicate", "the-verge", "OpenAI expands access to the latest ChatGPT model", minutes=8),
        story("mena", "entarabi", "Regional startup launches a digital payments network", minutes=20),
        story("eu", "heise-online", "Sicherheitslücke in Web-Apps", minutes=24),
        story("na", "betakit", "Manufacturers plan a semiconductor facility", minutes=29),
        story("research", "arxiv-ai", "Results from an adaptive networking protocol", minutes=34),
    ]
    selected = select_world(rows, 3, [item["source_id"] for item in rows])
    assert [item["id"] for item in selected] == ["lead", "mena", "eu"]
    digest = build_world(selected, 24, all_pool=rows, scope=("Research & Science",))
    assert len(digest["quick_hits"]) == 2
    assert {item["topic"] for item in digest["quick_hits"]} == {"chips", "research"}
    assert all("duplicate" not in item["url"] for item in digest["quick_hits"])
    assert "Research & Science" in digest["markdown"] and "Research &amp; Science" in digest["html"]
    assert "Cybersecurity &amp; Privacy" in digest["html"]


def test_personalized_preprint_summary_and_exports_show_provenance(monkeypatch):
    from app.web_digest import DigestAgent

    failed_model = Mock(return_value=None)
    monkeypatch.setattr(DigestAgent, "generate_digest", failed_model)
    row = story("research", "arxiv-ai", "Adaptive networking protocol results")
    digest = build_digest([row], "Reader", "Computer networks")
    article = digest["articles"][0]
    assert article["research_status"] == "preprint"
    assert article["region_id"] == "Global"
    assert article["summary_basis"] == "publisher_excerpt"
    assert "Avoid implying peer review" in failed_model.call_args.args[1]
    assert "Research preprint" in digest["markdown"] and "Research preprint" in digest["html"]
