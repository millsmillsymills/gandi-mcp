"""Enforce per-file and per-directory coverage thresholds from coverage.json.

`coverage.py` only enforces a global `--cov-fail-under`. This script reads the
JSON report produced by `pytest --cov-report=json` and fails on per-file gaps.
Run in CI after `pytest --cov`; non-zero exit blocks the merge.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

TOTAL_THRESHOLD = 85.0

PER_FILE_THRESHOLDS: dict[str, float] = {
    "src/gandi_mcp/clients/base.py": 90.0,
    "src/gandi_mcp/errors.py": 90.0,
    "src/gandi_mcp/server.py": 90.0,
    "src/gandi_mcp/config.py": 90.0,
}

PER_DIR_THRESHOLDS: dict[str, float] = {
    "src/gandi_mcp/tools/": 70.0,
}

COVERAGE_JSON = Path("coverage.json")


def _coverage(files: dict[str, dict[str, dict[str, float]]], path: str) -> float | None:
    entry = files.get(path)
    if entry is None:
        return None
    return entry["summary"]["percent_covered"]


def main() -> int:
    if not COVERAGE_JSON.exists():
        sys.stderr.write(f"ERROR: {COVERAGE_JSON} not found. Run pytest with --cov-report=json first.\n")
        return 2

    data = json.loads(COVERAGE_JSON.read_text())
    files = data["files"]
    total = data["totals"]["percent_covered"]

    failures: list[str] = []

    if total < TOTAL_THRESHOLD:
        failures.append(f"TOTAL: {total:.2f}% < {TOTAL_THRESHOLD:.1f}%")

    for path, threshold in PER_FILE_THRESHOLDS.items():
        pct = _coverage(files, path)
        if pct is None:
            failures.append(f"{path}: missing from coverage report")
            continue
        if pct < threshold:
            failures.append(f"{path}: {pct:.2f}% < {threshold:.1f}%")

    for dir_prefix, threshold in PER_DIR_THRESHOLDS.items():
        matched = [(p, files[p]["summary"]["percent_covered"]) for p in files if p.startswith(dir_prefix)]
        if not matched:
            failures.append(f"{dir_prefix}: no files matched (check prefix)")
            continue
        for path, pct in matched:
            if pct < threshold:
                failures.append(f"{path}: {pct:.2f}% < {threshold:.1f}% (dir gate)")

    if failures:
        sys.stderr.write("Coverage thresholds violated:\n")
        for line in failures:
            sys.stderr.write(f"  - {line}\n")
        return 1

    sys.stdout.write(f"Coverage thresholds satisfied (total {total:.2f}%).\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
