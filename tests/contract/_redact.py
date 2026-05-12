"""JSON-path PII redactor for contract-test cassettes.

VCR.py's ``before_record_response`` hook receives a response dict and returns the
(possibly modified) response. This module exposes ``redact_response`` for that
hook. Redaction is path-based, not regex-based: only values at the exact JSON
paths in ``PII_JSON_PATHS`` are replaced. Other ``id`` keys (DNS record IDs,
mailbox IDs, the resource's own ID) survive intact so contract tests can assert
against them.
"""

from __future__ import annotations

import json
from typing import Any

PII_JSON_PATHS: tuple[tuple[str, ...], ...] = (
    ("customer", "id"),
    ("owner", "id"),
    ("registrant", "email"),
    ("registrant", "phone"),
    ("registrant", "streetaddr"),
    ("billing", "iban"),
)

_REDACTED = "REDACTED"


def redact_response(response: dict[str, Any]) -> dict[str, Any]:
    """Replace values at known PII JSON paths with the literal string "REDACTED".

    Returns the response unchanged if the body is missing, empty, or not valid
    JSON. Missing intermediate keys are tolerated.
    """
    body_container = response.get("body")
    if not isinstance(body_container, dict) or "string" not in body_container:
        return response
    raw: bytes = body_container["string"]
    if not raw:
        return response
    try:
        parsed = json.loads(raw)
    except ValueError:
        return response
    if not isinstance(parsed, dict):
        return response
    for path in PII_JSON_PATHS:
        _redact_path(parsed, path)
    body_container["string"] = json.dumps(parsed).encode("utf-8")
    return response


def _redact_path(obj: dict[str, Any], path: tuple[str, ...]) -> None:
    cur: Any = obj
    for key in path[:-1]:
        if not isinstance(cur, dict) or key not in cur:
            return
        cur = cur[key]
    if isinstance(cur, dict) and path[-1] in cur:
        cur[path[-1]] = _REDACTED
