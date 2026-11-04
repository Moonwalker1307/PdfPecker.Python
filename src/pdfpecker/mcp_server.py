"""A Model Context Protocol server for PdfPecker, so AI agents and chat apps can make, look at and read PDFs.

    pdfpecker mcp [--root DIR ...]          # or: uvx pdfpecker mcp, python -m pdfpecker mcp

It speaks MCP over stdio (JSON-RPC 2.0, one message per line) with only the standard library, so it needs nothing but
this package. The tools read and write files only inside the root folders, because the client's model chooses the
paths: the current folder by default, or ~/PdfPecker when the server starts in the filesystem's root, as chat apps
often start servers. Documents load images, stylesheets and fonts from their own folder and never
from the network.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import traceback
from typing import Any, Callable, Dict, List, Optional

import pdfpecker

_PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
_MAX_IMAGES = 20  # pages returned by one render call, so a long PDF does not flood the client's context

_PAGE_OPTIONS = {
    "page_size": {"type": "string",
                  "description": "A3, A4, A5, Letter or Legal (default A4), or WIDTHxHEIGHT in mm such as 100x150. "
                                 "A CSS @page size rule wins."},
    "landscape": {"type": "boolean", "description": "Turn the page size sideways."},
    "margin": {"type": "number", "description": "Page margins in points (72 per inch), default 36. @page margin wins."},
    "title": {"type": "string", "description": "The document title; default: the HTML <title>."},
    "author": {"type": "string"},
    "language": {"type": "string", "description": "The document language, such as en-GB."},
    "header_text": {"type": "string", "description": "A line at the top of every page; {page} and {pages} are replaced."},
    "footer_text": {"type": "string", "description": "A line at the bottom of every page, such as \"Page {page} of {pages}\"."},
    "fonts": {"type": "array", "items": {"type": "string"},
              "description": "Font files or folders (.ttf, .otf, .woff2) that CSS font-family can name. Needed for "
                             "scripts other than Latin, Greek and Cyrillic."},
    "use_system_fonts": {"type": "boolean", "description": "Also use the fonts installed on this machine."},
    "conformance": {"type": "string", "enum": ["PDF/A-2b", "PDF/A-3b", "PDF/A-2u", "PDF/A-3u", "PDF/A-4", "PDF/A-4f"],
                    "description": "Write an archival PDF/A file."},
    "accessibility": {"type": "string", "enum": ["tagged", "PDF/UA-1", "PDF/UA-2"],
                      "description": "Write a tagged (accessible) PDF."},
    "preview": {"type": "boolean",
                "description": "Also return images of the first pages (up to 3, at 60 dpi) to check the layout. Default true."},
}

_PAGES = {"type": "string", "description": "Pages such as \"1\", \"1-3,5\", \"8-\" or \"last\", numbered from 1. Default: all."}

_TOOLS: List[Dict[str, Any]] = [
    {
        "name": "html_to_pdf",
        "title": "HTML to PDF",
        "description": "Converts HTML with CSS to a PDF file. Give the HTML inline or as a file; relative image, CSS and "
                       "font paths resolve against the HTML file's folder (or the root for inline HTML). Use @page rules "
                       "for size, margins, running headers and page numbers. No JavaScript runs and nothing loads from "
                       "the network. Returns the page count and, by default, previews of the first pages.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "output_path": {"type": "string", "description": "The PDF file to write."},
                "html": {"type": "string", "description": "The HTML document. Give this or html_path."},
                "html_path": {"type": "string", "description": "An HTML file to convert. Give this or html."},
                **_PAGE_OPTIONS,
            },
            "required": ["output_path"],
        },
    },
    {
        "name": "markdown_to_pdf",
        "title": "Markdown to PDF",
        "description": "Converts Markdown (CommonMark with GitHub tables, task lists, strikethrough and footnotes) to "
                       "a PDF file. Images resolve against the Markdown file's folder.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "output_path": {"type": "string", "description": "The PDF file to write."},
                "markdown": {"type": "string", "description": "The Markdown text. Give this or markdown_path."},
                "markdown_path": {"type": "string", "description": "A Markdown file to convert. Give this or markdown."},
                **_PAGE_OPTIONS,
            },
            "required": ["output_path"],
        },
    },
    {
        "name": "render_pdf_pages",
        "title": "Look at PDF pages",
        "description": f"Renders PDF pages to PNG images and returns them, to check a layout. At most {_MAX_IMAGES} "
                       "pages per call; for a long PDF, look at the first, a middle and the last page.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "pdf_path": {"type": "string"},
                "pages": {**_PAGES, "description": "Pages such as \"1\", \"1-3,5\" or \"last\". Default: \"1\"."},
                "dpi": {"type": "number", "description": "Resolution, default 80; 150 for small detail."},
                "password": {"type": "string"},
            },
            "required": ["pdf_path"],
        },
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "pdf_to_text",
        "title": "Read PDF text",
        "description": "Extracts the text of a PDF in reading order, with a line marking the start of each page.",
        "inputSchema": {
            "type": "object",
            "properties": {"pdf_path": {"type": "string"}, "pages": _PAGES, "password": {"type": "string"}},
            "required": ["pdf_path"],
        },
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "pdf_to_markdown",
        "title": "PDF to Markdown",
        "description": "Converts a PDF, any PDF, to GitHub Flavored Markdown: headings, paragraphs, lists and tables in "
                       "reading order. Better than pdf_to_text for documents with structure. Returns the Markdown, or "
                       "writes it to output_path when given.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "pdf_path": {"type": "string"},
                "pages": _PAGES,
                "output_path": {"type": "string", "description": "A .md file to write instead of returning the text."},
                "page_comments": {"type": "boolean", "description": "Start each page with <!-- page N -->."},
                "password": {"type": "string"},
            },
            "required": ["pdf_path"],
        },
    },
    {
        "name": "pdf_to_pdfa",
        "title": "Convert PDF to PDF/A",
        "description": "Converts an existing PDF to PDF/A for long-term archiving (fonts embedded, colours made device "
                       "independent, scripts removed; text stays text). Returns what it changed and anything it could "
                       "not fix. Encrypted and signed PDFs are refused.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "pdf_path": {"type": "string"},
                "output_path": {"type": "string", "description": "The PDF/A file to write."},
                "conformance": {"type": "string", "enum": ["PDF/A-2b", "PDF/A-2u", "PDF/A-3b", "PDF/A-3u"],
                                "description": "Default PDF/A-2b; the U levels also keep the text searchable."},
            },
            "required": ["pdf_path", "output_path"],
        },
    },
    {
        "name": "pdf_info",
        "title": "PDF page count",
        "description": "Returns the number of pages and the file size of a PDF.",
        "inputSchema": {
            "type": "object",
            "properties": {"pdf_path": {"type": "string"}, "password": {"type": "string"}},
            "required": ["pdf_path"],
        },
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "merge_pdfs",
        "title": "Merge PDFs",
        "description": "Merges PDF files into one, in the order given, keeping links, bookmarks and form fields.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "output_path": {"type": "string", "description": "The PDF file to write."},
                "pdf_paths": {"type": "array", "items": {"type": "string"}, "minItems": 1},
                "title": {"type": "string"},
            },
            "required": ["output_path", "pdf_paths"],
        },
    },
]


class ToolError(Exception):
    """A failure the model can fix, such as a path outside the roots; it is reported as a tool result, not a crash."""


class Server:
    def __init__(self, roots: List[str]) -> None:
        self.roots = [os.path.realpath(r) for r in roots]
        self.handlers: Dict[str, Callable[[Dict[str, Any]], List[Dict[str, Any]]]] = {
            "html_to_pdf": self.html_to_pdf,
            "markdown_to_pdf": self.markdown_to_pdf,
            "render_pdf_pages": self.render_pdf_pages,
            "pdf_to_text": self.pdf_to_text,
            "pdf_to_markdown": self.pdf_to_markdown,
            "pdf_to_pdfa": self.pdf_to_pdfa,
            "pdf_info": self.pdf_info,
            "merge_pdfs": self.merge_pdfs,
        }

    # --- JSON-RPC ---

    def handle(self, message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        method = message.get("method")
        if "id" not in message:
            return None  # a notification, such as notifications/initialized
        request_id = message["id"]
        params = message.get("params") or {}
        try:
            if method == "initialize":
                asked = params.get("protocolVersion")
                result: Dict[str, Any] = {
                    "protocolVersion": asked if asked in _PROTOCOL_VERSIONS else _PROTOCOL_VERSIONS[0],
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "pdfpecker", "title": "PdfPecker", "version": pdfpecker.__version__},
                    "instructions": "Write HTML with print CSS, convert it with html_to_pdf, look at the previews, fix "
                                    "and convert again. Files are read and written only inside: "
                                    + ", ".join(self.roots),
                }
            elif method == "ping":
                result = {}
            elif method == "tools/list":
                result = {"tools": _TOOLS}
            elif method == "tools/call":
                result = self.call(params.get("name"), params.get("arguments") or {})
            else:
                return _error(request_id, -32601, f"method not found: {method}")
        except Exception as e:  # never let one bad request end the server
            traceback.print_exc(file=sys.stderr)
            return _error(request_id, -32603, str(e))
        return {"jsonrpc": "2.0", "id": request_id, "result": result}

    def call(self, name: Any, arguments: Dict[str, Any]) -> Dict[str, Any]:
        handler = self.handlers.get(name)
        if handler is None:
            raise ValueError(f"unknown tool: {name}")
        try:
            return {"content": handler(arguments), "isError": False}
        except (ToolError, pdfpecker.PdfPeckerError, OSError, ValueError, TypeError) as e:
            return {"content": [_text(f"error: {e}")], "isError": True}

    # --- tools ---

    def html_to_pdf(self, a: Dict[str, Any]) -> List[Dict[str, Any]]:
        return self._convert(a, "html", pdfpecker.html_to_pdf)

    def markdown_to_pdf(self, a: Dict[str, Any]) -> List[Dict[str, Any]]:
        return self._convert(a, "markdown", pdfpecker.markdown_to_pdf)

    def _convert(self, a: Dict[str, Any], kind: str, convert: Callable[..., bytes]) -> List[Dict[str, Any]]:
        output = self.path(_required(a, "output_path"))
        source, source_path = a.get(kind), a.get(kind + "_path")
        if (source is None) == (source_path is None):
            raise ToolError(f"give either {kind} or {kind}_path")
        if source_path is not None:
            path = self.path(source_path)
            with open(path, "rb") as f:
                source = f.read()
            base_dir = os.path.dirname(path)
        else:
            base_dir = self.roots[0]
        options: Dict[str, Any] = {"base_dir": base_dir, "timeout": 120}
        for key in ("landscape", "margin", "title", "author", "language", "header_text", "footer_text",
                    "use_system_fonts", "conformance", "accessibility"):
            if a.get(key) is not None:
                options[key] = a[key]
        if a.get("page_size"):
            options["page_size"] = _page_size(a["page_size"])
        if a.get("fonts"):
            options["fonts"] = [self.path(f) for f in a["fonts"]]
        pdf = convert(source, **options)
        os.makedirs(os.path.dirname(output), exist_ok=True)
        with open(output, "wb") as f:
            f.write(pdf)
        count = pdfpecker.pdf_page_count(pdf)
        content = [_text(f"Wrote {output}: {count} page(s), {len(pdf):,} bytes.")]
        if a.get("preview", True):
            shown = min(count, 3)
            content.extend(_image(png) for png in pdfpecker.pdf_to_images(pdf, dpi=60, pages=f"1-{shown}"))
            if count > shown:
                content.append(_text(f"Showing pages 1-{shown}; render_pdf_pages shows the others."))
        return content

    def render_pdf_pages(self, a: Dict[str, Any]) -> List[Dict[str, Any]]:
        path = self.path(_required(a, "pdf_path"))
        password = a.get("password")
        pages = str(a.get("pages") or "1")
        total = pdfpecker.pdf_page_count(path, password=password)
        wanted = len(_parse_pages(pages, total) or [])
        if wanted > _MAX_IMAGES:
            raise ToolError(f"that is {wanted} pages; ask for at most {_MAX_IMAGES} at a time")
        images = pdfpecker.pdf_to_images(path, dpi=float(a.get("dpi") or 80), pages=pages, password=password,
                                         timeout=120)
        if len(images) > _MAX_IMAGES:
            raise ToolError(f"that is {len(images)} pages; ask for at most {_MAX_IMAGES} at a time")
        return [_text(f"{len(images)} of {total} page(s) of {path}.")] + [_image(png) for png in images]

    def pdf_to_text(self, a: Dict[str, Any]) -> List[Dict[str, Any]]:
        path = self.path(_required(a, "pdf_path"))
        texts = pdfpecker.pdf_to_text_pages(path, pages=a.get("pages"), password=a.get("password"), timeout=120)
        numbers = _page_numbers(a.get("pages"), len(texts), path, a.get("password"))
        return [_text("\n\n".join(f"--- page {n} ---\n{t}" for n, t in zip(numbers, texts)))]

    def pdf_to_markdown(self, a: Dict[str, Any]) -> List[Dict[str, Any]]:
        path = self.path(_required(a, "pdf_path"))
        markdown = pdfpecker.pdf_to_markdown(path, pages=a.get("pages"), page_comments=bool(a.get("page_comments")),
                                             password=a.get("password"), timeout=120)
        if a.get("output_path") is None:
            return [_text(markdown)]
        output = self.path(a["output_path"])
        os.makedirs(os.path.dirname(output), exist_ok=True)
        with open(output, "w", encoding="utf-8", newline="\n") as f:
            f.write(markdown)
        return [_text(f"Wrote {output}: {len(markdown):,} characters.")]

    def pdf_to_pdfa(self, a: Dict[str, Any]) -> List[Dict[str, Any]]:
        path = self.path(_required(a, "pdf_path"))
        output = self.path(_required(a, "output_path"))
        os.makedirs(os.path.dirname(output), exist_ok=True)
        result = pdfpecker.pdf_to_pdfa(path, output, conformance=a.get("conformance") or "PDF/A-2b", timeout=120)
        lines = [f"Wrote {output}: {len(result.pdf):,} bytes."]
        lines += (["Changed:"] + [f"- {c}" for c in result.changes]) if result.changes else []
        lines += (["Still breaks the PDF/A rules:"] + [f"- {p}" for p in result.problems] if result.problems
                  else ["No PDF/A problems left that the conversion checks for; veraPDF gives the final word."])
        return [_text("\n".join(lines))]

    def pdf_info(self, a: Dict[str, Any]) -> List[Dict[str, Any]]:
        path = self.path(_required(a, "pdf_path"))
        count = pdfpecker.pdf_page_count(path, password=a.get("password"))
        return [_text(f"{path}: {count} page(s), {os.path.getsize(path):,} bytes.")]

    def merge_pdfs(self, a: Dict[str, Any]) -> List[Dict[str, Any]]:
        output = self.path(_required(a, "output_path"))
        inputs = a.get("pdf_paths")
        if not isinstance(inputs, list) or not inputs:
            raise ToolError("pdf_paths must be a list of PDF files")
        pdf = pdfpecker.merge_pdfs([self.path(p) for p in inputs], title=a.get("title"), timeout=120)
        os.makedirs(os.path.dirname(output), exist_ok=True)
        with open(output, "wb") as f:
            f.write(pdf)
        return [_text(f"Wrote {output}: {pdfpecker.pdf_page_count(pdf)} page(s), {len(pdf):,} bytes.")]

    # The model picks the paths, so each one must resolve, after following links, to a place inside a root.
    def path(self, value: Any) -> str:
        if not isinstance(value, str) or not value:
            raise ToolError("a path must be a non-empty string")
        full = os.path.realpath(os.path.join(self.roots[0], os.path.expanduser(value)))
        for root in self.roots:
            if full == root or full.startswith(root.rstrip(os.sep) + os.sep):
                return full
        raise ToolError(f"{value} is outside the folders this server may use ({', '.join(self.roots)})")


def _required(a: Dict[str, Any], key: str) -> Any:
    if a.get(key) is None:
        raise ToolError(f"{key} is required")
    return a[key]


def _page_size(value: str):
    if "x" in value.lower():
        width, height = value.lower().split("x", 1)
        return (float(width), float(height))
    return value


def _page_numbers(pages: Optional[str], count: int, path: str, password: Optional[str]) -> List[int]:
    # Label the pages with their real numbers when the selection is a plain list or range.
    if not pages:
        return list(range(1, count + 1))
    numbers = _parse_pages(str(pages), pdfpecker.pdf_page_count(path, password=password))
    return numbers if numbers is not None and len(numbers) == count else list(range(1, count + 1))


def _parse_pages(pages: str, total: int) -> Optional[List[int]]:
    """The page numbers of a selection such as "1-3,5" or "last", or None when the library's parser must decide."""
    numbers: List[int] = []
    try:
        for part in pages.replace(" ", "").split(","):
            part = part.replace("last", str(total))
            if "-" in part:
                start, end = part.split("-", 1)
                first, last = int(start or 1), int(end or total)
                if abs(last - first) > 100_000:
                    return None
                step = 1 if last >= first else -1
                numbers.extend(range(first, last + step, step))
            elif part:
                numbers.append(int(part))
    except ValueError:
        return None
    return numbers


