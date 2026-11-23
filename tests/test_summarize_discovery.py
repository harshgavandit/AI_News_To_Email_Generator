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
