"""Test deprecated mcp_server.py module."""

import sys
from pathlib import Path

import pytest


def test_mcp_server_import_warns():
    """Test that importing mcp_server shows deprecation warning."""
    # Add project root to path
    project_root = Path(__file__).parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

    # Clear the module from cache if it exists
    if "mcp_server" in sys.modules:
        del sys.modules["mcp_server"]

    # Import should show deprecation warning
    with pytest.warns(DeprecationWarning, match="mcp_server is deprecated"):
        import mcp_server  # noqa: F401
