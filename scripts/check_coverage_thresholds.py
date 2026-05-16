"""Enforce per-file coverage thresholds from coverage.json.

`coverage.py` only enforces a global `--cov-fail-under`. This script reads the
JSON report produced by `pytest --cov-report=json` and fails any file whose
coverage drops below FILE_THRESHOLD. Run in CI after `pytest --cov`; non-zero
exit blocks the merge. The set of files is whatever `--cov` produced — new files
under `src/gandi_mcp/` are auto-included.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

TOTAL_THRESHOLD = 90.0
FILE_THRESHOLD = 90.0

COVERAGE_JSON = Path("coverage.json")


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

    for path, entry in sorted(files.items()):
        pct = entry["summary"]["percent_covered"]
        if pct < FILE_THRESHOLD:
            failures.append(f"{path}: {pct:.2f}% < {FILE_THRESHOLD:.1f}%")

    if failures:
        sys.stderr.write("Coverage thresholds violated:\n")
        for line in failures:
            sys.stderr.write(f"  - {line}\n")
        return 1

    sys.stdout.write(f"Coverage thresholds satisfied (total {total:.2f}%).\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
