"""PdfPecker: fast HTML and Markdown to PDF, and PDF to images and text, with no browser and no dependencies.

    import pdfpecker

    pdf = pdfpecker.html_to_pdf("<h1>Invoice</h1><p>Total: 42 EUR</p>")
    pdf = pdfpecker.html_file_to_pdf("templates/invoice.html", "invoice.pdf")
    pngs = pdfpecker.pdf_to_images(pdf, dpi=96)
    text = pdfpecker.pdf_to_text(pdf)

PdfPecker is a .NET library compiled ahead of time into a native library that ships inside the wheel, so no .NET
runtime is needed. It runs no JavaScript and never goes online: images, stylesheets and fonts load from base_dir.
Every function is thread-safe and releases the GIL while it works.
"""
from __future__ import annotations

import datetime as _dt
import os
from typing import Iterable, List, Optional, Sequence, Tuple, Union

from . import _native
from ._errors import (PdfFileError, PdfLimitError, PdfPasswordError, PdfPeckerArgumentError, PdfPeckerError,
                      PdfReadError, PdfTimeoutError)

__all__ = [
    "html_to_pdf", "html_file_to_pdf", "markdown_to_pdf", "markdown_file_to_pdf",
    "pdf_to_images", "pdf_page_count", "pdf_to_text", "pdf_to_text_pages", "merge_pdfs",
    "library_version", "__version__",
    "PdfPeckerError", "PdfPeckerArgumentError", "PdfReadError", "PdfPasswordError", "PdfLimitError",
    "PdfTimeoutError", "PdfFileError",
]

try:
    from importlib.metadata import version as _dist_version

    __version__ = _dist_version("pdfpecker")
except Exception:  # running from a source checkout
    __version__ = "0+unknown"

PathLike = Union[str, "os.PathLike[str]"]
PageSize = Union[str, Tuple[float, float]]
Margin = Union[float, Tuple[float, float, float, float]]
Date = Union[_dt.datetime, _dt.date, int, float]


def library_version() -> str:
    """The version of the PdfPecker .NET library inside this package."""
    return _native.version()


def html_to_pdf(
    html: Union[str, bytes],
    *,
    base_dir: Optional[PathLike] = None,
    page_size: Optional[PageSize] = None,
    landscape: bool = False,
    margin: Optional[Margin] = None,
    scale: Optional[float] = None,
    shrink_to_fit: Optional[bool] = None,
    title: Optional[str] = None,
    author: Optional[str] = None,
    subject: Optional[str] = None,
    keywords: Optional[str] = None,
    language: Optional[str] = None,
    header_text: Optional[str] = None,
    footer_text: Optional[str] = None,
    user_style_sheet: Optional[str] = None,
    fonts: Optional[Iterable[PathLike]] = None,
    use_system_fonts: bool = False,
    allow_file_access: bool = False,
    compress: bool = True,
    bookmarks: bool = True,
    max_pages: Optional[int] = None,
    creation_date: Optional[Date] = None,
    conformance: Optional[str] = None,
    accessibility: Optional[str] = None,
    timeout: Optional[float] = None,
) -> bytes:
    """Converts HTML to a PDF and returns its bytes.

    html: the document, as str or UTF-8 bytes. CSS (including @page rules for size, margins, headers and footers)
        comes from <style> and <link rel=stylesheet>.
    base_dir: the folder that relative image, stylesheet and font paths resolve against. Without it, a document from a
        string loads no local files. Files outside it load only with allow_file_access=True.
    page_size: "A3", "A4" (default), "A5", "Letter", "Legal" or (width_mm, height_mm); @page size overrides it.
    landscape: turns page_size sideways.
    margin: page margins in points (72 per inch): one number or (top, right, bottom, left). Default 36 (half an inch).
    scale: zooms the content; shrink_to_fit (default True) shrinks content wider than the page.
    title, author, subject, keywords: document properties. language: the document language, such as "en-GB".
    header_text, footer_text: a line of text at the top or bottom of every page; {page} and {pages} are replaced,
        as in "Page {page} of {pages}".
    user_style_sheet: CSS applied after the document's own.
    fonts: TrueType/OpenType files or folders that CSS font-family can name. Without fonts, text uses the standard PDF
        fonts, which cover Western European characters only; add fonts for other scripts.
    use_system_fonts: also look up font families among the fonts installed on this machine.
    compress: compress the PDF's streams. bookmarks: make bookmarks from the headings.
    max_pages: stop with PdfLimitError beyond this many pages (default 100,000).
    creation_date: a fixed creation date, which makes the output byte-identical from run to run.
    conformance: "PDF/A-2b", "PDF/A-3b", "PDF/A-2u", "PDF/A-3u", "PDF/A-4" or "PDF/A-4f".
    accessibility: "tagged", "PDF/UA-1" or "PDF/UA-2".
    timeout: seconds before the conversion stops with PdfTimeoutError.
    """
    data = html.encode("utf-8") if isinstance(html, str) else bytes(html)
    return _native.invoke("html_to_pdf", data, _pdf_options(locals()))


def html_file_to_pdf(path: PathLike, output: Optional[PathLike] = None, **options) -> bytes:
    """Converts an HTML file; relative paths resolve against its folder. Writes the PDF to output when given, and
    returns its bytes. Takes the keyword options of html_to_pdf."""
    options.setdefault("base_dir", os.path.dirname(os.path.abspath(path)))
    with open(path, "rb") as f:
        pdf = html_to_pdf(f.read(), **options)
    return _write(pdf, output)


