"""
Verschlüsselt kleine Geheimnisse (z. B. ein Passwort) mit Windows, so dass nur dein Windows-Benutzer auf diesem PC sie
wieder lesen kann (DPAPI). In einstellungen.json steht dann nur ein unlesbarer Text.
"""

import base64
import ctypes
from ctypes import wintypes


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _blob(data: bytes) -> _Blob:
    buf = ctypes.create_string_buffer(data, len(data))
    return _Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), buf


def _take(out: _Blob) -> bytes:
    data = ctypes.string_at(out.pbData, out.cbData)
    ctypes.windll.kernel32.LocalFree(out.pbData)
    return data


def protect(text: str) -> str:
    if not text:
        return ""
    try:
        blob, keep = _blob(text.encode("utf-8"))
        out = _Blob()
        if not ctypes.windll.crypt32.CryptProtectData(ctypes.byref(blob), None, None, None, None, 0, ctypes.byref(out)):
            return ""
        return base64.b64encode(_take(out)).decode("ascii")
    except Exception:
        return ""


def unprotect(token: str) -> str:
    if not token:
        return ""
    try:
        blob, keep = _blob(base64.b64decode(token))
        out = _Blob()
        if not ctypes.windll.crypt32.CryptUnprotectData(ctypes.byref(blob), None, None, None, None, 0, ctypes.byref(out)):
            return ""
        return _take(out).decode("utf-8")
    except Exception:
        return ""
