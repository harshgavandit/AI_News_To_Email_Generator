from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest

from app import news


def item(index, title='Generic AI news', publisher='Publisher'):
    return {'id': f'id-{index:02}', 'url': f'https://example.org/{index}', 'title': title,
            'description': 'An excerpt', 'source': 'openai', 'publisher': publisher, 'category': 'News',
            'published_at': (datetime.now(UTC) - timedelta(hours=index)).isoformat()}


def test_registry_has_expanded_sources_and_stable_channel_ids():
    from app.sources import DEFAULT_SOURCES
    assert len(DEFAULT_SOURCES) >= 35
    assert len({s.id for s in DEFAULT_SOURCES}) == len(DEFAULT_SOURCES)
    assert {'matthew-berman', 'ai-engineer', 'karpathy', 'two-minute-papers', 'hugging-face-video'} <= {
        source.id for source in DEFAULT_SOURCES if source.kind == 'video'}


def test_canonical_urls_keep_video_identity_and_remove_tracking():
    assert news.canonical_url('https://www.youtube.com/watch?v=abc&utm_source=feed') == 'https://www.youtube.com/watch?v=abc'
    assert news.canonical_url('https://example.org/story/?utm_source=feed#part') == 'https://example.org/story'


def test_matching_older_story_makes_short_digest():
    from app.selection import select_candidates
    articles = [item(i) for i in range(15)] + [item(16, 'Deploying retrieval augmented generation with PostgreSQL', 'Other')]
    result = select_candidates(articles, 'PostgreSQL retrieval augmented generation', 3, ['openai'])
    assert 'id-16' in {a['id'] for a in result}


@pytest.fixture
def store(tmp_path):
    from app.launch_store import Store
    return Store(f'sqlite:///{(tmp_path / "launch.sqlite").as_posix()}')


def test_news_history_paginates_and_survives_partial_fetch_failure(store):
    store.ingest('openai-news', [item(1), item(2), item(3)], True)
    store.ingest('openai-news', [], False)
    filters = dict(hours=168, source='all', query='', kind='all', publisher='')
    first = store.page(**filters, limit=2, cursor=None)
    second = store.page(**filters, limit=2, cursor=first['next_cursor'])
    assert [a['id'] for a in first['articles']] == ['id-01', 'id-02']
    assert [a['id'] for a in second['articles']] == ['id-03']
    assert first['total'] == 3
    assert store.source_state()['openai-news']['available'] is False


def test_daily_quota_is_atomic_across_independent_connections(store):
    from app.launch_store import Store
    second = Store(str(store.engine.url))
    def attempt(i):
        return (store if i % 2 else second).admit([('mail:reader', '2026-11-13', 3)])
    with ThreadPoolExecutor(max_workers=8) as executor:
        assert sum(executor.map(attempt, range(20))) == 3
    assert store.admit([('mail:reader', '2026-11-14', 3)])


def test_challenge_limits_attempts_and_is_single_use(store):
    store.save_code('challenge', 'mailbox', 'right', 1_000_000_000_000)
    assert not store.consume_code('challenge', 'other', 'right')
    assert not store.consume_code('challenge', 'mailbox', 'wrong')
    assert store.consume_code('challenge', 'mailbox', 'right')
    assert not store.consume_code('challenge', 'mailbox', 'right')
    store.save_code('second', 'mailbox', 'right', 1_000_000_000_000)
    for _ in range(5):
        assert not store.consume_code('second', 'mailbox', 'wrong')
    assert not store.consume_code('second', 'mailbox', 'right')

def test_public_mail_verifies_one_inbox_and_limits_three_daily(store, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app import public_mail

    for key, value in {
        'PUBLIC_EMAIL_ENABLED': '1', 'MAIL_SESSION_SECRET': 'session-secret-for-tests-at-least-32',
        'MY_EMAIL': 'sender@example.org', 'APP_PASSWORD': 'local-test-password',
        'NEWS_DATABASE_URL': 'sqlite:///test-fixture',
        'TURNSTILE_SITE_KEY': 'test-site-key', 'TURNSTILE_SECRET_KEY': 'test-captcha-secret',
        'PUBLIC_ORIGIN': 'https://brief.example.org',
    }.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(public_mail, 'get_store', lambda: store)
    monkeypatch.setattr(public_mail, 'verify_human', lambda *args: True)
    inbox = []
    def capture(recipient, subject, body, html, key):
        inbox.append((recipient, subject, body, key))
        return f'accepted-{len(inbox)}'
    monkeypatch.setattr(public_mail, 'send_message', capture)
    app = FastAPI()
    app.include_router(public_mail.router)
    client = TestClient(app, base_url='https://brief.example.org')
    for i in range(4):
        store.save_preview(f'preview-{i:028}', {'markdown': f'Brief {i}', 'html': '<p>Brief</p>'}, 1_000_000_000_000)
    payload = {'preview_id': 'preview-0000000000000000000000000000'}
    assert client.post('/api/mail/send', json=payload).status_code == 401
    assert client.post('/api/mail/challenge', json={'email': 'Reader@Example.org', 'captcha': 'token'}).status_code == 200
    challenge = client.post('/api/mail/challenge', json={'email': 'reader@example.org', 'captcha': 'token'})
    assert challenge.status_code == 429
    code = inbox[0][2].split(' ')[-1].rstrip('.')
    assert client.post('/api/mail/verify', json={'code': code}).status_code == 200
    assert client.post('/api/mail/verify', json={'code': code}).status_code == 400
    assert client.post('/api/mail/send', json=dict(payload, email='other@example.org')).status_code == 422
    assert client.post('/api/mail/send', json=payload).status_code == 200
    assert client.post('/api/mail/send', json=payload).status_code == 200
    for i in (1, 2):
        assert client.post('/api/mail/send', json={'preview_id': f'preview-{i:028}'}).status_code == 200
    assert client.post('/api/mail/send', json={'preview_id': f'preview-{3:028}'}).status_code == 429
    monkeypatch.setenv('MAIL_PILOT_MODE', '1')
    assert client.post('/api/mail/challenge', json={'email': 'other@example.org', 'captcha': 'token'}).status_code == 403
    assert client.post('/api/mail/send', json=payload).status_code == 403
    assert len(inbox) == 4
    assert {entry[0] for entry in inbox} == {'reader@example.org'}


def test_delivery_retry_preserves_reservation(store):
    policies = [('mail:reader', '2026-11-13', 3)]
    assert store.reserve_delivery('same', policies) == ('new', None)
    assert store.reserve_delivery('same', policies) == ('retry', None)
    store.record_delivery('same', 'provider-1')
    assert store.reserve_delivery('same', policies) == ('retry', 'provider-1')
    assert store.reserve_delivery('another', policies) == ('new', None)
    assert store.reserve_delivery('third', policies) == ('new', None)
    assert store.reserve_delivery('fourth', policies) == ('limited', None)
