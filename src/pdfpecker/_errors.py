"""The exceptions PdfPecker raises. Each status of the native library maps to one class."""
from __future__ import annotations


class PdfPeckerError(Exception):
    """Base class of every PdfPecker error. status is the native library's status code."""

    status = 0

    def __init__(self, message: str) -> None:
        super().__init__(message)


class PdfPeckerArgumentError(PdfPeckerError, ValueError):
    """An argument or option is not valid (an unknown page size, a page past the end, an unknown option)."""

    status = 1


class PdfReadError(PdfPeckerError):
    """The input is not a readable PDF, image or font."""

    status = 2


class PdfPasswordError(PdfPeckerError):
    """The PDF is encrypted and no password, or a wrong one, was given."""

    status = 3


class PdfLimitError(PdfPeckerError):
    """A page, size or resource limit was reached, such as max_pages."""

    status = 4


class PdfTimeoutError(PdfPeckerError, TimeoutError):
    """The conversion took longer than its timeout."""

    status = 5


class PdfFileError(PdfPeckerError, OSError):
    """A file the document needs (a font, an image) could not be read."""

    status = 7


_BY_STATUS = {c.status: c for c in (PdfPeckerArgumentError, PdfReadError, PdfPasswordError, PdfLimitError,
                                    PdfTimeoutError, PdfFileError)}


def error_for(status: int, message: str) -> PdfPeckerError:
    cls = _BY_STATUS.get(status, PdfPeckerError)
    error = cls(message)
    error.status = status
    return error
