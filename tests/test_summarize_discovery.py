from scripts.summarize_discovery import known_urls, summarize


def test_summary_marks_new_feeds_and_lists_failures():
    report = {"results": [
        {"page": "https://a.example/blog", "status": "discovered",
         "feeds": [{"url": "https://a.example/feed.xml"}, {"url": "https://www.brendangregg.com/blog/rss.xml"}]},
        {"page": "https://b.example/", "status": "unavailable", "error": "HTTPStatusError", "feeds": []},
    ]}
    text, new = summarize(report, known_urls())
    assert new == ["https://a.example/feed.xml"]
    assert "| https://a.example/blog | new | https://a.example/feed.xml |" in text
    assert "already in catalog" in text and "HTTPStatusError" in text
    assert text.strip().endswith("NEW_FEEDS=https://a.example/feed.xml")


def test_feeds_from_earlier_candidate_packs_are_not_proposed_again():
    from scripts.summarize_discovery import tried_urls
    tried = tried_urls()
    assert "https://medium.com/feed/skyscanner-engineering" in tried
    report = {"results": [{"page": "https://x.example/", "status": "discovered",
                           "feeds": [{"url": "https://medium.com/feed/skyscanner-engineering"}]}]}
    text, new = summarize(report, known_urls(), tried)
    assert new == [] and "| checked before |" in text


def test_discovery_seeds_fit_one_run():
    import json
    from app.article_metadata import public_link
    with open("app/discovery_seeds.json", encoding="utf-8") as handle:
        seeds = json.load(handle)
    assert 1 <= len(seeds) <= 150 and len(set(seeds)) == len(seeds)
    assert all(public_link(url) for url in seeds)
