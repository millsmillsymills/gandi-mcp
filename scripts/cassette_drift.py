"""Structural drift detector for VCR cassettes.

Compares response shapes between two cassette directories (typically the
committed ``tests/contract/cassettes/`` and a freshly-recorded
``tests/contract/cassettes.new/``). Emits ``+/-/~/!`` entries for keys
added/removed, types changed, and list cardinality bounds changed.

Run via ``make check-drift`` after PR #100 lands. See
``docs/superpowers/specs/2026-05-15-cassette-drift-detection-design.md``.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

# A "shape" is one of:
#   - a string scalar tag: "str" / "int" / "float" / "bool" / "null"
#   - a frozenset of (key, child_shape) pairs (dict)
#   - a tuple ("list", min_len, max_len, item_shape)
#   - a tuple ("union", frozenset_of_member_shapes)
# Shapes are hashable so frozensets can hold them.
Shape = Any


def extract_shape(value: Any) -> Shape:  # noqa: PLR0911 — one return per JSON type tag; flatter than dispatch dict
    """Walk ``value`` and return its normalized shape, discarding all values."""
    # bool must be checked before int because bool is a subclass of int in Python.
    if isinstance(value, bool):
        return "bool"
    if value is None:
        return "null"
    if isinstance(value, str):
        return "str"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, dict):
        return frozenset((k, extract_shape(v)) for k, v in value.items())
    if isinstance(value, list):
        return merge_list_shape([extract_shape(item) for item in value])
    # Bytes / unknown types fall through to a tag we can compare on.
    return type(value).__name__


def merge_list_shape(items: list[Shape]) -> Shape:
    """Fold a list of item shapes into ``("list", min, max, item_shape)``.

    Mixed item shapes collapse into ``("union", frozenset)``.
    """
    n = len(items)
    if n == 0:
        return ("list", 0, 0, None)
    distinct = frozenset(items)
    if len(distinct) == 1:
        return ("list", n, n, next(iter(distinct)))
    return ("list", n, n, ("union", distinct))


@dataclass(frozen=True)
class DriftEntry:
    kind: str
    path: str
    old: str | None
    new: str | None


def _render_shape(shape: Shape) -> str:
    """Compact human-readable rendering for diff messages."""
    if isinstance(shape, str):
        return shape
    if isinstance(shape, frozenset):
        # dict shape — render keyset for brevity
        keys = sorted(k for k, _ in shape)
        return "{" + ", ".join(keys) + "}"
    if isinstance(shape, tuple):
        tag = shape[0]
        if tag == "list" and len(shape) == 4:
            _, lo, hi, item = shape
            return f"list[{_render_shape(item) if item is not None else 'empty'}]({lo}..{hi})"
        if tag == "union" and len(shape) == 2:
            members = sorted(_render_shape(m) for m in shape[1])
            return "{" + ", ".join(members) + "}"
    return repr(shape)


def diff_shapes(old: Shape, new: Shape, path: str = "") -> list[DriftEntry]:
    """Walk two shapes and return drift entries sorted by jq-path for determinism."""
    entries: list[DriftEntry] = []

    if isinstance(old, frozenset) and isinstance(new, frozenset):
        old_keys = dict(old)
        new_keys = dict(new)
        for k in sorted(set(old_keys) | set(new_keys)):
            child_path = f"{path}.{k}"
            if k not in old_keys:
                entries.append(DriftEntry("added", child_path, None, _render_shape(new_keys[k])))
            elif k not in new_keys:
                entries.append(DriftEntry("removed", child_path, _render_shape(old_keys[k]), None))
            else:
                entries.extend(diff_shapes(old_keys[k], new_keys[k], child_path))
        return entries

    if (
        isinstance(old, tuple)
        and isinstance(new, tuple)
        and len(old) == 4
        and len(new) == 4
        and old[0] == new[0] == "list"
    ):
        _, o_lo, o_hi, o_item = old
        _, n_lo, n_hi, n_item = new
        if (o_lo, o_hi) != (n_lo, n_hi):
            entries.append(DriftEntry("cardinality_changed", path, f"{o_lo}..{o_hi}", f"{n_lo}..{n_hi}"))
        if o_item is not None and n_item is not None:
            entries.extend(diff_shapes(o_item, n_item, f"{path}[]"))
        elif o_item != n_item:
            entries.append(
                DriftEntry(
                    "type_changed",
                    f"{path}[]",
                    _render_shape(o_item) if o_item is not None else "empty",
                    _render_shape(n_item) if n_item is not None else "empty",
                )
            )
        return entries

    if (
        isinstance(old, tuple)
        and isinstance(new, tuple)
        and len(old) == 2
        and len(new) == 2
        and old[0] == new[0] == "union"
    ):
        if old[1] != new[1]:
            entries.append(DriftEntry("union_changed", path, _render_shape(old), _render_shape(new)))
        return entries

    if old != new:
        entries.append(DriftEntry("type_changed", path, _render_shape(old), _render_shape(new)))
    return entries


_RENDERERS = {
    "added": lambda e: f"+ added {e.path} ({e.new})",
    "removed": lambda e: f"- removed {e.path} ({e.old})",
    "type_changed": lambda e: f"~ {e.path}: {e.old} → {e.new}",
    "cardinality_changed": lambda e: f"! list {e.path}: {e.old} → {e.new}",
    "union_changed": lambda e: f"~ union {e.path}: {e.old} → {e.new}",
}


def render_report(cassette_path: str, entries: list[DriftEntry], fmt: str = "text") -> str:
    """Render a per-cassette drift report. Empty entries → empty string."""
    if not entries:
        return ""
    sorted_entries = sorted(entries, key=lambda e: (e.path, e.kind))
    lines = [_RENDERERS[e.kind](e) for e in sorted_entries]
    if fmt == "md":
        return f"## {cassette_path}\n\n```\n" + "\n".join(lines) + "\n```\n"
    return f"{cassette_path}:\n" + "\n".join(f"  {line}" for line in lines) + "\n"


class CassetteParseError(Exception):
    """Raised when a cassette YAML is malformed or missing required structure."""


def _request_key(req: dict) -> tuple[str, str, str]:
    method = str(req.get("method", ""))
    uri = str(req.get("uri", ""))
    body = req.get("body")
    body_bytes = b"" if body is None else (body.encode("utf-8") if isinstance(body, str) else bytes(body))
    body_hash = hashlib.sha256(body_bytes).hexdigest()
    return (method, uri, body_hash)


def load_cassette(path: str) -> list[tuple[dict, Any, int]]:
    """Parse a VCR cassette into ``(request, body_or_None, occurrence_index)`` triples."""
    try:
        with Path(path).open(encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise CassetteParseError(f"YAML parse error in {path}: {e}") from e
    if not isinstance(data, dict) or "interactions" not in data:
        raise CassetteParseError(f"missing top-level 'interactions' in {path}")
    interactions = data["interactions"]
    if not isinstance(interactions, list):
        raise CassetteParseError(f"'interactions' in {path} is not a list")

    triples: list[tuple[dict, Any, int]] = []
    counts: dict[tuple[str, str, str], int] = {}
    for interaction in interactions:
        if not isinstance(interaction, dict):
            continue
        request = interaction.get("request") or {}
        response = interaction.get("response") or {}
        status = (response.get("status") or {}).get("code", 0)
        body_field = response.get("body") or {}
        raw = body_field.get("string") if isinstance(body_field, dict) else None
        body: Any
        if not raw or not isinstance(status, int) or not (200 <= status < 300):
            body = None
        else:
            try:
                body = json.loads(raw)
            except (ValueError, TypeError):
                body = None
        key = _request_key(request)
        occ = counts.get(key, 0)
        counts[key] = occ + 1
        triples.append((request, body, occ))
    return triples


def pair_interactions(
    old: list[tuple[dict, Any, int]],
    new: list[tuple[dict, Any, int]],
) -> tuple[list[tuple[tuple[dict, Any, int], tuple[dict, Any, int]]], list, list]:
    """Pair old and new interactions by (method, uri, body-hash, occurrence_index).

    Returns ``(pairs, only_in_old, only_in_new)``.
    """
    old_by_key = {(*_request_key(r), occ): (r, b, occ) for (r, b, occ) in old}
    new_by_key = {(*_request_key(r), occ): (r, b, occ) for (r, b, occ) in new}
    keys_old = set(old_by_key)
    keys_new = set(new_by_key)
    common = keys_old & keys_new
    pairs = [(old_by_key[k], new_by_key[k]) for k in sorted(common)]
    only_in_old = [old_by_key[k] for k in sorted(keys_old - keys_new)]
    only_in_new = [new_by_key[k] for k in sorted(keys_new - keys_old)]
    return pairs, only_in_old, only_in_new


def find_existing_drift_issue(label: str, title_prefix: str) -> int | None:
    """Look up an open issue with the given label whose title starts with ``title_prefix``.

    Returns the issue number, or ``None`` on no match or on any ``gh`` failure
    (failure falls through to issue creation in main()).
    """
    try:
        result = subprocess.run(
            [  # noqa: S607 — relying on PATH lookup for `gh` is intentional
                "gh",
                "issue",
                "list",
                "--label",
                label,
                "--state",
                "open",
                "--json",
                "number,title",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
    except (FileNotFoundError, OSError):
        return None
    if result.returncode != 0:
        return None
    try:
        issues = json.loads(result.stdout)
    except (ValueError, TypeError):
        return None
    for issue in issues:
        title = issue.get("title", "")
        if isinstance(title, str) and title.startswith(title_prefix):
            number = issue.get("number")
            if isinstance(number, int):
                return number
    return None


def _walk_cassettes(root: Path) -> list[Path]:
    return sorted(root.glob("**/*.yaml"))


def _report_summary_line(n_cassettes: int) -> str:
    suffix = "s" if n_cassettes != 1 else ""
    return f"drift: {n_cassettes} cassette{suffix} drifted upstream"


def _post_or_append_issue(label: str, title: str, body: str) -> tuple[bool, str]:
    """Create a new drift issue with the given title, or append a dated comment to an existing one.

    Returns ``(success, message)``. ``success=False`` indicates ``gh`` failed.
    """
    existing = find_existing_drift_issue(label, "drift: ")
    timestamp = _dt.datetime.now(_dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    if existing is not None:
        commented_body = f"### Drift recurred at {timestamp}\n\n{body}"
        try:
            result = subprocess.run(
                ["gh", "issue", "comment", str(existing), "--body-file", "-"],  # noqa: S607 — PATH lookup for `gh` is intentional
                input=commented_body,
                capture_output=True,
                text=True,
                check=False,
            )
        except (FileNotFoundError, OSError):
            return False, "gh not installed"
        if result.returncode != 0:
            return False, f"append to issue #{existing} failed: {result.stderr.strip()}"
        return True, f"appended comment to issue #{existing}"

    try:
        result = subprocess.run(
            ["gh", "issue", "create", "--label", label, "--title", title, "--body-file", "-"],  # noqa: S607 — PATH lookup for `gh` is intentional
            input=body,
            capture_output=True,
            text=True,
            check=False,
        )
    except (FileNotFoundError, OSError):
        return False, "gh not installed"
    if result.returncode != 0:
        return False, f"create issue failed: {result.stderr.strip()}"
    return True, f"created issue: {result.stdout.strip()}"


def main(argv: list[str] | None = None) -> int:  # noqa: PLR0912 — single-pass walk over cassettes, splitting would obscure flow
    parser = argparse.ArgumentParser(description="Detect structural drift between VCR cassette directories.")
    parser.add_argument(
        "--cassette-dir-old",
        default="tests/contract/cassettes",
        help="Directory of committed cassettes (default: %(default)s).",
    )
    parser.add_argument(
        "--cassette-dir-new",
        default="tests/contract/cassettes.new",
        help="Directory of freshly-recorded cassettes (default: %(default)s).",
    )
    parser.add_argument("--report-format", choices=("text", "md"), default="text")
    parser.add_argument(
        "--open-issue",
        action="store_true",
        help="On drift, create or append to a 'drift'-labeled GitHub issue via gh.",
    )
    args = parser.parse_args(argv)

    old_root = Path(args.cassette_dir_old)
    new_root = Path(args.cassette_dir_new)
    if not old_root.is_dir():
        sys.stderr.write(f"ERROR: --cassette-dir-old not found: {old_root}\n")
        return 2
    if not new_root.is_dir():
        sys.stderr.write(f"ERROR: --cassette-dir-new not found: {new_root}\n")
        return 2

    old_cassettes = _walk_cassettes(old_root)
    if not old_cassettes:
        sys.stderr.write(f"WARN: no cassettes found under {old_root}\n")
        return 0

    parsed_total = 0
    parse_failures = 0
    drifted_cassettes: list[tuple[str, list[DriftEntry]]] = []
    warnings: list[str] = []

    for old_path in old_cassettes:
        rel = old_path.relative_to(old_root)
        new_path = new_root / rel
        if not new_path.is_file():
            warnings.append(f"WARN: missing-on-new: {rel}")
            continue
        try:
            old_triples = load_cassette(str(old_path))
            new_triples = load_cassette(str(new_path))
        except CassetteParseError as e:
            warnings.append(f"WARN: skipping {rel} (parse error: {e})")
            parse_failures += 1
            continue
        parsed_total += 1

        pairs, only_old, only_new = pair_interactions(old_triples, new_triples)
        warnings.extend(f"WARN: orchestration: removed {rel} {o[0].get('method')} {o[0].get('uri')}" for o in only_old)
        warnings.extend(f"WARN: orchestration: added {rel} {n[0].get('method')} {n[0].get('uri')}" for n in only_new)

        cassette_entries: list[DriftEntry] = []
        for i, (old_triple, new_triple) in enumerate(pairs):
            old_body = old_triple[1]
            new_body = new_triple[1]
            if old_body is None or new_body is None:
                warnings.append(f"WARN: {rel} interaction {i}: body skipped (not a recordable JSON success)")
                continue
            cassette_entries.extend(diff_shapes(extract_shape(old_body), extract_shape(new_body)))
        if cassette_entries:
            drifted_cassettes.append((str(rel), cassette_entries))

    report_parts = [render_report(name, entries, fmt=args.report_format) for name, entries in drifted_cassettes]
    full_report = "".join(p for p in report_parts if p)
    if full_report:
        sys.stdout.write(full_report)
    for w in warnings:
        sys.stderr.write(w + "\n")

    if args.open_issue and drifted_cassettes:
        title = _report_summary_line(len(drifted_cassettes))
        success, message = _post_or_append_issue("drift", title, full_report)
        if success:
            sys.stderr.write(message + "\n")
        else:
            sys.stderr.write(f"ERROR: drift detected but issue creation failed: {message}\n")

    if parsed_total == 0 and parse_failures > 0:
        return 1
    if drifted_cassettes:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
