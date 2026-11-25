"""Type-check the application and block new mypy errors (a ratchet).

The application predates type checking and still has known errors. Rather than fail
every pull request, each file may keep at most the number of errors recorded in
``scripts/mypy-baseline.json``. A change that adds an error to any file fails; a change
that removes errors passes and prints the lower count so the baseline can be tightened.

Usage:
  python -m scripts.check_type_baseline              # check against the baseline
  python -m scripts.check_type_baseline --update     # rewrite the baseline (review the diff)
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "scripts" / "mypy-baseline.json"
MYPY = [
    sys.executable,
    "-m",
    "mypy",
    "app",
    "--ignore-missing-imports",
    "--follow-imports=silent",
    "--no-error-summary",
    "--no-pretty",
    "--show-error-codes",
]
ERROR = re.compile(r"^(?P<path>[^:]+\.py):\d+(?::\d+)?: error: ")


def count_errors(output: str) -> Counter[str]:
    counts: Counter[str] = Counter()
    for line in output.splitlines():
        if match := ERROR.match(line):
            counts[match["path"].replace("\\", "/")] += 1
    return counts


def compare(
    current: Counter[str], baseline: dict[str, int]
) -> tuple[list[str], list[str]]:
    """Return (regressions, improvements) as readable lines."""
    regressions = [
        f"{path}: {count} errors (baseline {baseline.get(path, 0)})"
        for path, count in sorted(current.items())
        if count > baseline.get(path, 0)
    ]
    improvements = [
        f"{path}: {current.get(path, 0)} errors (baseline {allowed})"
        for path, allowed in sorted(baseline.items())
        if current.get(path, 0) < allowed
    ]
    return regressions, improvements


def run_mypy() -> str:
    result = subprocess.run(MYPY, cwd=ROOT, capture_output=True, text=True, check=False)
    if result.returncode not in (
        0,
        1,
    ):  # 2 means mypy itself failed (bad config, crash).
        sys.stderr.write(result.stdout + result.stderr)
        raise SystemExit("mypy did not run cleanly")
    return result.stdout


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--update",
        action="store_true",
        help="rewrite the baseline from the current code",
    )
    args = parser.parse_args(argv)
    output = run_mypy()
    current = count_errors(output)
    if args.update:
        BASELINE.write_text(
            json.dumps(dict(sorted(current.items())), indent=2) + "\n", encoding="utf-8"
        )
        print(
            f"Baseline updated: {sum(current.values())} errors in {len(current)} files."
        )
        return 0
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    regressions, improvements = compare(current, baseline)
    print(
        f"mypy: {sum(current.values())} errors in {len(current)} files "
        f"(baseline {sum(baseline.values())} in {len(baseline)} files)."
    )
    if improvements:
        print(
            "Fewer errors than the baseline. Run `python -m scripts.check_type_baseline --update` to lock in:"
        )
        print("\n".join(f"  {line}" for line in improvements))
    if regressions:
        print(
            "::error::New type errors. Fix them or explain why the baseline should grow:"
        )
        print("\n".join(f"  {line}" for line in regressions))
        print(
            "\n".join(
                line
                for line in output.splitlines()
                if any(
                    line.startswith(entry.split(":")[0] + ":") for entry in regressions
                )
            )
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
