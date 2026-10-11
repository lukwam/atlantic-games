"""Entry point for atlg-mcp, with a clear message when the mcp extra is missing."""


def main() -> None:
    """Run the atlantic-games MCP server over stdio."""
    try:
        from atlgames.mcp_server import main as run
    except ImportError as err:
        raise SystemExit(
            f"atlg-mcp needs the mcp extra ({err.name or 'mcp'} is missing). Install it with:\n"
            '    pip install "atlantic-games[mcp]"'
        ) from None
    run()
