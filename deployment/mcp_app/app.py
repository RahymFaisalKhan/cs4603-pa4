"""Standalone streamable-HTTP MCP service for Bonus C."""

import os
import sys
from pathlib import Path

# Running a nested script puts only ``deployment/mcp_app`` on sys.path.
# Add the packaged source root so the shared tool definitions are importable.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.mcp_server import mcp

if __name__ == "__main__":
    # Databricks Apps requires the process to listen on every interface and
    # supplies its port at runtime. TLS and user/service authentication are
    # enforced by the Databricks Apps reverse proxy.
    mcp.settings.host = "0.0.0.0"
    mcp.settings.port = int(os.environ.get("DATABRICKS_APP_PORT", "8000"))
    # Databricks Apps only applies bearer-token API authentication to routes
    # below /api. Keep FastMCP's streamable HTTP protocol on that protected
    # prefix so headless agents can call it with an OAuth token.
    mcp.settings.streamable_http_path = "/api/mcp"
    mcp.settings.transport_security.enable_dns_rebinding_protection = False
    mcp.run(transport="streamable-http")
