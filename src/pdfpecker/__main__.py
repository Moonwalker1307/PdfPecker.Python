"""The pdfpecker command. Its one subcommand runs the MCP server:

    pdfpecker mcp [--root DIR ...]       # or: uvx pdfpecker mcp, python -m pdfpecker mcp
"""
import sys
from typing import List, Optional


def main(argv: Optional[List[str]] = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if args[:1] == ["mcp"]:
        from .mcp_server import main as mcp_main

        return mcp_main(args[1:])
    sys.stderr.write("usage: pdfpecker mcp [--root DIR ...]\n\n"
                     "Runs the PdfPecker MCP server over stdio. The Python API is documented in help(pdfpecker).\n")
    return 0 if args[:1] in (["-h"], ["--help"]) else 2


if __name__ == "__main__":
    sys.exit(main())
