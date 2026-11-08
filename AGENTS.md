# AGENTS.md

Guidance for coding agents (and people) working in this repository. `CLAUDE.md` imports this file, so Claude Code and
other agents read the same rules.

PdfPecker.Python is the `pdfpecker` package on PyPI: the [PdfPecker](https://github.com/Moonwalker1307/PdfPecker)
.NET library compiled with NativeAOT into a shared library with a C ABI, and a small `ctypes` package over it. The
library itself is not here; the native project uses the released PdfPecker NuGet package.

## Core rules

- **PdfPecker comes from NuGet.** `native/PdfPecker.Native.csproj` references the version in `PDFPECKER_VERSION`,
  which is also the Python package's version. Never copy library code here or build against an unreleased library;
  when the package needs something PdfPecker cannot do, fix the library in its own repository and PR first.
- **No Python dependencies.** The package uses only the standard library (`ctypes`, `json`, `struct`). Test tools
  (pytest) are not runtime dependencies.
- **One C entry point.** New operations go through `pdfpecker_invoke` with a new op name and options, not new
  exports. A change to the calling convention bumps `AbiVersion` in `native/Exports.cs` and `_ABI_VERSION` in
  `src/pdfpecker/_native.py` together.
- **No exception crosses the C boundary.** Every export catches everything and returns a status; each status maps to
  one Python exception class in `src/pdfpecker/_errors.py`, all subclasses of `PdfPeckerError`.
- **Unknown options fail.** Python functions take keyword-only options, and the native side rejects any option an
  operation does not read.
- **No breaking API changes before 2.0**, as in the library: add functions and options, don't rename or remove them.
- **Trimmable and AOT-compatible.** No reflection in `native/`; the build must stay warning-free (warnings are errors).
- **Never name a user's private application or employer** in code, tests, commits, the README or PR descriptions.

## Repo map

- `native/` – `Exports.cs` (the C ABI and statuses), `Operations.cs` (the operations, option reading, list framing).
- `src/pdfpecker/` – `__init__.py` (the public API and its docstrings), `_native.py` (loading and calling the
  library), `_errors.py` (exceptions), `py.typed`, `mcp_server.py` (the MCP server, standard library only, run by
  `__main__.py` as `pdfpecker mcp`). The built library is copied in here and is git-ignored.
- `server.json` – the MCP Registry entry; the release workflow sets its version from `PDFPECKER_VERSION`.
- `tests/` – pytest; `conftest.py` runs them against the source tree unless `PDFPECKER_TEST_INSTALLED=1`.
- `ci/build.sh` builds the library for one RID, packs the wheel with its platform tag and tests the installed wheel;
  `ci/linux.sh` does it inside the PyPA manylinux and musllinux images.
- `setup.py` tags the wheel `py3-none-<platform>` (the code is pure Python over ctypes, so any Python 3.9+ works).
- `.github/workflows/wheels.yml` – eight platform builds on every PR, and the PyPI upload on a published release.
- `.github/workflows/vulnerability-scan.yml` – daily: OSV-Scanner on the NuGet packages the library is built from
  (results in Security → Code scanning), and an issue for each new .NET security release of the version the library
  is built for, since every wheel carries that runtime.

## Build and verify

```
ci/build.sh linux-x64 manylinux_2_39_x86_64     # .NET 10 SDK and clang; builds, packs and tests one wheel
```

Before pushing, the native build must be warning-free and the tests must pass. CI is the check for the other seven
platforms.

## Releasing

After a PdfPecker NuGet release (once nuget.org serves it), a PR changes `PDFPECKER_VERSION` and adds functions or
options for what the release added. The owner publishes the GitHub release `v<version>`; the workflow uploads to
PyPI with Trusted Publishing (project `pdfpecker`, workflow `wheels.yml`, environment `pypi`). Never publish, tag or
create a release yourself.

## Commit guidance

- Branch from the latest `origin/main`, one branch per piece of work, named after the work with a `claude/` prefix
  when an agent creates it. Never reuse a branch name after its PR is merged or closed.
- Commit subjects are short imperative or descriptive sentences without prefixes; the body explains why.
- Fill in `.github/pull_request_template.md`, and update `README.md` in the same PR when a function or option changes.

## Wisdom

- Linux wheels must build inside the PyPA images: a library built on a new distribution needs that distribution's
  glibc, and `ci/build.sh` refuses a library that needs a newer glibc than its tag.
- NativeAOT links Microsoft's zlib-ng, so PDFs are about 30% larger than those of a .NET app on a distribution whose
  framework uses the system zlib; the content, inflated, is identical.
- NativeAOT is faster than JIT .NET to start (about 20 ms against 450 ms) and on small documents, and about a third
  slower on long ones, because it has no dynamic PGO.
