from datetime import UTC, datetime, timedelta
from xml.etree import ElementTree

from fastapi.testclient import TestClient

from app import server
from app.launch_store import get_store
from app.sources import BY_ID


def test_release_serves_archive_from_ingestion_to_reader_and_rss(tmp_path, monkeypatch):
    monkeypatch.setenv("NEWS_DATABASE_URL", f"sqlite:///{tmp_path / 'release.db'}")
    source = BY_ID["openai-news"]
    story = {
        "id": "release-smoke",
        "source_id": source.id,
        "source": source.group,
        "publisher": source.label,
        "kind": source.kind,
        "category": "Research",
        "title": "AI research on document retrieval",
        "description": "A retrieval research excerpt for the release smoke test.",
        "url": "https://openai.com/news/release-smoke",
        "published_at": (datetime.now(UTC) - timedelta(minutes=5)).isoformat(),
    }
    store = get_store()
    assert store is not None
    store.ingest(source.id, [story], available=True)

    with TestClient(server.app) as client:
        home = client.get("/")
        assert home.status_code == 200
        assert "Informa AI" in home.text
        assert "style-src 'self'" in home.headers["content-security-policy"]
        assert client.get("/app.js").status_code == 200

        ready = client.get("/api/ready")
        assert ready.status_code == 200
        assert ready.json()["freshness"]["counts"]["fresh"] == 1

        latest = client.get("/api/news", params={"hours": 24, "limit": 5})
        assert latest.status_code == 200
        assert [article["id"] for article in latest.json()["articles"]] == [story["id"]]

        detail = client.get(f"/api/articles/{story['id']}")
        assert detail.status_code == 200
        assert detail.json()["article"]["url"] == story["url"]

        rss = client.get("/feeds/latest.xml")
        assert rss.status_code == 200
        assert rss.headers["content-type"].startswith("application/rss+xml")
        assert ElementTree.fromstring(rss.content).findtext("./channel/item/link") == story["url"]
