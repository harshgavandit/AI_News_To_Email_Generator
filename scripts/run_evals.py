"""Replay Ask Informa against the fixed, synthetic archive. Stubbed by default."""

import argparse
from contextlib import ExitStack
from datetime import UTC, datetime, timedelta
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter
from unittest.mock import patch

from app import ai_usage, ask, deep_ask, research
from app.cache import Cache
from app.launch_store import Store
from scripts.check_reader_quality import fixture_row

ROOT = Path(__file__).resolve().parents[1] / "evals"
ANCHOR = datetime(2026, 1, 15, 12, tzinfo=UTC)


class FixtureArchive(Store):
    def query(self, hours, *args, **filters):
        return super().query(hours, *args, **{"now": ANCHOR, **filters})


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


def deep_stub(plan: list[str], follow_up: list[str]):
    """Exercise real search and checking while substituting only model output."""

    def respond(payload, _instructions, _schema, *, task, **_options):
        data = json.loads(payload)
        if task == "deep_plan":
            return json.dumps({"queries": plan})
        evidence = data["evidence"]
        if task == "deep_assess":
            return json.dumps({"enough": len(evidence) >= 3, "queries": follow_up})
        claims = [
            {"source_id": row["id"], "text": row["excerpt"]} for row in evidence[:3]
        ]
        return json.dumps(
            {
                "summary": claims[:1],
                "sections": [
                    {"heading": heading, "claims": [claim]}
                    for heading, claim in zip(deep_ask.HEADINGS, claims)
                ],
                "timeline": [
                    {**claim, "date": row["published_at"][:10]}
                    for claim, row in zip(claims, evidence)
                ],
            }
        )

    return respond


def grade_deep(case: dict, result: dict, control: deep_ask.Control) -> dict:
    dates = case["expected_dates"]
    expected = set(dates)
    cited = {citation["n"]: citation["id"] for citation in result["citations"]}
    lines = result["summary"].splitlines()
    for section in result["sections"]:
        lines.extend(section["text"].splitlines())
    for entry in result["timeline"]:
        lines.append(entry["event"])
    sentences = (
        [line for line in lines if line.strip()]
        if result["status"] == "answered"
        else []
    )
    text = normalized(" ".join(sentences))
    correct_dates = {
        cited[n]
        for item in result["timeline"]
        for n in item["citations"]
        if n in cited and dates.get(cited[n]) == item["date"]
    }
    return {
        "case": case["id"],
        "status": result["status"],
        "expected_status": case["expected_status"],
        "correct_citations": len(set(cited.values()) & expected),
        "all_citations": len(cited),
        "sentences": len(sentences),
        "cited_sentences": sum(
            bool(markers := deep_ask.guardrails.MARKER.findall(line))
            and all(int(number) in cited for number in markers)
            for line in sentences
        ),
        "required_facts": len(case["required_facts"]),
        "facts_found": sum(normalized(fact) in text for fact in case["required_facts"]),
        "correct_dates": len(correct_dates),
        "expected_dates": len(dates),
        "violations": sum(
            normalized(fact) in text for fact in case["prohibited_facts"]
        ),
        "limits_ok": (
            result["steps_used"] <= deep_ask.MAX_STEPS
            and result["stories_read"] <= deep_ask.MAX_STORIES
            and control.rounds <= deep_ask.MAX_ROUNDS
            and control.queries <= deep_ask.MAX_QUESTIONS
            and control.tokens <= deep_ask.MAX_TOKENS
        ),
        "steps": result["steps_used"],
        "rounds": control.rounds,
        "minimum_rounds": case["minimum_rounds"],
    }


