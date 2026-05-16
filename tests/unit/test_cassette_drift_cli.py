"""CLI subprocess tests for scripts/cassette_drift.py.

Offline-pure: no live network, no real gh API. The gh CLI is stubbed via
a PATH-shadowing fake executable written into tmp_path.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "cassette_drift.py"


def _cassette(interactions: list[dict]) -> str:
    return yaml.safe_dump({"interactions": interactions})


def _interaction(uri: str, body_json: str | None, method: str = "GET", status: int = 200) -> dict:
    return {
        "request": {"method": method, "uri": uri, "body": None},
        "response": {"status": {"code": status}, "body": {"string": body_json if body_json is not None else ""}},
    }


def _run_cli(args: list[str], env_extra: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def _write_gh_stub(
    bindir: Path,
    *,
    on_list: str = "[]",
    on_create_rc: int = 0,
    on_comment_rc: int = 0,
    recorder: Path | None = None,
) -> None:
    """Write a fake gh that records argv into ``recorder`` and behaves per the kwargs."""
    bindir.mkdir(parents=True, exist_ok=True)
    rec = str(recorder) if recorder else "/dev/null"
    gh = bindir / "gh"
    gh.write_text(
        textwrap.dedent(f"""\
        #!/usr/bin/env bash
        echo "$@" >> {rec}
        case "$1 $2" in
          "issue list")
            echo '{on_list}'
            exit 0
            ;;
          "issue create")
            cat >/dev/null
            echo "https://github.com/x/y/issues/123"
            exit {on_create_rc}
            ;;
          "issue comment")
            cat >/dev/null
            exit {on_comment_rc}
            ;;
        esac
        exit 0
    """)
    )
    gh.chmod(gh.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _path_with_stub(bindir: Path) -> dict[str, str]:
    return {"PATH": f"{bindir}:{os.environ.get('PATH', '')}"}


@pytest.fixture
def cassette_dirs(tmp_path: Path) -> tuple[Path, Path]:
    old = tmp_path / "old"
    new = tmp_path / "new"
    old.mkdir()
    new.mkdir()
    return old, new


class TestExitCodes:
    def test_no_drift_exit_0(self, cassette_dirs: tuple[Path, Path]) -> None:
        old, new = cassette_dirs
        body = '{"username": "alice"}'
        (old / "x.yaml").write_text(_cassette([_interaction("https://x", body)]))
        (new / "x.yaml").write_text(_cassette([_interaction("https://x", body)]))
        result = _run_cli(["--cassette-dir-old", str(old), "--cassette-dir-new", str(new)])
        assert result.returncode == 0, result.stderr
        assert result.stdout == ""

    def test_drift_exit_1_with_report(self, cassette_dirs: tuple[Path, Path]) -> None:
        old, new = cassette_dirs
        (old / "x.yaml").write_text(_cassette([_interaction("https://x", '{"a": "x"}')]))
        (new / "x.yaml").write_text(_cassette([_interaction("https://x", '{"a": "x", "b": 1}')]))
        result = _run_cli(["--cassette-dir-old", str(old), "--cassette-dir-new", str(new)])
        assert result.returncode == 1, result.stdout + result.stderr
        assert "+ added .b (int)" in result.stdout
        assert "x.yaml" in result.stdout

    def test_missing_dir_exit_2(self, cassette_dirs: tuple[Path, Path]) -> None:
        old, _new = cassette_dirs
        result = _run_cli(["--cassette-dir-old", str(old), "--cassette-dir-new", "/nonexistent"])
        assert result.returncode == 2
        assert "--cassette-dir-new not found" in result.stderr

    def test_empty_old_dir_exit_0_with_warning(self, cassette_dirs: tuple[Path, Path]) -> None:
        old, new = cassette_dirs
        result = _run_cli(["--cassette-dir-old", str(old), "--cassette-dir-new", str(new)])
        assert result.returncode == 0
        assert "no cassettes found" in result.stderr

    def test_single_cassette_parse_failure_exits_1(self, cassette_dirs: tuple[Path, Path]) -> None:
        old, new = cassette_dirs
        # One good cassette, one malformed.
        body = '{"a": 1}'
        (old / "good.yaml").write_text(_cassette([_interaction("https://x", body)]))
        (new / "good.yaml").write_text(_cassette([_interaction("https://x", body)]))
        (old / "bad.yaml").write_text("not: : valid: yaml: :::")
        (new / "bad.yaml").write_text(_cassette([_interaction("https://y", body)]))
        result = _run_cli(["--cassette-dir-old", str(old), "--cassette-dir-new", str(new)])
        assert result.returncode == 1, result.stderr
        assert "cassettes failed to parse" in result.stderr


class TestOpenIssueFlag:
    def test_open_issue_creates_when_no_existing(self, cassette_dirs: tuple[Path, Path], tmp_path: Path) -> None:
        old, new = cassette_dirs
        (old / "x.yaml").write_text(_cassette([_interaction("https://x", '{"a": "x"}')]))
        (new / "x.yaml").write_text(_cassette([_interaction("https://x", '{"a": "x", "b": 1}')]))
        recorder = tmp_path / "gh-argv.txt"
        bindir = tmp_path / "bin"
        _write_gh_stub(bindir, on_list="[]", recorder=recorder)
        result = _run_cli(
            ["--cassette-dir-old", str(old), "--cassette-dir-new", str(new), "--open-issue"],
            env_extra=_path_with_stub(bindir),
        )
        assert result.returncode == 1
        argv_log = recorder.read_text()
        assert "issue list" in argv_log
        assert "issue create" in argv_log
        assert "--label drift" in argv_log

    def test_open_issue_appends_when_existing_open(self, cassette_dirs: tuple[Path, Path], tmp_path: Path) -> None:
        old, new = cassette_dirs
        (old / "x.yaml").write_text(_cassette([_interaction("https://x", '{"a": "x"}')]))
        (new / "x.yaml").write_text(_cassette([_interaction("https://x", '{"a": "x", "b": 1}')]))
        recorder = tmp_path / "gh-argv.txt"
        bindir = tmp_path / "bin"
        existing = json.dumps([{"number": 42, "title": "drift: 1 cassette drifted upstream"}])
        _write_gh_stub(bindir, on_list=existing, recorder=recorder)
        result = _run_cli(
            ["--cassette-dir-old", str(old), "--cassette-dir-new", str(new), "--open-issue"],
            env_extra=_path_with_stub(bindir),
        )
        assert result.returncode == 1
        argv_log = recorder.read_text()
        assert "issue comment 42" in argv_log
        assert "issue create" not in argv_log

    def test_open_issue_failure_returns_distinct_exit_code(
        self, cassette_dirs: tuple[Path, Path], tmp_path: Path
    ) -> None:
        # When --open-issue is set and gh fails to create the issue, exit code is 3
        # (not 1) so CI dashboards can distinguish "drift posted to tracker" from
        # "drift detected but lost to a gh outage".
        old, new = cassette_dirs
        (old / "x.yaml").write_text(_cassette([_interaction("https://x", '{"a": "x"}')]))
        (new / "x.yaml").write_text(_cassette([_interaction("https://x", '{"a": "x", "b": 1}')]))
        recorder = tmp_path / "gh-argv.txt"
        bindir = tmp_path / "bin"
        _write_gh_stub(bindir, on_list="[]", on_create_rc=1, recorder=recorder)
        result = _run_cli(
            ["--cassette-dir-old", str(old), "--cassette-dir-new", str(new), "--open-issue"],
            env_extra=_path_with_stub(bindir),
        )
        assert result.returncode == 3, result.stderr
        assert "+ added .b (int)" in result.stdout
        assert "issue creation failed" in result.stderr

    def test_open_issue_comment_failure_still_reports_drift(
        self, cassette_dirs: tuple[Path, Path], tmp_path: Path
    ) -> None:
        old, new = cassette_dirs
        (old / "x.yaml").write_text(_cassette([_interaction("https://x", '{"a": "x"}')]))
        (new / "x.yaml").write_text(_cassette([_interaction("https://x", '{"a": "x", "b": 1}')]))
        recorder = tmp_path / "gh-argv.txt"
        bindir = tmp_path / "bin"
        existing = json.dumps([{"number": 42, "title": "drift: 1 cassette drifted upstream"}])
        _write_gh_stub(bindir, on_list=existing, on_comment_rc=1, recorder=recorder)
        result = _run_cli(
            ["--cassette-dir-old", str(old), "--cassette-dir-new", str(new), "--open-issue"],
            env_extra=_path_with_stub(bindir),
        )
        # With the I3 fix, gh failure under --open-issue is exit 3, not 1.
        assert result.returncode == 3
        assert "+ added .b (int)" in result.stdout
        assert "issue creation failed" in result.stderr


class TestSubdirectoryWalking:
    def test_subdirectory_cassettes_are_walked(self, cassette_dirs: tuple[Path, Path]) -> None:
        old, new = cassette_dirs
        (old / "area1").mkdir()
        (new / "area1").mkdir()
        (old / "area1" / "c.yaml").write_text(_cassette([_interaction("https://x", '{"a": 1}')]))
        (new / "area1" / "c.yaml").write_text(_cassette([_interaction("https://x", '{"a": 1, "b": "new"}')]))
        result = _run_cli(["--cassette-dir-old", str(old), "--cassette-dir-new", str(new)])
        assert result.returncode == 1
        assert "area1/c.yaml" in result.stdout


class TestWarnings:
    def test_non_json_body_emits_warning_not_drift(self, cassette_dirs: tuple[Path, Path]) -> None:
        old, new = cassette_dirs
        (old / "x.yaml").write_text(_cassette([_interaction("https://x", "<html>not json</html>")]))
        (new / "x.yaml").write_text(_cassette([_interaction("https://x", "<html>not json</html>")]))
        result = _run_cli(["--cassette-dir-old", str(old), "--cassette-dir-new", str(new)])
        assert result.returncode == 0
        # 2xx + non-JSON body is the high-signal regression case.
        assert "invalid JSON body" in result.stderr
        assert "+ added" not in result.stdout

    def test_non_2xx_body_emits_no_warning(self, cassette_dirs: tuple[Path, Path]) -> None:
        old, new = cassette_dirs
        # 404 on both sides — intentional skip, no warning needed.
        (old / "x.yaml").write_text(_cassette([_interaction("https://x", '{"e": 1}', status=404)]))
        (new / "x.yaml").write_text(_cassette([_interaction("https://x", '{"e": 1}', status=404)]))
        result = _run_cli(["--cassette-dir-old", str(old), "--cassette-dir-new", str(new)])
        assert result.returncode == 0
        # non_2xx and empty are intentional contracts — they must not pollute stderr.
        assert "invalid JSON body" not in result.stderr
        assert "schema regression" not in result.stderr

    def test_missing_on_new_emits_warning_not_drift(self, cassette_dirs: tuple[Path, Path]) -> None:
        old, _new = cassette_dirs
        (old / "x.yaml").write_text(_cassette([_interaction("https://x", '{"a": 1}')]))
        result = _run_cli(["--cassette-dir-old", str(old), "--cassette-dir-new", str(_new)])
        assert result.returncode == 0
        assert "missing-on-new" in result.stderr

    def test_orchestration_drift_only_does_not_fail(self, cassette_dirs: tuple[Path, Path]) -> None:
        old, new = cassette_dirs
        # New cassette adds an extra interaction that doesn't exist in old.
        body = '{"a": 1}'
        (old / "x.yaml").write_text(_cassette([_interaction("https://x/a", body)]))
        (new / "x.yaml").write_text(_cassette([_interaction("https://x/a", body), _interaction("https://x/b", body)]))
        result = _run_cli(["--cassette-dir-old", str(old), "--cassette-dir-new", str(new)])
        assert result.returncode == 0  # orchestration drift only — no shape drift
        assert "orchestration: added" in result.stderr
