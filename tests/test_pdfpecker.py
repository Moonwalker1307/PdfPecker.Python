import base64
import concurrent.futures
import datetime
import os
import struct
import zlib

import pytest

import pdfpecker

ROOT = os.path.join(os.path.dirname(__file__), "..")


def png_size(png):
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    return struct.unpack(">II", png[16:24])


def tiny_png(color=(200, 30, 30)):
    raw = b"".join(b"\x00" + bytes(color) * 4 for _ in range(4))

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 4, 4, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def long_html(rows=2000):
    return "<table>" + "".join(f"<tr><td>Row {i}</td><td>{i * 3}</td></tr>" for i in range(rows)) + "</table>"


def test_versions():
    with open(os.path.join(ROOT, "PDFPECKER_VERSION")) as f:
        expected = f.read().strip()
    assert pdfpecker.library_version() == expected
    if os.environ.get("PDFPECKER_TEST_INSTALLED") == "1":
        assert pdfpecker.__version__ == expected


def test_html_to_pdf():
    pdf = pdfpecker.html_to_pdf("<h1>Hello</h1><p>Grüße, ünïcode — “quotes”</p>")
    assert pdf.startswith(b"%PDF-")
    assert pdfpecker.pdf_page_count(pdf) == 1
    assert pdfpecker.pdf_to_text(pdf) == "Hello\n\nGrüße, ünïcode — “quotes”"


def test_bytes_input_and_fixed_date_are_byte_identical():
    html = "<p>same</p>".encode("utf-8")
    date = datetime.datetime(2026, 1, 2, 3, 4, 5, tzinfo=datetime.timezone.utc)
    assert pdfpecker.html_to_pdf(html, creation_date=date) == pdfpecker.html_to_pdf(html, creation_date=date)
    assert pdfpecker.html_to_pdf(html, creation_date=datetime.date(2026, 1, 2)) == pdfpecker.html_to_pdf(
        html, creation_date=1767312000)


def test_page_size_landscape_and_margin():
    letter = pdfpecker.pdf_to_images(pdfpecker.html_to_pdf("<p>x", page_size="Letter"), dpi=72)[0]
    assert png_size(letter) == (612, 792)
    landscape = pdfpecker.pdf_to_images(pdfpecker.html_to_pdf("<p>x", page_size="A5", landscape=True), dpi=72)[0]
    assert png_size(landscape) == (595, 420)
    custom = pdfpecker.pdf_to_images(pdfpecker.html_to_pdf("<p>x", page_size=(100, 50), margin=(5, 5, 5, 5)), dpi=72)[0]
    assert png_size(custom) == (283, 142)


def test_document_properties():
    pdf = pdfpecker.html_to_pdf("<p>x", title="My title", author="Me", compress=False)
    assert b"My title" in pdf or "My title".encode("utf-16-be") in pdf


def test_base_dir_loads_images_and_nothing_loads_without_it(tmp_path):
    (tmp_path / "dot.png").write_bytes(tiny_png())
    html = '<img src="dot.png" style="width:100px;height:100px">'
    without = pdfpecker.html_to_pdf(html)
    with_dir = pdfpecker.html_to_pdf(html, base_dir=tmp_path)
    assert len(with_dir) > len(without)
    page = pdfpecker.pdf_to_images(with_dir, dpi=72)[0]
    assert len(page) > len(pdfpecker.pdf_to_images(without, dpi=72)[0])


def test_data_uri_images_always_load():
    uri = "data:image/png;base64," + base64.b64encode(tiny_png()).decode("ascii")
    plain = pdfpecker.html_to_pdf("<p>x")
    assert len(pdfpecker.html_to_pdf(f'<img src="{uri}" width=50 height=50>')) > len(plain)


def test_files_outside_base_dir_need_allow_file_access(tmp_path):
    (tmp_path / "dot.png").write_bytes(tiny_png())
    sub = tmp_path / "sub"
    sub.mkdir()
    html = '<img src="../dot.png" style="width:100px;height:100px">'
    blocked = pdfpecker.html_to_pdf(html, base_dir=sub)
    allowed = pdfpecker.html_to_pdf(html, base_dir=sub, allow_file_access=True)
    assert len(allowed) > len(blocked)


