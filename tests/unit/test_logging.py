"""Tests for stderr-bound JSON logging configuration."""

from __future__ import annotations

import json
import logging
import sys

from gandi_mcp._logging import JSONFormatter, configure_logging


class TestJSONFormatter:
    def test_renders_required_fields_as_json(self) -> None:
        record = logging.LogRecord(
            name="gandi_mcp.test",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="hello %s",
            args=("world",),
            exc_info=None,
        )
        payload = json.loads(JSONFormatter().format(record))
        assert payload["level"] == "INFO"
        assert payload["logger"] == "gandi_mcp.test"
        assert payload["message"] == "hello world"
        assert "time" in payload
        assert "exc_info" not in payload

    def test_includes_exc_info_when_present(self) -> None:
        try:
            raise ValueError("boom")
        except ValueError:
            exc_info = sys.exc_info()
        record = logging.LogRecord(
            name="gandi_mcp.test",
            level=logging.ERROR,
            pathname=__file__,
            lineno=1,
            msg="failed",
            args=(),
            exc_info=exc_info,
        )
        payload = json.loads(JSONFormatter().format(record))
        assert "ValueError: boom" in payload["exc_info"]


class TestConfigureLogging:
    def test_binds_stderr_streamhandler(self) -> None:
        configure_logging(level=logging.DEBUG)
        root = logging.getLogger()
        assert root.level == logging.DEBUG
        assert len(root.handlers) == 1
        handler = root.handlers[0]
        assert isinstance(handler, logging.StreamHandler)
        assert handler.stream is sys.stderr
        assert isinstance(handler.formatter, JSONFormatter)

    def test_idempotent(self) -> None:
        configure_logging()
        configure_logging()
        assert len(logging.getLogger().handlers) == 1
