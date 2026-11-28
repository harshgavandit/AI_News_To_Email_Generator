"""Score Watch agent with public synthetic stories and no delivery side effects."""

import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import time
from unittest.mock import patch

from app import ai_usage, watch_agent, watch_storage
from app.launch_store import Store, monitor_profiles, monitor_watches
from app.monitoring import Watch, watch_values
from scripts.check_reader_quality import fixture_row

ROOT = Path(__file__).resolve().parents[1] / "evals"


def read(name):
    return json.loads((ROOT / name).read_text(encoding="utf-8"))


def fixture(store, now):
    raw = {}
    for item in read("fixtures/watch_archive.json"):
        row = fixture_row(item, item["id"], item["excerpt"], now - 900)
        row["topic"] = item["topic"]
        raw[row["id"]] = row
        with patch("app.launch_store.time.time", return_value=now - 90):
            store.ingest(row["source_id"], [row], True)
    return raw


def draft_stub(case):
    def call(_store, _payload, _prompt, _schema, _task, _timeout):
        return json.dumps({"watch": case["watch"]})

    return call


def judge_stub(_store, payload, _prompt, _schema, _task, _timeout):
    watch = watch_agent.Spec.model_validate(payload["watch"])
    examples = payload["recent_not_relevant"]
    decisions = []
    for row in payload["stories"]:
        text = watch_agent.document(row)
        valid = not any(watch_agent.includes(text, term) for term in watch.exclude)
        valid &= all(watch_agent.includes(text, term) for term in watch.must_have)
        valid &= not watch.entities or any(
            watch_agent.includes(text, name) for name in watch.entities
        )
        valid &= watch.severity == "any" or watch_agent.includes(text, watch.severity)
        valid &= not any(watch_agent.document(example) == text for example in examples)
        decisions.append(
            {
                "story_id": row["id"],
                "match": valid,
                "confidence": 0.95,
                "quote": row["excerpt"][:215] if valid else "",
            }
        )
    return json.dumps({"decisions": decisions})


def canonical(ident):
    return "cloud-outage" if ident == "zz-cloud-duplicate" else ident


def score_case(store, raw, case, *, live):
    result = watch_agent.draft(
        store, case["sentence"], model=None if live else draft_stub(case)
    )
    expected, found, unrated = set(case["expected"]), [], []
    checked = []
    if result["status"] == "ready":
        watch = watch_agent.Spec.model_validate(result["watch"])
        records = [
            row
            for article in raw.values()
            if (row := watch_agent.archive_record(article))
        ]
        negatives = [row for row in records if row["id"] in case["negative_examples"]]

        def evaluate(examples):
            return watch_agent.graph(
                store,
                watch,
                records,
                examples,
                deadline=time.monotonic() + 8,
                model=None if live else judge_stub,
            ).get("checked", [])

        checked = watch_agent.grouped_matches(evaluate(negatives), raw, {})
        found = [canonical(row["id"]) for row in checked]
        if negatives:
            unrated = [canonical(row["id"]) for row in evaluate([])]
    valid = 0
    for row in checked:
        source = watch_agent.archive_record(raw[row["id"]])
        if (
            source
            and row["url"] == source["url"]
            and len(row["reason"]) == 2
            and row["source_checked"]
        ):
            quote = (
                row["reason"][1].removeprefix("Source evidence: “").removesuffix("”")
            )
            if watch_agent.checked_match(watch, source, quote, row["mode"]):
                valid += 1
    return {
        "case": case["id"],
        "state": result["status"],
        "expected": sorted(expected),
        "found": found,
        "correct": len(set(found) & expected),
        "valid_citations": valid,
        "unrated_false_positives": len(set(unrated) - expected),
        "negative_examples": len(case["negative_examples"]),
        "refusal_case": case["watch"] is None,
    }


def hourly_sample(store, now):
    cases = read("watch_cases.json")
    sample = [
        next(case for case in cases if case["id"] == key)
        for key in ("cloud-1", "model-1", "security-1", "none-1")
    ]
    with store.engine.begin() as conn:
        for index, case in enumerate(sample):
            profile = str(index).zfill(64)
            spec = watch_agent.Spec.model_validate(case["watch"])
            watch = Watch(id=case["id"], query=spec.summary, agent=spec)
            conn.execute(
                monitor_profiles.insert().values(
                    id=profile, expires=now + 3600, revision=0
                )
            )
            conn.execute(
                monitor_watches.insert().values(
                    **watch_values(profile, watch, now - 150)
                )
            )
            watch_storage.write_specs(conn, profile, [watch], now - 150)
    return watch_storage.run(store, now=now, model=judge_stub, budget_seconds=30)


def run(*, live=False):
    if live and (
        os.getenv("GITHUB_EVENT_NAME") != "workflow_dispatch"
        or os.getenv("GITHUB_WORKFLOW") != "Ask Informa live evaluation"
    ):
        raise ValueError(
            "Live Watch agent evaluation requires the manual Ask Informa live evaluation workflow."
        )
    if live and not os.getenv("OPENAI_API_KEY"):
        raise ValueError(
            "Configure the workflow's OPENAI_API_KEY secret to run the manual evaluation."
        )
    now = time.time()
    with TemporaryDirectory() as folder:
        store = Store("sqlite:///" + (Path(folder) / "watch.db").as_posix())
        try:
            raw = fixture(store, now)
            with patch.object(ai_usage, "_store", return_value=store):
                results = [
                    score_case(store, raw, case, live=live)
                    for case in read("watch_cases.json")
                ]
            usage = ai_usage.summary(store) if live else []
            hourly = None if live else hourly_sample(store, now)
        finally:
            store.engine.dispose()
    positive = [row for row in results if row["found"]]
    refusals = [row for row in results if row["refusal_case"]]
    duplicate_cases = [row for row in results if row["case"].startswith("cloud-")]
    feedback_cases = [row for row in results if row["negative_examples"]]
    emitted = sum(len(row["found"]) for row in positive)

    def ratio(count, total):
        return round(count / total, 4) if total else 0.0

    correct = sum(row["correct"] for row in results)
    metrics = {
        "precision": ratio(correct, emitted),
        "recall": ratio(correct, sum(len(row["expected"]) for row in results)),
        "duplicate_suppression": ratio(
            sum(row["found"].count("cloud-outage") == 1 for row in duplicate_cases),
            len(duplicate_cases),
        ),
        "citation_accuracy": ratio(
            sum(row["valid_citations"] for row in results), emitted
        ),
        "refusals": ratio(
            sum(row["state"] == "refused" and not row["found"] for row in refusals),
            len(refusals),
        ),
        "feedback_improvement": ratio(
            sum(
                bool(row["unrated_false_positives"])
                and set(row["found"]) == set(row["expected"])
                for row in feedback_cases
            ),
            len(feedback_cases),
        ),
    }
    thresholds = read("watch_thresholds.json")
    failed = [key for key, floor in thresholds.items() if metrics[key] < floor]
    return {
        "mode": "live" if live else "stub",
        "total_cases": len(results),
        "metrics": metrics,
        "thresholds": thresholds,
        "failed_metrics": failed,
        "passed": not failed,
        "cases": results,
        "fixture_hourly_run": hourly,
        "model_usage": usage,
    }
