from collections import Counter

from scripts.check_type_baseline import compare, count_errors


def test_counts_errors_per_file_and_ignores_notes():
    output = "\n".join(
        [
            "app/a.py:3: error: Incompatible types  [assignment]",
            "app/a.py:9:5: error: Missing return  [return]",
            "app/a.py:9: note: See docs",
            "app\\b.py:1: error: Name is not defined  [name-defined]",
        ]
    )
    assert count_errors(output) == Counter({"app/a.py": 2, "app/b.py": 1})


def test_a_new_error_fails_and_a_fixed_error_is_reported():
    regressions, improvements = compare(
        Counter({"app/a.py": 3, "app/new.py": 1}), {"app/a.py": 2, "app/old.py": 4}
    )
    assert regressions == [
        "app/a.py: 3 errors (baseline 2)",
        "app/new.py: 1 errors (baseline 0)",
    ]
    assert improvements == ["app/old.py: 0 errors (baseline 4)"]
    assert compare(Counter({"app/a.py": 2}), {"app/a.py": 2}) == ([], [])