def markdown_to_pdf(markdown: Union[str, bytes], **options) -> bytes:
    """Converts Markdown (CommonMark with GitHub tables, task lists, strikethrough and footnotes) to a PDF. Takes the
    keyword options of html_to_pdf."""
    data = markdown.encode("utf-8") if isinstance(markdown, str) else bytes(markdown)
    return _native.invoke("markdown_to_pdf", data, _pdf_options(_check(options, html_to_pdf)))


def markdown_file_to_pdf(path: PathLike, output: Optional[PathLike] = None, **options) -> bytes:
    """Converts a Markdown file; images resolve against its folder. Writes the PDF to output when given."""
    options.setdefault("base_dir", os.path.dirname(os.path.abspath(path)))
    with open(path, "rb") as f:
        pdf = markdown_to_pdf(f.read(), **options)
    return _write(pdf, output)


def pdf_to_images(
    pdf: Union[bytes, PathLike],
    *,
    dpi: float = 150,
    format: str = "png",
    pages: Optional[Union[str, int, Sequence[int]]] = None,
    width: Optional[int] = None,
    height: Optional[int] = None,
    transparent: bool = False,
    quality: Optional[int] = None,
    password: Optional[str] = None,
    timeout: Optional[float] = None,
) -> List[bytes]:
    """Renders PDF pages to images and returns one encoded image per page.

    pdf: the PDF's bytes or a path to it.
    format: "png" (default), "jpeg" or "webp"; quality 1-100 for jpeg and webp.
    pages: which pages, numbered from 1: an int, a list, or a range such as "1-3,5" or "last". Default: all.
    dpi: resolution (default 150); width or height instead fix the size in pixels, keeping the aspect ratio.
    transparent: leave the page background transparent (png and webp).
    """
    return _native.unframe(_native.invoke("pdf_to_images", _pdf_bytes(pdf), {
        "dpi": dpi, "format": format, "pages": _pages(pages), "width": width, "height": height,
        "transparent": transparent, "quality": quality, "password": password, "timeout": timeout}))


def pdf_page_count(pdf: Union[bytes, PathLike], *, password: Optional[str] = None) -> int:
    """The number of pages of a PDF."""
    return int(_native.invoke("pdf_page_count", _pdf_bytes(pdf), {"password": password}))


def pdf_to_text_pages(
    pdf: Union[bytes, PathLike],
    *,
    pages: Optional[Union[str, int, Sequence[int]]] = None,
    password: Optional[str] = None,
    timeout: Optional[float] = None,
) -> List[str]:
    """Extracts the text of each page, in reading order, as one string per page."""
    raw = _native.invoke("pdf_to_text", _pdf_bytes(pdf), {"pages": _pages(pages), "password": password, "timeout": timeout})
    return [page.decode("utf-8") for page in _native.unframe(raw)]


def pdf_to_text(pdf: Union[bytes, PathLike], **options) -> str:
    """Extracts the text of a PDF, pages separated by a form feed. Takes the options of pdf_to_text_pages."""
    return "\f".join(pdf_to_text_pages(pdf, **options))


def merge_pdfs(
    pdfs: Iterable[Union[bytes, PathLike]],
    *,
    title: Optional[str] = None,
    author: Optional[str] = None,
    bookmarks: bool = True,
    creation_date: Optional[Date] = None,
    timeout: Optional[float] = None,
) -> bytes:
    """Merges PDFs, given as bytes or paths, into one, keeping links, bookmarks and form fields."""
    items = [_pdf_bytes(p) for p in pdfs]
    return _native.invoke("merge_pdfs", _native.frame(items), {
        "title": title, "author": author, "bookmarks": bookmarks, "creation_date": _date(creation_date),
        "timeout": timeout})


def _pdf_options(args: dict) -> dict:
    options = {k: v for k, v in args.items() if k not in ("html", "data")}
    if options.get("base_dir") is not None:
        options["base_dir"] = os.fspath(options["base_dir"])
    if options.get("fonts") is not None:
        options["fonts"] = [os.fspath(f) for f in options["fonts"]]
    options["creation_date"] = _date(options.get("creation_date"))
    if not options.get("landscape"):
        options.pop("landscape", None)
    return options


_PDF_OPTION_NAMES = None


def _check(options: dict, like) -> dict:
    global _PDF_OPTION_NAMES
    if _PDF_OPTION_NAMES is None:
        code = like.__code__
        _PDF_OPTION_NAMES = set(code.co_varnames[code.co_argcount:code.co_argcount + code.co_kwonlyargcount])
    unknown = set(options) - _PDF_OPTION_NAMES
    if unknown:
        raise TypeError(f"unexpected keyword argument(s): {', '.join(sorted(unknown))}")
    return options


def _date(value: Optional[Date]) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, _dt.datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=_dt.timezone.utc)
        return int(value.timestamp())
    if isinstance(value, _dt.date):
        return int(_dt.datetime(value.year, value.month, value.day, tzinfo=_dt.timezone.utc).timestamp())
    return int(value)


def _pages(pages) -> Optional[str]:
    if pages is None or isinstance(pages, str):
        return pages
    if isinstance(pages, int):
        return str(pages)
    return ",".join(str(int(p)) for p in pages)


def _pdf_bytes(pdf) -> bytes:
    if isinstance(pdf, (bytes, bytearray, memoryview)):
        return bytes(pdf)
    with open(pdf, "rb") as f:
        return f.read()


def _write(pdf: bytes, output: Optional[PathLike]) -> bytes:
    if output is not None:
        with open(output, "wb") as f:
            f.write(pdf)
    return pdf
