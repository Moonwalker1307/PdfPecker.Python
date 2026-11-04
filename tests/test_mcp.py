import base64
import json
import os
import subprocess
import sys

import pytest

import pdfpecker
from pdfpecker import mcp_server

SRC = os.path.dirname(os.path.dirname(os.path.abspath(pdfpecker.__file__)))


@pytest.fixture
def server(tmp_path):
    return mcp_server.Server([str(tmp_path)])


def call(server, name, **arguments):
    reply = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                           "params": {"name": name, "arguments": arguments}})
    return reply["result"]


def texts(result):
    return "\n".join(c["text"] for c in result["content"] if c["type"] == "text")


def images(result):
    return [base64.b64decode(c["data"]) for c in result["content"] if c["type"] == "image"]


def test_stdio_session(tmp_path):
    messages = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "test", "version": "1"}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
         "params": {"name": "html_to_pdf", "arguments": {"html": "<h1>Hi</h1>", "output_path": "out/hi.pdf"}}},
        {"jsonrpc": "2.0", "id": 4, "method": "nope"},
    ]
    stdin = "".join(json.dumps(m) + "\n" for m in messages) + "not json\n"
    env = dict(os.environ, PYTHONPATH=SRC)
    done = subprocess.run([sys.executable, "-m", "pdfpecker", "mcp"], input=stdin.encode(), capture_output=True,
                          cwd=tmp_path, env=env, timeout=120, check=True)
    replies = [json.loads(line) for line in done.stdout.decode().splitlines()]
    assert [r.get("id") for r in replies] == [1, 2, 3, 4, None]
    assert replies[0]["result"]["protocolVersion"] == "2025-06-18"
    assert replies[0]["result"]["serverInfo"]["name"] == "pdfpecker"
    names = [t["name"] for t in replies[1]["result"]["tools"]]
    assert names == ["html_to_pdf", "markdown_to_pdf", "render_pdf_pages", "pdf_to_text", "pdf_info", "merge_pdfs"]
    assert replies[2]["result"]["isError"] is False
    assert (tmp_path / "out" / "hi.pdf").read_bytes().startswith(b"%PDF")
    assert replies[3]["error"]["code"] == -32601
    assert replies[4]["error"]["code"] == -32700


def test_unknown_protocol_version_gets_the_latest(server):
    reply = server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "1999-01-01"}})
    assert reply["result"]["protocolVersion"] == "2025-06-18"
    assert server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    assert server.handle({"jsonrpc": "2.0", "id": 2, "method": "ping"})["result"] == {}


def test_html_file_with_previews_and_relative_assets(server, tmp_path):
    (tmp_path / "style.css").write_text("p { color: red; }")
    rows = "".join(f"<p>line {i}</p>" for i in range(400))
    (tmp_path / "doc.html").write_text(f"<link rel=stylesheet href=style.css>{rows}")
    result = call(server, "html_to_pdf", html_path="doc.html", output_path="doc.pdf", page_size="100x150",
                  footer_text="Page {page} of {pages}")
    assert result["isError"] is False
    count = pdfpecker.pdf_page_count(str(tmp_path / "doc.pdf"))
    assert count > 3 and f"{count} page(s)" in texts(result)
    shots = images(result)
    assert len(shots) == 3 and all(s.startswith(b"\x89PNG") for s in shots)
    assert "render_pdf_pages" in texts(result)
    assert call(server, "html_to_pdf", html="<p>x", output_path="quiet.pdf", preview=False)["content"][1:] == []


def test_markdown_render_text_info_and_merge(server, tmp_path):
    call(server, "markdown_to_pdf", markdown="# One\n\ntext", output_path="a.pdf", preview=False)
    (tmp_path / "b.md").write_text("# Two")
    call(server, "markdown_to_pdf", markdown_path="b.md", output_path="b.pdf", preview=False)
    merged = call(server, "merge_pdfs", output_path="ab.pdf", pdf_paths=["a.pdf", "b.pdf"])
    assert "2 page(s)" in texts(merged)
    text = texts(call(server, "pdf_to_text", pdf_path="ab.pdf", pages="2"))
    assert text == "--- page 2 ---\nTwo"
    assert "2 page(s)" in texts(call(server, "pdf_info", pdf_path="ab.pdf"))
    rendered = call(server, "render_pdf_pages", pdf_path="ab.pdf", pages="1-2", dpi=30)
    assert len(images(rendered)) == 2 and "2 of 2" in texts(rendered)


def test_errors_are_tool_results(server, tmp_path):
    outside = call(server, "html_to_pdf", html="x", output_path="../escape.pdf")
    assert outside["isError"] and "outside" in texts(outside)
    assert not (tmp_path.parent / "escape.pdf").exists()
    assert call(server, "pdf_info", pdf_path="/etc/hostname")["isError"]
    if os.name != "nt":  # creating a symbolic link needs extra rights on Windows
        os.symlink("/etc", tmp_path / "link")
        assert "outside" in texts(call(server, "pdf_info", pdf_path="link/hostname"))
    assert "either" in texts(call(server, "html_to_pdf", output_path="x.pdf"))
    assert "required" in texts(call(server, "html_to_pdf", html="x"))
    (tmp_path / "bad.pdf").write_bytes(b"not a pdf")
    assert call(server, "render_pdf_pages", pdf_path="bad.pdf")["isError"]
    assert call(server, "html_to_pdf", html="x", output_path="x.pdf", page_size="B9")["isError"]
    assert call(server, "html_to_pdf", html="x", output_path="x.pdf", page_size="AxB")["isError"]
    many = "".join("<p style='break-after: page'>x</p>" for _ in range(25))
    call(server, "html_to_pdf", html=many, output_path="many.pdf", preview=False)
    assert "at most" in texts(call(server, "render_pdf_pages", pdf_path="many.pdf", pages="1-"))
    reply = server.handle({"jsonrpc": "2.0", "id": 9, "method": "tools/call", "params": {"name": "nope"}})
    assert reply["error"]["code"] == -32603
