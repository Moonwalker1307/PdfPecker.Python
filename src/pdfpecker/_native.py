"""Loads the PdfPecker shared library and calls its one entry point, pdfpecker_invoke."""
from __future__ import annotations

import ctypes
import json
import os
import struct
import sys
from typing import Any, List, Sequence

from ._errors import error_for

_ABI_VERSION = 1

if sys.platform == "win32":
    _LIB_NAME = "pdfpecker_native.dll"
elif sys.platform == "darwin":
    _LIB_NAME = "pdfpecker_native.dylib"
else:
    _LIB_NAME = "pdfpecker_native.so"


def _load() -> ctypes.CDLL:
    path = os.environ.get("PDFPECKER_NATIVE_LIB") or os.path.join(os.path.dirname(os.path.abspath(__file__)), _LIB_NAME)
    if not os.path.exists(path):
        raise ImportError(
            f"PdfPecker's native library is missing ({path}). Install a wheel built for this platform "
            "(pip install pdfpecker), or set PDFPECKER_NATIVE_LIB to a pdfpecker_native library you built.")
    lib = ctypes.CDLL(path)
    lib.pdfpecker_invoke.argtypes = [
        ctypes.c_char_p, ctypes.c_char_p, ctypes.c_int64, ctypes.c_char_p,
        ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_int64), ctypes.POINTER(ctypes.c_void_p)]
    lib.pdfpecker_invoke.restype = ctypes.c_int
    lib.pdfpecker_free.argtypes = [ctypes.c_void_p]
    lib.pdfpecker_free.restype = None
    lib.pdfpecker_version.argtypes = []
    lib.pdfpecker_version.restype = ctypes.c_char_p
    lib.pdfpecker_abi_version.argtypes = []
    lib.pdfpecker_abi_version.restype = ctypes.c_int
    abi = lib.pdfpecker_abi_version()
    if abi != _ABI_VERSION:
        raise ImportError(f"PdfPecker's native library speaks ABI {abi}, this package expects {_ABI_VERSION}")
    return lib


_lib = _load()


def version() -> str:
    return _lib.pdfpecker_version().decode("ascii")


def invoke(op: str, data: bytes, options: dict[str, Any]) -> bytes:
    """Runs one operation. ctypes releases the GIL for the call, so threads convert in parallel."""
    opts = {k: v for k, v in options.items() if v is not None}
    output = ctypes.c_void_p()
    output_len = ctypes.c_int64()
    error = ctypes.c_void_p()
    status = _lib.pdfpecker_invoke(
        op.encode("ascii"), data, len(data), json.dumps(opts).encode("utf-8"),
        ctypes.byref(output), ctypes.byref(output_len), ctypes.byref(error))
    if status != 0:
        message = "PdfPecker failed"
        if error.value:
            message = ctypes.string_at(error.value).decode("utf-8", "replace")
            _lib.pdfpecker_free(error)
        raise error_for(status, message)
    try:
        return ctypes.string_at(output.value, output_len.value)
    finally:
        _lib.pdfpecker_free(output)


def frame(items: Sequence[bytes]) -> bytes:
    parts = [struct.pack("<i", len(items))]
    for item in items:
        parts.append(struct.pack("<q", len(item)))
        parts.append(item)
    return b"".join(parts)


def unframe(data: bytes) -> List[bytes]:
    (count,) = struct.unpack_from("<i", data, 0)
    items = []
    at = 4
    for _ in range(count):
        (length,) = struct.unpack_from("<q", data, at)
        at += 8
        items.append(data[at:at + length])
        at += length
    return items
