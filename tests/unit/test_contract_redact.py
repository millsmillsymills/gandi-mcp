"""Unit tests for the contract-cassette PII redactor."""

from __future__ import annotations

import json

from tests.contract._redact import PII_JSON_PATHS, redact_response


def _resp(body: dict) -> dict:
    return {"body": {"string": json.dumps(body).encode("utf-8")}}


class TestRedactResponse:
    def test_customer_id_redacted(self) -> None:
        resp = _resp({"customer": {"id": "f8a3c9d0-1111-2222-3333-444455556666"}})
        out = redact_response(resp)
        assert json.loads(out["body"]["string"])["customer"]["id"] == "REDACTED"

    def test_owner_id_redacted(self) -> None:
        resp = _resp({"owner": {"id": "f8a3c9d0-1111-2222-3333-444455556666"}})
        out = redact_response(resp)
        assert json.loads(out["body"]["string"])["owner"]["id"] == "REDACTED"

    def test_registrant_email_redacted(self) -> None:
        resp = _resp({"registrant": {"email": "real-customer@example.com"}})
        out = redact_response(resp)
        assert json.loads(out["body"]["string"])["registrant"]["email"] == "REDACTED"

    def test_non_pii_id_left_alone(self) -> None:
        resp = _resp({"records": [{"id": "dns-record-uuid", "name": "@", "type": "A"}]})
        out = redact_response(resp)
        body = json.loads(out["body"]["string"])
        assert body["records"][0]["id"] == "dns-record-uuid"

    def test_top_level_id_left_alone(self) -> None:
        resp = _resp({"id": "domain-record-uuid", "fqdn": "example.com"})
        out = redact_response(resp)
        assert json.loads(out["body"]["string"])["id"] == "domain-record-uuid"

    def test_missing_intermediate_key_is_noop(self) -> None:
        resp = _resp({"foo": "bar"})
        out = redact_response(resp)
        assert json.loads(out["body"]["string"]) == {"foo": "bar"}

    def test_non_dict_at_pii_path_is_noop(self) -> None:
        resp = _resp({"customer": None})
        out = redact_response(resp)
        assert json.loads(out["body"]["string"])["customer"] is None

    def test_non_json_body_returned_unchanged(self) -> None:
        resp = {"body": {"string": b"<html>not json</html>"}}
        out = redact_response(resp)
        assert out["body"]["string"] == b"<html>not json</html>"

    def test_empty_body_returned_unchanged(self) -> None:
        resp = {"body": {"string": b""}}
        out = redact_response(resp)
        assert out["body"]["string"] == b""

    def test_missing_body_key_returned_unchanged(self) -> None:
        resp = {"headers": {}}
        out = redact_response(resp)
        assert "body" not in out

    def test_list_body_returned_unchanged(self) -> None:
        raw_bytes = json.dumps([{"id": "a"}, {"id": "b"}]).encode("utf-8")
        resp = {"body": {"string": raw_bytes}}
        out = redact_response(resp)
        assert json.loads(out["body"]["string"]) == [{"id": "a"}, {"id": "b"}]

    def test_pii_paths_constant_is_a_tuple_of_path_tuples(self) -> None:
        assert isinstance(PII_JSON_PATHS, tuple)
        assert all(isinstance(p, tuple) and all(isinstance(k, str) for k in p) for p in PII_JSON_PATHS)
