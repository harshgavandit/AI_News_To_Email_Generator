"""Public ownership, quotas and opt-in scheduling against a real isolated store."""
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import public_mail
from app.launch_store import Store


@pytest.fixture
def mail(tmp_path, monkeypatch):
    store = Store(f'sqlite:///{(tmp_path / "mail.sqlite").as_posix()}')
    for key, value in {
        'PUBLIC_EMAIL_ENABLED': '1', 'MAIL_SESSION_SECRET': 'test-mail-session-secret-at-least-32',
        'MY_EMAIL': 'sender@example.org', 'APP_PASSWORD': 'test-only',
        'NEWS_DATABASE_URL': 'sqlite:///fixture', 'TURNSTILE_SITE_KEY': 'site',
        'TURNSTILE_SECRET_KEY': 'secret', 'PUBLIC_ORIGIN': 'https://brief.example.org',
    }.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv('VERCEL', raising=False)
    monkeypatch.delenv('MAIL_PILOT_MODE', raising=False)
    monkeypatch.setattr(public_mail, 'get_store', lambda: store)
    inbox = []
    def capture(recipient, subject, body, html, key, **kwargs):
        inbox.append(dict(recipient=recipient, body=body, html=html, key=key, **kwargs))
        return key
    monkeypatch.setattr(public_mail, 'send_message', capture)
    app = FastAPI()
    app.include_router(public_mail.router)
    client = TestClient(app, base_url='https://brief.example.org')
    client.cookies.set(public_mail.SESSION, public_mail.seal('session', 'reader@example.org', 3600))
    for i in range(9):
        store.save_preview(f'preview-{i:028}', {'markdown': 'Brief', 'html': '<p>Brief</p>'}, time.time() + 3600)
    return store, client, inbox


def test_verified_email_matches_request_without_accepting_another_inbox(mail):
    store, client, inbox = mail
    assert client.get('/api/mail/config').json()['verified_email'] == 'reader@example.org'
    payload = {'preview_id': f'preview-{0:028}', 'email': 'reader@example.org'}
    assert client.post('/api/mail/send', json=payload).status_code == 200
    assert client.post('/api/mail/send', json=dict(payload, email='someone@example.org')).status_code == 422
    assert len(inbox) == 1


def test_five_ip_hour_limit_counts_unique_deliveries_across_mailboxes(mail):
    _, client, inbox = mail
    for i in range(6):
        client.cookies.set(public_mail.SESSION, public_mail.seal('session', f'reader{i}@example.org', 3600))
        result = client.post('/api/mail/send', json={'preview_id': f'preview-{i:028}'})
        assert result.status_code == (200 if i < 5 else 429)
        if i == 0:
            assert client.post('/api/mail/send', json={'preview_id': f'preview-{i:028}'}).status_code == 200
    assert len(inbox) == 5


def test_subscription_requires_explicit_opt_in_and_timezone(mail):
    store, client, _ = mail
    payload = {'preview_id': f'preview-{0:028}'}
    assert client.post('/api/mail/send', json=payload).status_code == 200
    mailbox = public_mail.digest_key('mailbox:reader@example.org')
    assert store.subscription(mailbox) is None
    assert client.post('/api/mail/send', json=dict(payload, subscribe=True)).status_code == 422
    assert client.post('/api/mail/send', json=dict(payload, subscribe=True, timezone='Mars/Base')).status_code == 422
    response = client.post('/api/mail/send', json=dict(payload, subscribe=True, timezone='Asia/Kolkata'))
    assert response.status_code == 200
    assert response.json()['subscribed'] is True
    subscription = store.subscription(mailbox)
    assert subscription['timezone'] == 'Asia/Kolkata'
    assert subscription['enabled'] is True


def test_morning_schedule_uses_local_eight_and_dst():
    from app.mail_schedule import next_morning
    # New York switches to daylight time on March 8, 2026.
    assert next_morning('America/New_York', datetime(2026, 3, 7, 14, tzinfo=UTC)) == datetime(2026, 3, 8, 12, tzinfo=UTC).timestamp()
    assert next_morning('Asia/Kolkata', datetime(2026, 11, 14, 1, tzinfo=UTC)) == datetime(2026, 11, 14, 2, 30, tzinfo=UTC).timestamp()


def test_scheduler_claim_is_atomic_and_unsubscribe_stops_future_deliveries(mail, monkeypatch):
    from app import mail_schedule
    store, client, inbox = mail
    monkeypatch.setattr(mail_schedule, 'get_store', lambda: store)
    mailbox = public_mail.digest_key('mailbox:reader@example.org')
    store.subscribe(mailbox, 'reader@example.org', 'UTC', time.time() - 10)
    with ThreadPoolExecutor(max_workers=4) as workers:
        list(workers.map(lambda _: mail_schedule.run_due_subscriptions(lambda: {'markdown': 'Daily', 'html': '<p>Daily</p>'}), range(4)))
    assert len(inbox) == 1
    assert 'unsubscribe_url' in inbox[0]
    url = inbox[0]['unsubscribe_url']
    # GET is a confirmation, so scanners cannot unsubscribe someone.
    assert client.get(url).status_code == 200
    assert store.subscription(mailbox)['enabled'] is True
    assert client.post(url, content='List-Unsubscribe=One-Click', headers={'Content-Type': 'application/x-www-form-urlencoded'}).status_code == 200
    assert store.subscription(mailbox)['enabled'] is False
    assert mail_schedule.run_due_subscriptions(lambda: {'markdown': 'Daily', 'html': '<p>Daily</p>'})['sent'] == 0
    assert client.post(url + 'tampered').status_code == 400


def test_subscription_retry_after_ambiguous_send_does_not_duplicate(mail, monkeypatch):
    from app import mail_schedule
    store, _, inbox = mail
    monkeypatch.setattr(mail_schedule, 'get_store', lambda: store)
    mailbox = public_mail.digest_key('mailbox:reader@example.org')
    store.subscribe(mailbox, 'reader@example.org', 'UTC', time.time() - 10)
    def timeout(*args, **kwargs):
        raise OSError('ambiguous transport timeout')
    monkeypatch.setattr(public_mail, 'send_message', timeout)
    result = mail_schedule.run_due_subscriptions(lambda: {'markdown': 'Daily', 'html': '<p>Daily</p>'})
    assert result['unconfirmed'] == 1
    assert mail_schedule.run_due_subscriptions(lambda: {'markdown': 'Daily', 'html': '<p>Daily</p>'})['sent'] == 0
