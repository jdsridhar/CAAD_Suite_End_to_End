#!/usr/bin/env python3
"""Summarize coverage.py JSON by CADD Suite architecture layer."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class CoverageCount:
    covered: int = 0
    statements: int = 0

    @property
    def percent(self) -> float:
        return 100.0 * self.covered / self.statements if self.statements else 100.0


def summarize(report: dict[str, Any]) -> dict[str, CoverageCount]:
    groups = {name: CoverageCount() for name in ("core", "adapters", "workers")}
    for filename, data in report["files"].items():
        if filename.startswith("src/caddsuite/adapters/"):
            group = "adapters"
        elif filename.startswith("src/caddsuite_worker/"):
            group = "workers"
        elif filename.startswith("src/caddsuite/"):
            group = "core"
        else:
            continue
        summary = data["summary"]
        groups[group].covered += int(summary["covered_lines"])
        groups[group].statements += int(summary["num_statements"])
    return groups


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path, help="coverage.py JSON report")
    parser.add_argument("--minimum-core", type=float)
    parser.add_argument("--minimum-adapters", type=float)
    args = parser.parse_args()
    report = json.loads(args.report.read_text(encoding="utf-8"))
    groups = summarize(report)
    print(f"{'Group':<12} {'Coverage':>9} {'Covered':>10} {'Statements':>12}")
    for name, data in groups.items():
        print(f"{name:<12} {data.percent:>8.2f}% {data.covered:>10} {data.statements:>12}")
    failures = []
    for name, minimum in (
        ("core", args.minimum_core),
        ("adapters", args.minimum_adapters),
    ):
        if minimum is not None and groups[name].percent < minimum:
            failures.append(f"{name} coverage {groups[name].percent:.2f}% is below {minimum:.2f}%")
    for failure in failures:
        print(f"FAIL: {failure}")
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