def deep_scores(results: list[dict]) -> dict:
    def total(name):
        return sum(row[name] for row in results)

    def status_score(status):
        cases = [row for row in results if row["expected_status"] == status]
        return ratio(sum(row["status"] == status for row in cases), len(cases))

    answerable = sum(row["expected_status"] == "answered" for row in results)
    follow_ups = [row for row in results if row["minimum_rounds"] > 1]
    return {
        "citation_rate": ratio(total("cited_sentences"), total("sentences"))
        * ratio(sum(row["correct_citations"] > 0 for row in results), answerable),
        "citation_precision": ratio(total("correct_citations"), total("all_citations")),
        "required_fact_recall": ratio(total("facts_found"), total("required_facts")),
        "timeline_date_accuracy": ratio(
            total("correct_dates"), total("expected_dates")
        ),
        "must_not_include_violations": total("violations"),
        "correct_refusals": status_score("refused"),
        "correct_insufficient": status_score("insufficient"),
        "steps_within_limits": ratio(total("limits_ok"), len(results)),
        "follow_up_success": ratio(
            sum(
                row["status"] == "answered" and row["rounds"] >= row["minimum_rounds"]
                for row in follow_ups
            ),
            len(follow_ups),
        ),
    }


def run_deep(*, live: bool = False) -> dict:
    if live and not os.environ.get("OPENAI_API_KEY"):
        raise ValueError("Set OPENAI_API_KEY to run the manual live evaluation.")
    rows = read_json("fixtures/deep_archive.json") + [
        row for row in read_json("fixtures/ask_archive.json") if row["id"] == "meridian"
    ]
    cases = read_json("deep_cases.json")
    started = perf_counter()
    with TemporaryDirectory() as folder, ExitStack() as context:
        store = FixtureArchive("sqlite:///" + (Path(folder) / "deep.db").as_posix())
        context.callback(store.engine.dispose)
        populate(store, rows)
        context.enter_context(
            patch("app.launch_store.page_window", return_value=(ANCHOR, None))
        )
        context.enter_context(
            patch.object(deep_ask, "_cache", Cache("deep-fixture", shared=False))
        )
        context.enter_context(patch.object(ai_usage, "_store", return_value=store))
        context.enter_context(
            patch.dict(os.environ, {"NEWS_AI_DEEP_DAILY": str(len(cases))})
        )
        results = []
        for case in cases:
            control = deep_ask.Control()
            model = None if live else deep_stub(case["plan"], case["follow_up"])
            result = deep_ask.research_archive(
                store,
                deep_ask.DeepRequest(question=case["question"]),
                control,
                model=model,
            )
            results.append(grade_deep(case, result, control))
    metrics = deep_scores(results)
    thresholds = read_json("deep_thresholds.json")
    failures = gate(metrics, thresholds)
    return {
        "mode": "live" if live else "stub",
        "total_cases": len(results),
        "elapsed_ms": round((perf_counter() - started) * 1000),
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
    parser.add_argument(
        "--deep", action="store_true", help="Score archive research reports."
    )
    parser.add_argument("--watch", action="store_true", help="Score the archive Watch agent.")
    parser.add_argument("--editor", action="store_true", help="Score the archive Editor agent.")
    args = parser.parse_args()
    if sum((args.deep, args.watch, args.editor)) > 1:
        parser.error("Choose one evaluation mode.")
    if (
        args.deep
        and args.live
        and (
            os.getenv("GITHUB_EVENT_NAME") != "workflow_dispatch"
            or os.getenv("GITHUB_WORKFLOW") != "Ask Informa live evaluation"
        )
    ):
        parser.error(
            "Live Deep Ask evaluation requires the manual Ask Informa live evaluation workflow."
        )
    try:
        if args.editor:
            from scripts import editor_evals

            report = editor_evals.run(live=args.live)
        elif args.watch:
            from scripts import watch_evals

            report = watch_evals.run(live=args.live)
        else:
            report = (run_deep if args.deep else run)(live=args.live)
    except ValueError as error:
        parser.error(str(error))
    filename = ("latest-editor.json" if args.editor else "latest-watch.json" if args.watch
                else "latest-deep.json" if args.deep else "latest.json")
    path = ROOT / "results" / filename
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
