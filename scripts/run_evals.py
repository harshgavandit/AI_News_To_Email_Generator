"""Replay Ask Informa against the fixed, synthetic archive. Stubbed by default."""

import argparse
from contextlib import ExitStack
from datetime import UTC, datetime, timedelta
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from app import ai_usage, ask, research
from app.cache import Cache
from app.launch_store import Store
from scripts.check_reader_quality import fixture_row

ROOT = Path(__file__).resolve().parents[1] / "evals"
ANCHOR = datetime(2026, 1, 15, 12, tzinfo=UTC)


class FixtureArchive(Store):
    def query(self, hours, **filters):
        return super().query(hours, **{"now": ANCHOR, **filters})


def populate(store: Store, records: list[dict]) -> None:
    store.migrate()
    by_source: dict[str, list[dict]] = {}
    for record in records:
        stamp = ANCHOR - timedelta(minutes=record["minutes_ago"])
        row = fixture_row(record, record["id"], record["excerpt"], stamp.timestamp())
        by_source.setdefault(row["source_id"], []).append(row)
    for source, stories in by_source.items():
        store.ingest(source, stories, True)


def stub_model(payload, _instructions, _schema, **_options):
    evidence = json.loads(payload)["evidence"]
    row = evidence[0]
    return json.dumps(
        {
            "status": "answered",
            "claims": [
                {
                    "text": row["excerpt"],
                    "kind": "fact",
                    "source_ids": [row["id"]],
                    "quotes": [row["excerpt"]],
                }
            ],
            "limitations": "",
        }
    )


def normalized(text: str) -> str:
    return " ".join(text.casefold().split())


def grade(case: dict, result: dict) -> dict:
    answer = normalized(result["answer"])
    expected = set(case["expected_story_ids"])
    cited = {citation["id"] for citation in result["citations"]}
    missing = [
        phrase for phrase in case["must_include"] if normalized(phrase) not in answer
    ]
    violations = [
        phrase for phrase in case["must_not_include"] if normalized(phrase) in answer
    ]
    return {
        "case": case["id"],
        "expected_status": case["expected_status"],
        "status": result["status"],
        "expected_story_ids": sorted(expected),
        "cited_story_ids": sorted(cited),
        "correct_citations": len(expected & cited),
        "all_citations": len(cited),
        "missing_facts": missing,
        "expected_facts": len(case["must_include"]),
        "violations": violations,
    }


def ratio(part: int, total: int) -> float:
    return round(part / total, 4) if total else 0.0


def scores(results: list[dict]) -> dict:
    answerable = [row for row in results if row["expected_status"] == "answered"]
    refusals = [row for row in results if row["expected_status"] == "refused"]
    facts = sum(row["expected_facts"] for row in results)
    return {
        "citation_rate": ratio(
            sum(row["correct_citations"] > 0 for row in answerable), len(answerable)
        ),
        "citation_precision": ratio(
            sum(row["correct_citations"] for row in results),
            sum(row["all_citations"] for row in results),
        ),
        "must_include_recall": ratio(
            facts - sum(len(row["missing_facts"]) for row in results), facts
        ),
        "must_not_include_violations": sum(len(row["violations"]) for row in results),
        "correct_refusals": ratio(
            sum(row["status"] == "refused" for row in refusals), len(refusals)
        ),
        "status_accuracy": ratio(
            sum(row["status"] == row["expected_status"] for row in results),
            len(results),
        ),
    }


def gate(metrics: dict, thresholds: dict) -> list[str]:
    return [
        name
        for name, value in metrics.items()
        if (
            value > thresholds[name]
            if name == "must_not_include_violations"
            else value < thresholds[name]
        )
    ]


def read_json(path: str):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def run(*, live: bool = False) -> dict:
    if live and not os.environ.get("OPENAI_API_KEY"):
        raise ValueError("Set OPENAI_API_KEY to run the manual live evaluation.")
    rows = read_json("fixtures/ask_archive.json")
    cases = read_json("ask_cases.json")
    with TemporaryDirectory() as folder, ExitStack() as context:
        store = FixtureArchive("sqlite:///" + (Path(folder) / "ask.db").as_posix())
        context.callback(store.engine.dispose)
        populate(store, rows)
        context.enter_context(patch.dict(os.environ, {"UPSTASH_REDIS_REST_URL": ""}))
        context.enter_context(patch.object(ask, "_cache", Cache("ask-fixture")))
        context.enter_context(
            patch.object(research, "vectors_enabled", return_value=False)
        )
        context.enter_context(patch.object(ai_usage, "_store", return_value=store))
        if not live:
            context.enter_context(
                patch.object(research, "ai_enabled", return_value=True)
            )
            context.enter_context(
                patch.object(research, "generate_response", side_effect=stub_model)
            )
            context.enter_context(
                patch.dict(os.environ, {"NEWS_AI_ANSWERS_DAILY": str(len(cases))})
            )
        results = [
            grade(
                case, ask.ask_archive(store, ask.AskRequest(question=case["question"]))
            )
            for case in cases
        ]
    metrics = scores(results)
    thresholds = read_json("thresholds.json")
    failures = gate(metrics, thresholds)
    return {
        "mode": "live" if live else "stub",
        "total_cases": len(results),
        "metrics": metrics,
        "thresholds": thresholds,
        "failed_metrics": failures,
        "passed": not failures,
        "cases": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--live",
        action="store_true",
        help="Use the configured model on the same fixture cases.",
    )
    args = parser.parse_args()
    try:
        report = run(live=args.live)
    except ValueError as error:
        parser.error(str(error))
    path = ROOT / "results" / "latest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(
        f"| {report['mode'].title()} evaluation ({report['total_cases']} cases) | Score | Threshold |"
    )
    print("| --- | ---: | ---: |")
    for name, value in report["metrics"].items():
        print(f"| {name} | {value} | {report['thresholds'][name]} |")
    print(
        "Passed."
        if report["passed"]
        else "Failed: " + ", ".join(report["failed_metrics"])
    )
    return int(not report["passed"])


if __name__ == "__main__":
    raise SystemExit(main())