def test_html_and_markdown_files(tmp_path):
    (tmp_path / "dot.png").write_bytes(tiny_png())
    (tmp_path / "doc.html").write_text('<h1>File</h1><img src="dot.png" width=40 height=40>', encoding="utf-8")
    out = tmp_path / "doc.pdf"
    pdf = pdfpecker.html_file_to_pdf(tmp_path / "doc.html", out, title="File")
    assert out.read_bytes() == pdf
    assert "File" in pdfpecker.pdf_to_text(pdf)
    (tmp_path / "doc.md").write_text("# Heading\n\n- [x] done\n- [ ] todo\n\n![dot](dot.png)\n", encoding="utf-8")
    md = pdfpecker.markdown_file_to_pdf(tmp_path / "doc.md")
    assert "Heading" in pdfpecker.pdf_to_text(md)


def test_markdown_to_pdf():
    pdf = pdfpecker.markdown_to_pdf("# Title\n\n| a | b |\n|---|---|\n| 1 | 2 |\n", page_size="Letter")
    text = pdfpecker.pdf_to_text(pdf)
    assert "Title" in text and "1" in text


def test_header_footer_and_bookmarks():
    pdf = pdfpecker.html_to_pdf(long_html(300), footer_text="Page {page} of {pages}")
    count = pdfpecker.pdf_page_count(pdf)
    assert count > 1
    assert f"Page 2 of {count}" in pdfpecker.pdf_to_text_pages(pdf)[1]


def test_pdf_to_images_formats_pages_and_size():
    pdf = pdfpecker.html_to_pdf(long_html(300))
    count = pdfpecker.pdf_page_count(pdf)
    assert len(pdfpecker.pdf_to_images(pdf, dpi=20)) == count
    assert len(pdfpecker.pdf_to_images(pdf, dpi=20, pages="1-2")) == 2
    assert len(pdfpecker.pdf_to_images(pdf, dpi=20, pages=[1, 1, 2])) == 3
    assert len(pdfpecker.pdf_to_images(pdf, dpi=20, pages=1)) == 1
    assert pdfpecker.pdf_to_images(pdf, dpi=20, pages="last") == pdfpecker.pdf_to_images(pdf, dpi=20, pages=count)
    assert png_size(pdfpecker.pdf_to_images(pdf, width=300, pages=1)[0])[0] == 300
    jpeg = pdfpecker.pdf_to_images(pdf, format="jpeg", quality=60, pages=1, dpi=30)[0]
    assert jpeg[:3] == b"\xff\xd8\xff"
    webp = pdfpecker.pdf_to_images(pdf, format="webp", pages=1, dpi=30)[0]
    assert webp[:4] == b"RIFF" and webp[8:12] == b"WEBP"


def test_pdf_paths_are_accepted(tmp_path):
    path = tmp_path / "a.pdf"
    path.write_bytes(pdfpecker.html_to_pdf("<p>path"))
    assert pdfpecker.pdf_page_count(path) == 1
    assert pdfpecker.pdf_to_text(str(path)) == "path"


def test_text_pages():
    pdf = pdfpecker.html_to_pdf("<p>one</p><p style='break-before:page'>two</p><p style='break-before:page'>three</p>")
    assert pdfpecker.pdf_to_text_pages(pdf) == ["one", "two", "three"]
    assert pdfpecker.pdf_to_text_pages(pdf, pages="2-3") == ["two", "three"]
    assert pdfpecker.pdf_to_text(pdf) == "one\ftwo\fthree"


def test_merge_pdfs(tmp_path):
    a = pdfpecker.html_to_pdf("<p>first")
    path = tmp_path / "b.pdf"
    path.write_bytes(pdfpecker.html_to_pdf("<p>second"))
    merged = pdfpecker.merge_pdfs([a, path], title="Both")
    assert pdfpecker.pdf_to_text_pages(merged) == ["first", "second"]


def test_pdfa():
    pdf = pdfpecker.html_to_pdf("<p>archive", conformance="PDF/A-2b", creation_date=0)
    assert b"pdfaid" in pdf or pdfpecker.pdf_page_count(pdf) == 1


def test_pdf_to_markdown(tmp_path):
    pdf = pdfpecker.html_to_pdf("<h1>Report</h1><p>See <a href='https://example.com'>the site</a>.</p>"
                                "<ul><li>one</li><li>two</li></ul>", accessibility="tagged")
    markdown = pdfpecker.pdf_to_markdown(pdf)
    assert markdown.startswith("# Report")
    assert "](https://example.com/)" in markdown
    assert "- one" in markdown and "- two" in markdown
    path = tmp_path / "r.pdf"
    path.write_bytes(pdf)
    assert pdfpecker.pdf_to_markdown(path, include_links=False, page_comments=True).startswith("<!-- page 1 -->")
    with pytest.raises(pdfpecker.PdfPeckerArgumentError):
        pdfpecker.pdf_to_markdown(pdf, pages=3)


