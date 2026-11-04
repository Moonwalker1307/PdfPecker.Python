## What changes

<!-- What a Python user sees before and after this change. Link the issue it fixes, if any. -->

## How

<!-- A short note on the approach, if it isn't obvious from the diff. -->

## Checklist

- [ ] `ci/build.sh` (or `pytest` with a locally built library) passes
- [ ] The Wheels workflow is green on all eight platforms
- [ ] `PDFPECKER_VERSION` names a PdfPecker release that nuget.org already serves
- [ ] A new function or option has a docstring, a test and a line in `README.md`
- [ ] A change to the C ABI bumps `AbiVersion` in `native/Exports.cs` and `_ABI_VERSION` in `src/pdfpecker/_native.py` together
