"""Recovering stories that only the previous production database holds."""
from datetime import UTC, datetime

from sqlalchemy import func, select

from app.launch_store import Store, article_feeds, articles
from scripts import recover_archive


def story(story_id, published, title="Story"):
    return {"id": story_id, "url": f"https://example.com/{story_id}", "title": title, "description": "About it",
            "source": "Example", "source_id": "example", "publisher": "Example", "kind": "news",
            "category": "Technology", "published_at": published}


def put(store, *rows, links=()):
    with store.engine.begin() as conn:
        conn.execute(articles.insert(), list(rows))
        if links:
            conn.execute(article_feeds.insert(), [{"article_id": a, "source_id": s} for a, s in links])


def count(store, table=articles):
    with store.engine.connect() as conn:
        return conn.scalar(select(func.count()).select_from(table))


def stores(tmp_path):
    return Store(f"sqlite:///{tmp_path / 'old.db'}"), Store(f"sqlite:///{tmp_path / 'new.db'}")


SINCE, UNTIL = datetime(2026, 11, 23, 12, tzinfo=UTC), datetime(2026, 11, 25, 8, tzinfo=UTC)


def test_copies_only_missing_stories_in_the_window_and_never_overwrites(tmp_path):
    old, new = stores(tmp_path)
    put(old, story("a1", "2026-11-24T03:00:00+00:00"), story("a2", "2026-11-24T09:30:00Z"),
        story("kept", "2026-11-24T05:00:00+00:00", title="Old title"),
        story("before", "2026-11-22T10:00:00+00:00"), story("after", "2026-11-25T09:00:00+00:00"),
        links=[("a1", "example"), ("a1", "mirror"), ("before", "example")])
    put(new, story("kept", "2026-11-24T05:00:00+00:00", title="Current title"))

    dry = recover_archive.recover(old, new, SINCE, UNTIL)
    assert dry == {"in_old": 3, "missing": 2, "copied": 0, "feed_links": 0}
    assert count(new) == 1

    done = recover_archive.recover(old, new, SINCE, UNTIL, apply=True)
    assert done["copied"] == 2 and done["feed_links"] == 2
    with new.engine.connect() as conn:
        ids = set(conn.scalars(select(articles.c.id)))
        title = conn.scalar(select(articles.c.title).where(articles.c.id == "kept"))
    assert ids == {"a1", "a2", "kept"} and title == "Current title"

    again = recover_archive.recover(old, new, SINCE, UNTIL, apply=True)
    assert again["missing"] == 0 and again["copied"] == 0 and count(new) == 3


def test_main_requires_two_different_databases_and_never_prints_urls(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("OLD_NEWS_DATABASE_URL", raising=False)
    monkeypatch.setenv("NEWS_DATABASE_URL", "sqlite:///x.db")
    assert recover_archive.main(["--since", "2026-11-23T12:00:00Z"]) == 1
    monkeypatch.setenv("OLD_NEWS_DATABASE_URL", "sqlite:///x.db")
    assert recover_archive.main(["--since", "2026-11-23T12:00:00Z"]) == 1
    assert "same database" in capsys.readouterr().out

    old, new = stores(tmp_path)
    put(old, story("a1", "2026-11-24T03:00:00+00:00"))
    monkeypatch.setenv("OLD_NEWS_DATABASE_URL", f"sqlite:///{tmp_path / 'old.db'}")
    monkeypatch.setenv("NEWS_DATABASE_URL", f"sqlite:///{tmp_path / 'new.db'}")
    assert recover_archive.main(["--since", "2026-11-23T12:00:00Z", "--until", "2026-11-25T08:00:00Z"]) == 0
    out = capsys.readouterr().out
    assert "dry run" in out and "1 missing" in out and str(tmp_path) not in out
    assert count(new) == 0
    assert recover_archive.main(["--since", "2026-11-23T12:00:00Z", "--until", "2026-11-25T08:00:00Z", "--apply"]) == 0
    assert count(new) == 1
