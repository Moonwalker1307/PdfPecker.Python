# pdfpecker for Python

Fast HTML and Markdown to PDF, and PDF to images and text, for Python. No browser, no dependencies, no .NET to install.

```
pip install pdfpecker
```

```python
import pdfpecker

pdf = pdfpecker.html_to_pdf("<h1>Invoice 42</h1><p>Total: <b>1,250.00 EUR</b></p>")
pdfpecker.html_file_to_pdf("templates/invoice.html", "invoice.pdf")     # images and CSS resolve next to the file
pdfpecker.markdown_file_to_pdf("README.md", "readme.pdf")

pngs = pdfpecker.pdf_to_images(pdf, dpi=96)        # one PNG per page (or format="jpeg"/"webp")
text = pdfpecker.pdf_to_text(pdf)                  # pages separated by \f
both = pdfpecker.merge_pdfs([pdf, "terms.pdf"])
```

This is the [PdfPecker](https://github.com/Moonwalker1307/PdfPecker) .NET library, compiled ahead of time into a
native library that ships inside the wheel. PdfPecker has its own HTML parser, CSS engine, layout engine, PDF writer
and PDF renderer, so a conversion takes about a millisecond for a one-page invoice and never starts a browser.
The package version is the library version it holds. Documentation of what PdfPecker renders, its CSS support and
its limitations: [pdfpecker.net/docs](https://pdfpecker.net/docs/).

## Platforms

Wheels for Linux (glibc 2.28+ and musl, x86-64 and ARM64), macOS (Apple Silicon and Intel) and Windows (x64 and
ARM64), on Python 3.9 and later. Each wheel is about 9 MB and has no Python or system dependencies.

## Speed

From Python, on a 4-core Linux cloud VM, median time per document after warm-up; the documents are the benchmark
pages of the PdfPecker repository:

| | Invoice, 1 page | Feature tour, 5 pages | Report, 29 pages | Start-up and first PDF | Peak memory, one PDF |
|---|---:|---:|---:|---:|---:|
| **pdfpecker** | **0.7 ms** | **2.9 ms** | **32 ms** | **57 ms** | **32 MB** |
| Chromium 153 via Playwright | 24 ms | 48 ms | 290 ms | 735 ms | 542 MB |
| xhtml2pdf 0.2.28 | 33 ms | 209 ms | 2.9 s | 453 ms | 63 MB |
| WeasyPrint 70.0 | 324 ms | 797 ms | 4.2 s | 1.1 s | 75 MB |

## API

Every function takes bytes or a path for PDFs, raises a subclass of `PdfPeckerError` on failure, is thread-safe and
releases the GIL while it works, so threads convert in parallel.

| Function | Returns |
|---|---|
| `html_to_pdf(html, **options)` | PDF bytes from an HTML `str` or UTF-8 `bytes` |
| `html_file_to_pdf(path, output=None, **options)` | PDF bytes, also written to `output` when given; `base_dir` is the file's folder |
| `markdown_to_pdf(markdown, **options)` | PDF bytes from CommonMark with GitHub tables, task lists, strikethrough and footnotes |
| `markdown_file_to_pdf(path, output=None, **options)` | as `html_file_to_pdf` |
| `pdf_to_images(pdf, dpi=150, format="png", pages=None, width=None, height=None, transparent=False, quality=None, password=None)` | a list of encoded images, one per page |
| `pdf_to_text(pdf, pages=None, password=None)` | the text in reading order, pages separated by `\f` |
| `pdf_to_text_pages(pdf, pages=None, password=None)` | a list with the text of each page |
| `pdf_page_count(pdf, password=None)` | the number of pages |
| `merge_pdfs(pdfs, title=None, author=None, bookmarks=True, creation_date=None)` | one PDF from several |
| `library_version()` | the version of the PdfPecker library inside |

`pages` takes a page number, a list of numbers, or a range such as `"1-3,5"`, `"8-"` or `"last"`, numbered from 1.
Every function also takes `timeout` in seconds.

Options of the HTML and Markdown functions:

| Option | Meaning |
|---|---|
| `base_dir` | The folder relative image, stylesheet and font paths resolve against. Without it, a document from a string loads no local files. |
| `allow_file_access` | Let the document read files outside `base_dir` too. Only for HTML you trust. |
| `page_size`, `landscape` | `"A3"`, `"A4"` (default), `"A5"`, `"Letter"`, `"Legal"` or `(width_mm, height_mm)`. A CSS `@page { size }` rule wins. |
| `margin` | In points (72 per inch): one number or `(top, right, bottom, left)`. Default 36. CSS `@page { margin }` wins. |
| `scale`, `shrink_to_fit` | Zoom the content; shrink content wider than the page (on by default). |
| `header_text`, `footer_text` | A line of text in the top or bottom margin; `{page}` and `{pages}` are replaced. CSS margin boxes (`@top-center`, ...) do more. |
| `fonts`, `use_system_fonts` | TrueType/OpenType files or folders that CSS `font-family` can name; or look families up among the installed fonts. |
| `title`, `author`, `subject`, `keywords`, `language` | Document properties. |
| `user_style_sheet` | CSS applied after the document's own. |
| `creation_date` | A fixed date (`datetime`, `date` or Unix seconds): the output is then byte-identical from run to run. |
| `conformance` | `"PDF/A-2b"`, `"PDF/A-3b"`, `"PDF/A-2u"`, `"PDF/A-3u"`, `"PDF/A-4"` or `"PDF/A-4f"`. |
| `accessibility` | `"tagged"`, `"PDF/UA-1"` or `"PDF/UA-2"`. |
| `compress`, `bookmarks`, `max_pages` | Compress streams (on); bookmarks from headings (on); stop beyond this many pages (100,000). |

Errors: `PdfPeckerArgumentError` (also a `ValueError`) for bad options, `PdfReadError` for input that is not a
readable PDF, `PdfPasswordError`, `PdfLimitError` for `max_pages` and the size limits, `PdfTimeoutError` (also a
`TimeoutError`) and `PdfFileError` (also an `OSError`) for a font or file that cannot be read.

## Using it from AI agents and skills

pdfpecker suits code that an agent writes and runs in a sandbox: one `pip install`, nothing to download at run time,
no browser to launch, and errors that say what went wrong. A few things to tell the agent:

- Write the document as HTML with CSS; put page size, margins, page numbers and running headers in `@page` rules,
  for example `@page { size: A4; margin: 20mm; @bottom-center { content: "Page " counter(page) " of " counter(pages) } }`.
- There is no JavaScript: charts must be SVG or images, not a script that draws them.
- Images, stylesheets and fonts load from `base_dir` (or `data:` URIs), never from the network.
- The built-in fonts (Helvetica, Times and Courier, with bundled fallback fonts for the letters they lack) cover
  Latin, Greek and Cyrillic; other scripts come out as question marks. For Chinese, Japanese, Arabic, Hebrew, Hindi or Thai, pass `fonts=[...]` with a font
  that covers the script, or `use_system_fonts=True`.
- To check a result, render it back with `pdf_to_images(pdf, dpi=60)` and look at the pages, or read it with
  `pdf_to_text`.

## MCP server

The package includes a [Model Context Protocol](https://modelcontextprotocol.io/) server, so chat apps and coding
agents that speak MCP can make PDFs, look at their pages and read them. It runs over stdio and needs nothing but this
package:

```
claude mcp add pdfpecker -- uvx pdfpecker mcp            # Claude Code
```

For Claude Desktop and other apps that read an `mcpServers` setting:

```json
{ "mcpServers": { "pdfpecker": { "command": "uvx", "args": ["pdfpecker", "mcp", "--root", "/Users/me/Documents/pdfs"] } } }
```

| Tool | What it does |
|---|---|
| `html_to_pdf` | HTML (inline or a file) to a PDF file, with previews of the first pages to check the layout |
| `markdown_to_pdf` | the same for Markdown |
| `render_pdf_pages` | PNG images of up to 20 pages, for the model to look at |
| `pdf_to_text` | the text of a PDF, page by page |
| `pdf_info` | page count and file size |
| `merge_pdfs` | several PDF files into one |

The tools read and write files only inside the `--root` folders (repeatable), because the model picks the paths. The
default is the current folder, or `~/PdfPecker` when the server starts in the filesystem's root, as chat apps often
do. `python -m pdfpecker mcp` runs the same server without `uvx`.

<!-- mcp-name: io.github.Moonwalker1307/pdfpecker -->

## Building from source

The wheel's native library is built from the released PdfPecker NuGet package named in `PDFPECKER_VERSION`.
It needs the .NET 10 SDK with the NativeAOT prerequisites (clang on Linux, Xcode on macOS, the Visual Studio C++
tools on Windows):

```
ci/build.sh linux-x64 manylinux_2_39_x86_64          # RID and wheel tag; builds, packs and tests the wheel
```

Or by hand: `dotnet publish native/PdfPecker.Native.csproj -c Release -r linux-x64`, copy `pdfpecker_native.so`
(`.dylib`, `.dll`) into `src/pdfpecker/`, and run `pytest`. `PDFPECKER_NATIVE_LIB` points the package at a library
elsewhere.

The C ABI (`native/Exports.cs`) is one function, `pdfpecker_invoke(op, input, input_len, options_json, &output,
&output_len, &error)`, plus `pdfpecker_free`, `pdfpecker_version` and `pdfpecker_abi_version`, so other languages
with an FFI can use the same library.

## Releasing

A PdfPecker release on NuGet is followed by a pull request here that changes `PDFPECKER_VERSION`. Once it is merged,
the owner publishes a GitHub release tagged `v<version>`; the Wheels workflow builds the eight wheels again, checks the
tag against `PDFPECKER_VERSION` and uploads them to PyPI with Trusted Publishing. It then lists the new version of
the MCP server (`server.json`) in the official MCP Registry.

## License

MIT. The wheel also contains the .NET runtime, zlib-ng and the fonts and data PdfPecker bundles, each under its own
license: see `THIRD-PARTY-NOTICES.md`.
