from app.news import PRERELEASE
from app.sanitation import sanitize_story_excerpt, sanitize_text
from app.visit_catchup import NOTICE


def test_wordpress_feed_footer_is_removed():
    text = "Memory makers are reshaping their research agenda. The post Memory R&D Is a High-Stakes Game appeared first on EE Times."
    assert sanitize_text(text) == "Memory makers are reshaping their research agenda."
    assert "appeared first" not in sanitize_story_excerpt(text, "eetimes")


def test_truncation_markers_and_read_more_links_are_removed():
    assert sanitize_text("Chipmakers expand capacity in Arizona [&#8230;]") == "Chipmakers expand capacity in Arizona"
    assert sanitize_text("A short summary. Continue reading on the site") == "A short summary."


def test_prerelease_builds_are_recognised():
    for title in ("electron v46.0.0-alpha.12", "React 19.2.0-rc.1", "v1.0.0rc2", "Release 3.1 Beta",
                  "nightly-2026-11-21", "v0.12.0.dev3", "Canary 2026.11"):
        assert PRERELEASE.search(title), title


def test_stable_releases_and_product_names_are_kept():
    for title in ("v2.4.1", "Developer preview program opens", "Devcontainers v1.2", "Betaflight 4.5",
                  "Prettier 3.4: release notes", "Alpha Fold 3 weights", "v3.0.0 – Beta testers rejoice"):
        assert not PRERELEASE.search(title), title


def test_catchup_notice_is_reader_facing():
    assert "index" not in NOTICE.casefold()
