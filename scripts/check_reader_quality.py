"""Reproducible offline evaluation of coverage grouping, novelty, and citation validation."""
from datetime import UTC, datetime
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import time

from app import ai_insights, event_intelligence, research
from app.launch_store import Store
from app.sources import BY_ID

FIXTURES = Path(__file__).with_name("reader_quality_cases.json")


def fixture_row(case, ident, excerpt, stamp, *, source_id=None):
    source = BY_ID[source_id or case["source_id"]]
    return {"id": ident, "title": case["title"], "description": excerpt, "topic": source.topic,
            "source": source.group, "source_id": source.id, "publisher": source.label,
            "kind": source.kind, "category": "Technology",
            "url": f"https://{source.hosts[0]}/reader-quality/{ident}",
            "published_at": datetime.fromtimestamp(stamp, UTC).isoformat()}


def citations_pass(case, entries):
    excerpt = next((row["excerpt"] for row in entries if case["quote"] in row["excerpt"]), "")
    if not excerpt:
        return False
    evidence = [{"id": "fixture-evidence", "title": case["title"], "excerpt": excerpt}]
    schema = research.answer_schema(evidence, quoted=True)
    def validate(text):
        answer = schema.model_validate({"status": "answered", "limitations": "Only the fixture excerpt is available.",
            "claims": [{"text": text, "kind": "fact", "source_ids": ["fixture-evidence"], "quotes": [case["quote"]]}]})
        return research.validate_answer(answer, evidence)

    validate(case["accepted_claim"])
    try:
        validate(case["rejected_claim"])
    except ValueError:
        return True
    return False


def evaluate(store, case):
    now = time.time()
    ident = case["id"]
    row = fixture_row(case, ident, case["first"], now - 900)
    store.ingest(row["source_id"], [row], True)
    development, _ = event_intelligence.observe(store, row, now=now - 810)
    revisions, grouped = [], []
    for index, step in enumerate(case["steps"], 1):
        entry = (fixture_row(case, f"{ident}-{index}", step["excerpt"], now - 900 + index)
                 if step.get("repeat") else dict(row, description=step["excerpt"]))
        store.ingest(entry["source_id"], [entry], True)
        linked, _ = event_intelligence.observe(store, entry, now=now - 810 + index)
        grouped.append(linked == development)
        timeline = event_intelligence.timeline(store, development)
        revisions.append((timeline["entries"][0]["reason"], timeline["revision"]))
    catalog = event_intelligence.catalog(store, query=case["expected_search"], hours=12, limit=20)
    ranked = ai_insights.rank_events(catalog, ai_insights.RadarProfile(followed_events=[development]), {})
    timeline = event_intelligence.timeline(store, development)
    first = timeline["entries"][-1]
    latency = round(first["observed"] - datetime.fromisoformat(first["published_at"]).timestamp())
    return {"case": ident, "source": case["source"], "grouped": all(grouped),
            "material_revisions": revisions == [(step["reason"], step["revision"]) for step in case["steps"]],
            "search_and_rank": bool(ranked and ranked[0]["id"] == development),
            "citation_validation": citations_pass(case, timeline["entries"]),
            "replay_latency_seconds": latency, "replay_latency_pass": 0 <= latency <= 120}


def run():
    suite = json.loads(FIXTURES.read_text(encoding="utf-8"))
    with TemporaryDirectory() as folder:
        store = Store("sqlite:///" + (Path(folder) / "quality.db").as_posix())
        try:
            store.migrate()
            cases = [evaluate(store, case) for case in suite["cases"]]
        finally:
            store.engine.dispose()
    checks = ("grouped", "material_revisions", "search_and_rank", "citation_validation", "replay_latency_pass")
    return {"method": suite["method"], "cases": cases, "passed": all(row[key] for row in cases for key in checks)}


if __name__ == "__main__":
    report = run()
    print(json.dumps(report, indent=2))
    raise SystemExit(0 if report["passed"] else 1)