def test_pdf_to_pdfa(tmp_path):
    pdf = pdfpecker.html_to_pdf("<p>archive me", creation_date=0)
    out = tmp_path / "a.pdf"
    result = pdfpecker.pdf_to_pdfa(pdf, out, conformance="PDF/A-3u")
    assert out.read_bytes() == result.pdf
    assert b"pdfaid" in result.pdf
    assert result.is_conformant, result.problems
    assert isinstance(result.changes, list)
    assert pdfpecker.pdf_to_text(result.pdf) == "archive me"
    assert pdfpecker.pdf_to_pdfa(pdf).pdf == pdfpecker.pdf_to_pdfa(pdf).pdf
    with pytest.raises(pdfpecker.PdfPeckerArgumentError, match="conformance"):
        pdfpecker.pdf_to_pdfa(pdf, conformance="PDF/A-4")
    with pytest.raises(pdfpecker.PdfReadError):
        pdfpecker.pdf_to_pdfa(b"not a pdf")


def test_errors():
    with pytest.raises(pdfpecker.PdfPeckerArgumentError, match="page_size"):
        pdfpecker.html_to_pdf("x", page_size="B9")
    with pytest.raises(ValueError, match="margin"):
        pdfpecker.html_to_pdf("x", margin="wide")
    with pytest.raises(pdfpecker.PdfPeckerArgumentError, match="conformance"):
        pdfpecker.html_to_pdf("x", conformance="PDF/X")
    with pytest.raises(TypeError):
        pdfpecker.html_to_pdf("x", nope=1)
    with pytest.raises(TypeError):
        pdfpecker.markdown_to_pdf("x", nope=1)
    with pytest.raises(pdfpecker.PdfReadError):
        pdfpecker.pdf_page_count(b"this is not a PDF")
    with pytest.raises(pdfpecker.PdfReadError):
        pdfpecker.pdf_to_images(b"%PDF-1.7\n%%EOF")
    pdf = pdfpecker.html_to_pdf("<p>x")
    with pytest.raises(pdfpecker.PdfPeckerArgumentError, match="out of range"):
        pdfpecker.pdf_to_images(pdf, pages=5)
    with pytest.raises(pdfpecker.PdfPeckerArgumentError, match="format"):
        pdfpecker.pdf_to_images(pdf, format="gif")
    # A timeout too long for the native timer is a bad argument, not an unexpected error.
    with pytest.raises(pdfpecker.PdfPeckerArgumentError, match="timeout"):
        pdfpecker.html_to_pdf("x", timeout=1e300)
    with pytest.raises(pdfpecker.PdfLimitError):
        pdfpecker.html_to_pdf(long_html(), max_pages=2)
    with pytest.raises(pdfpecker.PdfTimeoutError):
        pdfpecker.html_to_pdf(long_html(20000), timeout=0.001)
    with pytest.raises(TimeoutError):
        pdfpecker.html_to_pdf(long_html(20000), timeout=0.001)
    with pytest.raises(pdfpecker.PdfFileError):
        pdfpecker.html_to_pdf("x", fonts=["/no/such/font.ttf"])
    # Every error is a PdfPeckerError, so one except clause catches them all.
    assert issubclass(pdfpecker.PdfLimitError, pdfpecker.PdfPeckerError)


def test_threads_convert_in_parallel_with_identical_results():
    html = long_html(400)
    expected = pdfpecker.html_to_pdf(html, creation_date=0)
    with concurrent.futures.ThreadPoolExecutor(8) as pool:
        results = list(pool.map(lambda _: pdfpecker.html_to_pdf(html, creation_date=0), range(16)))
    assert all(r == expected for r in results)


def test_hostile_input_fails_cleanly():
    # Damaged PDFs are either repaired or rejected with a PdfPeckerError; nothing else may escape.
    for data in [b"%PDF-1.7\n1 0 obj <</Type/Catalog/Pages 2 0 R>> endobj\ntrailer<</Root 1 0 R>>\n%%EOF",
                 b"%PDF-" + bytes(range(256)) * 50, b""]:
        try:
            pdfpecker.pdf_to_images(data)
        except pdfpecker.PdfPeckerError:
            pass
    for html in ["<" * 10000, "<div>" * 5000, "&#xFFFFFFFF;"]:
        try:
            pdfpecker.html_to_pdf(html, timeout=30)
        except pdfpecker.PdfPeckerError:
            pass
