from collections import Counter
from types import SimpleNamespace

from app import ingestion


def queue(*hosts):
    return [(SimpleNamespace(id=f"{host}-{index}"), host) for index, host in enumerate(hosts)]


def test_github_release_feeds_get_a_larger_host_allowance():
    assert ingestion.host_limit("github.com") > ingestion.HOST_WORKERS
    assert ingestion.host_limit("example.com") == ingestion.HOST_WORKERS
    assert ingestion.host_gate("github.com") is ingestion.host_gate("github.com")


def test_deepest_host_queue_starts_first_but_keeps_priority_within_a_host():
    pending = queue("a.com", "b.com", *["github.com"] * 13, *["c.com"] * 5)
    first = ingestion.next_source(pending, Counter())
    assert pending[first][1] == "c.com"  # 5 queued at 2 per host drains slower than 13 at 6 per host.
    pending = queue("a.com", *["github.com"] * 30, "c.com", "c.com")
    first = ingestion.next_source(pending, Counter())
    assert first == 1  # The first GitHub feed, preserving priority order within the host.


def test_full_hosts_are_skipped_and_none_is_returned_when_all_are_busy():
    pending = queue("a.com", "a.com", "b.com")
    assert pending[ingestion.next_source(pending, Counter({"a.com": 2}))][1] == "b.com"
    assert ingestion.next_source(pending, Counter({"a.com": 2, "b.com": 2})) is None
    assert ingestion.next_source([], Counter()) is None


def test_paused_sources_record_a_reason():
    from app.sources import BY_ID
    for ident in ("naver-d2", "uber-engineering"):
        assert not BY_ID[ident].enabled and BY_ID[ident].pause_reason


def test_a_host_only_gets_its_larger_allowance_after_a_healthy_response():
    pending = queue(*["github.com"] * 10)
    cautious = lambda host: min(ingestion.HOST_WORKERS, ingestion.host_limit(host))
    assert ingestion.next_source(pending, Counter({"github.com": 2}), cautious) is None
    assert ingestion.next_source(pending, Counter({"github.com": 2})) == 0
