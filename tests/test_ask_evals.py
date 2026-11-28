from app import weekly_recap
from scripts import editor_evals, run_evals


def test_scoring_detects_wrong_sources_missing_facts_and_bad_refusals():
    cases = [
        {
            "id": "answer",
            "expected_status": "answered",
            "expected_story_ids": ["one"],
            "must_include": ["storage API", "25 minutes"],
            "must_not_include": ["payments"],
        },
        {
            "id": "refusal",
            "expected_status": "refused",
            "expected_story_ids": [],
            "must_include": [],
            "must_not_include": [],
        },
    ]
    results = [
        {
            "status": "answered",
            "answer": "Storage API and payments",
            "citations": [{"id": "one"}, {"id": "wrong"}],
        },
        {"status": "insufficient", "answer": "No source", "citations": []},
    ]
    rows = [
        run_evals.grade(case, result)
        for case, result in zip(cases, results, strict=True)
    ]
    assert run_evals.scores(rows) == {
        "citation_rate": 1,
        "citation_precision": 0.5,
        "must_include_recall": 0.5,
        "must_not_include_violations": 1,
        "correct_refusals": 0,
        "status_accuracy": 0.5,
    }
    assert run_evals.gate(
        run_evals.scores(rows), run_evals.read_json("thresholds.json")
    ) == [
        "citation_precision",
        "must_include_recall",
        "must_not_include_violations",
        "correct_refusals",
        "status_accuracy",
    ]


def test_eval_matrix_has_independent_expected_outcomes():
    cases = run_evals.read_json("ask_cases.json")
    assert len(cases) >= 40
    assert len({row["id"] for row in cases}) == len(cases)
    assert {row["expected_status"] for row in cases} == {
        "answered",
        "insufficient",
        "refused",
    }


def test_editor_recap_fixture_cites_distinct_stories_from_the_requested_week():
    item = editor_evals.recap()
    start, end = weekly_recap.week_bounds(item["action"]["week"])
    assert len({row["id"] for row in item["evidence"]}) == 3
    assert all(start.isoformat() <= row["date"] < end.isoformat() for row in item["evidence"])
