"""Smoke test: package imports and exposes __version__."""

import gandi_mcp


def test_version_exposed():
    assert hasattr(gandi_mcp, "__version__")
    assert isinstance(gandi_mcp.__version__, str)
    assert gandi_mcp.__version__.count(".") == 2