def _text(text: str) -> Dict[str, Any]:
    return {"type": "text", "text": text}


def _image(png: bytes) -> Dict[str, Any]:
    return {"type": "image", "data": base64.b64encode(png).decode("ascii"), "mimeType": "image/png"}


def _error(request_id: Any, code: int, message: str) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def serve(server: Server, stdin=None, stdout=None) -> None:
    stdin = stdin or sys.stdin.buffer
    stdout = stdout or sys.stdout.buffer
    for line in stdin:
        if not line.strip():
            continue
        try:
            message = json.loads(line)
        except ValueError:
            reply: Optional[Dict[str, Any]] = _error(None, -32700, "parse error")
        else:
            reply = server.handle(message) if isinstance(message, dict) else _error(None, -32600, "invalid request")
        if reply is not None:
            stdout.write(json.dumps(reply, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n")
            stdout.flush()


def _default_root() -> str:
    # Chat apps often start servers in the filesystem's root, where the current folder would open every file on the
    # machine to the model; a folder of its own in the home folder is used instead.
    cwd = os.getcwd()
    if os.path.dirname(cwd) != cwd:
        return cwd
    folder = os.path.join(os.path.expanduser("~"), "PdfPecker")
    os.makedirs(folder, exist_ok=True)
    return folder


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="pdfpecker mcp", description=__doc__.split("\n\n")[0])
    parser.add_argument("--root", action="append", default=[],
                        help="a folder the tools may read and write (repeatable); default: the current folder, or ~/PdfPecker "
                             "when that is the filesystem's root")
    parser.add_argument("--version", action="version",
                        version=f"pdfpecker mcp {pdfpecker.__version__} (PdfPecker {pdfpecker.library_version()})")
    args = parser.parse_args(argv)
    roots = args.root or [_default_root()]
    for root in roots:
        if not os.path.isdir(root):
            parser.error(f"--root {root} is not a folder")
    serve(Server(roots))
    return 0


if __name__ == "__main__":
    sys.exit(main())
