"""Entry point for running gandi-mcp as a module."""

from __future__ import annotations

from gandi_mcp.server import create_server


def main() -> None:
    """Start the Gandi MCP server."""
    server = create_server()
    server.run()


if __name__ == "__main__":
    main()
