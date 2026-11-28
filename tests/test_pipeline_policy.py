"""Repository delivery policy: pinned actions, gate wiring and the Release CI decision."""

import json
import os
from pathlib import Path
import re
import shutil
import subprocess

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = sorted((ROOT / ".github" / "workflows").glob("*.yml"))


def load(path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_vercel_builds_require_a_manual_deployment():
    config = json.loads((ROOT / "vercel.json").read_text(encoding="utf-8"))
    assert config["git"]["deploymentEnabled"] is False


@pytest.mark.parametrize(
    "workflow, job, names",
    [
        (
            "refresh-feeds.yml",
            "intelligence",
            {
                "watch_agent_status",
                "watch_agent_checked",
                "watch_agent_alerts",
                "watch_agent_candidates",
                "watch_agent_model_calls",
                "editor_status",
                "editor_candidates",
                "editor_model_calls",
                "editor_queued",
            },
        ),
        ("weekly-recap.yml", "recap", {"editor_recap_status", "editor_recap_queued"}),
    ],
)
def test_existing_jobs_log_agent_counts_without_logging_the_raw_response(
    workflow, job, names
):
    step = load(ROOT / ".github" / "workflows" / workflow)["jobs"][job]["steps"][0]
    projection = re.search(r"jq '\{([a-z_,\s]+)\}' <<< \"\$result\"", step["run"])
    assert projection
    assert names <= set(re.findall(r"[a-z_]+", projection.group(1)))


def test_every_action_is_pinned_to_a_full_commit_sha():
    unpinned = []
    for path in WORKFLOWS:
        for line in path.read_text(encoding="utf-8").splitlines():
            match = re.search(r"uses:\s*([^\s#]+)", line)
            if (
                match
                and not match.group(1).startswith("./")
                and not re.search(r"@[0-9a-f]{40}$", match.group(1))
            ):
                unpinned.append(f"{path.name}: {match.group(1)}")
    assert unpinned == []


@pytest.mark.skipif(not shutil.which("bash"), reason="needs bash")
@pytest.mark.parametrize(
    "selection, failures, expected, status",
    [
        ({}, {}, ["quick"], 0),
        ({"DEEP_EVAL": "true", "EDITOR_EVAL": "true"}, {}, ["deep", "editor"], 0),
        ({"ALL_AGENTS": "true"}, {"deep": 1}, ["deep", "watch", "editor"], 1),
        ({"ALL_AGENTS": "true"}, {"deep": 2}, ["deep"], 2),
    ],
)
def test_live_workflow_runs_selected_agents_and_preserves_failures(
    tmp_path, selection, failures, expected, status
):
    workflow = load(ROOT / ".github" / "workflows" / "ask-evals-live.yml")
    step = next(step for step in workflow["jobs"]["evaluate"]["steps"] if "run" in step and "modes=" in step["run"])
    simulator = '''uv() {
      mode=${@: -1}
      mode=${mode#--}
      if [[ $mode == live ]]; then mode=quick; fi
      echo "ran:$mode"
      case "$mode" in
        deep) return "$DEEP_STATUS";;
        *) return 0;;
      esac
    }
    '''
    env = {
        **os.environ,
        **dict.fromkeys(("ALL_AGENTS", "DEEP_EVAL", "WATCH_EVAL", "EDITOR_EVAL"), "false"),
        **selection,
        "GITHUB_STEP_SUMMARY": (tmp_path / "summary").as_posix(),
        "DEEP_STATUS": str(failures.get("deep", 0)),
    }
    result = subprocess.run([shutil.which("bash"), "-c", simulator + step["run"]], env=env, capture_output=True, text=True)
    assert result.returncode == status, result.stderr
    assert [line.removeprefix("ran:") for line in result.stdout.splitlines() if line.startswith("ran:")] == expected


def test_build_and_test_gates_depend_on_change_detection_and_security_always_runs():
    jobs = load(ROOT / ".github" / "workflows" / "ci.yml")["jobs"]
    for name in ("verify", "frontend", "database"):
        assert jobs[name]["needs"] == "changes"
        assert jobs[name]["if"] == "needs.changes.outputs.code == 'true'"
    assert "if" not in jobs["security"]
    assert set(jobs["release"]["needs"]) == {
        "changes",
        "verify",
        "frontend",
        "security",
        "database",
    }
    assert jobs["release"]["if"] == "${{ always() }}"


def release_decision(**results):
    """Run the Release CI step's own bash with the given job results."""
    step = load(ROOT / ".github" / "workflows" / "ci.yml")["jobs"]["release"]["steps"][
        0
    ]
    summary = ROOT / ".pytest_cache" / "release-summary.md"
    summary.parent.mkdir(exist_ok=True)
    env = {
        **os.environ,
        "GITHUB_STEP_SUMMARY": str(summary),
        **{key.upper(): value for key, value in results.items()},
    }
    return subprocess.run(
        [shutil.which("bash"), "-c", step["run"]], env=env, capture_output=True, text=True
    ).returncode


@pytest.mark.skipif(not shutil.which("bash"), reason="needs bash")
@pytest.mark.parametrize(
    "results, allowed",
    [
        (
            {
                "changes": "success",
                "code": "true",
                "python": "success",
                "frontend": "success",
                "security": "success",
                "database": "success",
            },
            True,
        ),
        (
            {
                "changes": "success",
                "code": "false",
                "python": "skipped",
                "frontend": "skipped",
                "security": "success",
                "database": "skipped",
            },
            True,
        ),
        # Code changed but a gate was skipped, failed or cancelled.
        (
            {
                "changes": "success",
                "code": "true",
                "python": "skipped",
                "frontend": "success",
                "security": "success",
                "database": "success",
            },
            False,
        ),
        (
            {
                "changes": "success",
                "code": "true",
                "python": "success",
                "frontend": "failure",
                "security": "success",
                "database": "success",
            },
            False,
        ),
        (
            {
                "changes": "success",
                "code": "true",
                "python": "success",
                "frontend": "success",
                "security": "success",
                "database": "cancelled",
            },
            False,
        ),
        # Markdown-only changes still need the security scan and working change detection.
        (
            {
                "changes": "success",
                "code": "false",
                "python": "skipped",
                "frontend": "skipped",
                "security": "failure",
                "database": "skipped",
            },
            False,
        ),
        (
            {
                "changes": "failure",
                "code": "",
                "python": "skipped",
                "frontend": "skipped",
                "security": "success",
                "database": "skipped",
            },
            False,
        ),
    ],
)
def test_release_ci_blocks_every_failed_skipped_or_cancelled_gate(results, allowed):
    assert (release_decision(**results) == 0) is allowed


def test_dependency_updates_enter_through_staging():
    config = load(ROOT / ".github" / "dependabot.yml")
    assert {update["package-ecosystem"] for update in config["updates"]} == {
        "uv",
        "npm",
        "github-actions",
    }
    assert all(update["target-branch"] == "Staging" for update in config["updates"])


def test_codeql_scans_python_javascript_and_workflows_on_every_pull_request():
    workflow = load(ROOT / ".github" / "workflows" / "codeql.yml")
    triggers = workflow[True]
    assert set(triggers["pull_request"]["branches"]) == {"main", "Staging"}
    assert workflow["jobs"]["analyze"]["strategy"]["matrix"]["language"] == [
        "python",
        "javascript-typescript",
        "actions",
    ]
