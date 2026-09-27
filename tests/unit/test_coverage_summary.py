from __future__ import annotations

from scripts.summarize_coverage import summarize


def test_coverage_groups_follow_platform_layers() -> None:
    report = {
        "files": {
            "src/caddsuite/workflow/scheduler.py": {
                "summary": {"covered_lines": 8, "num_statements": 10}
            },
            "src/caddsuite/adapters/docking/vina.py": {
                "summary": {"covered_lines": 5, "num_statements": 10}
            },
            "src/caddsuite_worker/psi4_worker.py": {
                "summary": {"covered_lines": 2, "num_statements": 10}
            },
            "tests/unit/test_scheduler.py": {
                "summary": {"covered_lines": 100, "num_statements": 100}
            },
        }
    }

    counts = summarize(report)

    assert (counts["core"].covered, counts["core"].statements) == (8, 10)
    assert counts["core"].percent == 80
    assert (counts["adapters"].covered, counts["adapters"].statements) == (5, 10)
    assert counts["adapters"].percent == 50
    assert (counts["workers"].covered, counts["workers"].statements) == (2, 10)
