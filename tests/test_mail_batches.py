import base64
import hashlib
import hmac
import json
import time
from unittest.mock import Mock

import httpx
import pytest
from fastapi.testclient import TestClient

from app import mail_batches, mail_events, public_mail, server
from app.launch_store import Store
from app.mail_capacity import mail_capacity


@pytest.fixture
def batch_store(tmp_path, monkeypatch):
    for key, value in {"RESEND_API_KEY": "fake", "MAIL_FROM": "brief@example.org",
                       "MAIL_SESSION_SECRET": "a-test-secret-that-is-not-used-in-production",
                       "MAIL_OUTBOUND_DAILY_LIMIT": "12000", "MAIL_DIGEST_DAILY_LIMIT": "11000"}.items():
        monkeypatch.setenv(key, value)
    return Store(f"sqlite:///{tmp_path / 'batches.db'}")


def test_batch_retry_reuses_exact_payload_and_reserves_quota_once(batch_store, monkeypatch):
    store = batch_store
    clock = [int(time.time())]
    monkeypatch.setattr(mail_batches.time, "time", lambda: clock[0])
    mailbox = public_mail.digest_key("mailbox:reader@example.org")
    store.subscribe(mailbox, "reader@example.org", "UTC", clock[0] - 60)
    post = Mock(side_effect=[httpx.ReadTimeout("test timeout"), httpx.Response(200, json={"data": [{"id": "accepted"}]})])
    monkeypatch.setattr(mail_batches.httpx, "post", post)
    generator = Mock(return_value={"html": "<body>daily</body>", "markdown": "daily"})

    assert mail_batches.run_batch_worker(store, generator)["queued"] == 1
    assert mail_batches.run_batch_worker(store, generator)["sent"] == 0
    clock[0] += 31
    assert mail_batches.run_batch_worker(store, generator)["sent"] == 1
    generator.assert_called_once()
    assert post.call_args_list[0] == post.call_args_list[1]
    assert post.call_args.kwargs["json"][0]["headers"]["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"
    policy = [(f"mail:{mailbox}", public_mail.day(), 3)]
    assert store.admit(policy) and store.admit(policy) and not store.admit(policy)


def test_global_budget_defers_remaining_schedules(batch_store, monkeypatch):
    store = batch_store
    monkeypatch.setenv("MAIL_DIGEST_DAILY_LIMIT", "1")
    for i in range(2):
        store.subscribe(str(i), f"reader{i}@example.org", "UTC", time.time() - 10)
    mock = Mock(return_value=httpx.Response(200, json={"data": [{"id": "accepted"}]}))
    monkeypatch.setattr(mail_batches.httpx, "post", mock)
    result = mail_batches.run_batch_worker(store, lambda: {"html": "<p>daily</p>", "markdown": "daily"})
    assert result["sent"] == 1 and result["due"] == 1
    mock.assert_called_once()
    monkeypatch.delenv("RESEND_API_KEY")
    assert mail_capacity().digests == 45


def test_batch_scheduled_mail_contains_saved_curiosity_cards(batch_store, monkeypatch):
    from app.curiosity import curiosity_article

    store = batch_store
    mailbox = public_mail.digest_key("mailbox:reader@example.org")
    store.subscribe(mailbox, "reader@example.org", "UTC", time.time() - 10)
    store.save_curiosity_selection(mailbox, [curiosity_article("attention-is-all-you-need")])
    response = httpx.Response(200, json={"data": [{"id": "provider-accepted"}]},
                              request=httpx.Request("POST", "https://api.resend.com/emails/batch"))
    post = Mock(return_value=response)
    monkeypatch.setattr(mail_batches.httpx, "post", post)

    result = mail_batches.run_batch_worker(store, lambda: {
        "html": "<html><body><p>Daily</p></body></html>", "markdown": "Daily"})

    assert result["sent"] == 1
    message = post.call_args.kwargs["json"][0]
    assert "Attention Is All You Need" in message["text"]
    assert "Google Research" in message["text"]
    assert "https://research.google/pubs/attention-is-all-you-need" in message["text"]
    assert "Curiosity Cards" in message["html"]


def test_resend_transient_retry_keeps_payload_and_idempotency_key(batch_store, monkeypatch):
    post = Mock(side_effect=[httpx.ReadTimeout('lost response'), httpx.Response(200, json={'id': 'provider-1'},
        request=httpx.Request('POST', 'https://api.resend.com/emails'))])
    monkeypatch.setattr(public_mail.httpx, 'post', post)
    assert public_mail.send_message('reader@example.org', 'Brief', 'Text', '<p>Brief</p>', 'stable-key') == 'provider-1'
    assert post.call_count == 2
    assert post.call_args_list[0] == post.call_args_list[1]
    assert post.call_args.kwargs['headers']['Idempotency-Key'] == 'stable-key'


def test_provider_acceptance_requires_a_message_id_and_rejections_are_not_retried(batch_store, monkeypatch):
    post = Mock(return_value=httpx.Response(200, json={}, request=httpx.Request('POST', 'https://api.resend.com/emails')))
    monkeypatch.setattr(public_mail.httpx, 'post', post)
    with pytest.raises(OSError, match='did not confirm'):
        public_mail.send_message('reader@example.org', 'Brief', 'Text', None, 'key')
    assert post.call_count == 1
    post.reset_mock()
    post.return_value = httpx.Response(422, request=httpx.Request('POST', 'https://api.resend.com/emails'))
    with pytest.raises(OSError, match='did not confirm'):
        public_mail.send_message('reader@example.org', 'Brief', 'Text', None, 'key')
    assert post.call_count == 1


def test_signed_bounce_suppresses_inbox_and_replay_does_not_double_count(batch_store, monkeypatch):
    store = batch_store
    monkeypatch.setattr(mail_events, "get_store", lambda: store)
    mailbox = public_mail.digest_key("mailbox:reader@example.org")
    store.subscribe(mailbox, "reader@example.org", "UTC", time.time() - 10)
    key = b"test-signing-key"
    monkeypatch.setenv("RESEND_WEBHOOK_SECRET", "whsec_" + base64.b64encode(key).decode())
    payload = json.dumps({"type": "email.bounced", "data": {"to": ["reader@example.org"]}}).encode()
    ts = str(int(time.time()))
    signature = base64.b64encode(hmac.new(key, f"msg_test.{ts}.".encode() + payload, hashlib.sha256).digest()).decode()
    with TestClient(server.app) as client:
        headers = {"svix-timestamp": ts, "svix-id": "msg_test", "svix-signature": f"v1,{signature}"}
        assert client.post("/api/mail/events/resend", content=payload, headers={**headers, "svix-signature": "bad"}).status_code == 401
        assert not store.suppressed(mailbox)
        for _ in range(2):
            assert client.post("/api/mail/events/resend", content=payload, headers=headers).status_code == 200
    assert store.suppressed(mailbox) and not store.subscription(mailbox)["enabled"]
    assert store.mail_backlog(time.time())["provider_events_24h"] == {"email.bounced": 1}
