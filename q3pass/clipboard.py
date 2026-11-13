"""Copy text to the Windows clipboard through the Win32 API (ctypes, no third-party libraries).

Besides CF_UNICODETEXT the following registered formats are placed on the clipboard:

* ExcludeClipboardContentFromMonitorProcessing
* CanIncludeInClipboardHistory = 0   (Win+V history)
* CanUploadToCloudClipboard = 0      (cross-device cloud clipboard)

Windows honours these formats; third-party clipboard managers may ignore them.
"""

from __future__ import annotations

import sys
import time

NOT_SUPPORTED = "NOT_SUPPORTED"
FORMAT = "FORMAT"
WINDOW = "WINDOW"
BUSY = "BUSY"
EMPTY = "EMPTY"
ALLOC = "ALLOC"
LOCK = "LOCK"
UNLOCK = "UNLOCK"
SET = "SET"

CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002
OPEN_RETRIES = 10
OPEN_RETRY_DELAY = 0.05

PRIVACY_FORMATS = (
    "ExcludeClipboardContentFromMonitorProcessing",
    "CanIncludeInClipboardHistory",
    "CanUploadToCloudClipboard",
)
_DWORD_ZERO = (0).to_bytes(4, "little")


class ClipboardError(Exception):
    """Copy failed. Never carries the copied text."""

    def __init__(self, reason: str, winerror: int = 0) -> None:
        self.reason = reason
        self.winerror = winerror
        super().__init__(f"{reason} (WinError {winerror})" if winerror else reason)


class _Win32:
    """Lazily bound Win32 functions with explicit argument and return types."""

    def __init__(self) -> None:
        import ctypes
        from ctypes import wintypes

        self.ctypes = ctypes
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

        def bind(dll, name, argtypes, restype):
            fn = getattr(dll, name)
            fn.argtypes = argtypes
            fn.restype = restype
            return fn

        H = wintypes.HANDLE  # c_void_p: full 64-bit handles, never truncated to int
        self.OpenClipboard = bind(user32, "OpenClipboard", [wintypes.HWND], wintypes.BOOL)
        self.EmptyClipboard = bind(user32, "EmptyClipboard", [], wintypes.BOOL)
        self.SetClipboardData = bind(user32, "SetClipboardData", [wintypes.UINT, H], H)
        self.CloseClipboard = bind(user32, "CloseClipboard", [], wintypes.BOOL)
        self.GetClipboardSequenceNumber = bind(user32, "GetClipboardSequenceNumber", [], wintypes.DWORD)
        self.RegisterClipboardFormatW = bind(
            user32, "RegisterClipboardFormatW", [wintypes.LPCWSTR], wintypes.UINT
        )
        self.CreateWindowExW = bind(
            user32,
            "CreateWindowExW",
            [
                wintypes.DWORD,    # dwExStyle
                wintypes.LPCWSTR,  # lpClassName
                wintypes.LPCWSTR,  # lpWindowName
                wintypes.DWORD,    # dwStyle
                ctypes.c_int,      # X
                ctypes.c_int,      # Y
                ctypes.c_int,      # nWidth
                ctypes.c_int,      # nHeight
                wintypes.HWND,     # hWndParent
                wintypes.HMENU,    # hMenu
                wintypes.HINSTANCE,  # hInstance
                wintypes.LPVOID,   # lpParam
            ],
            wintypes.HWND,
        )
        self.DestroyWindow = bind(user32, "DestroyWindow", [wintypes.HWND], wintypes.BOOL)
        self.GlobalAlloc = bind(kernel32, "GlobalAlloc", [wintypes.UINT, ctypes.c_size_t], H)
        self.GlobalLock = bind(kernel32, "GlobalLock", [H], wintypes.LPVOID)
        self.GlobalUnlock = bind(kernel32, "GlobalUnlock", [H], wintypes.BOOL)
        self.GlobalFree = bind(kernel32, "GlobalFree", [H], H)

    def last_error(self) -> int:
        return self.ctypes.get_last_error()


_api: _Win32 | None = None


def _win32() -> _Win32:
    global _api
    if _api is None:
        _api = _Win32()
    return _api


def _register_formats(api: _Win32) -> list[int]:
    formats = []
    for name in PRIVACY_FORMATS:
        fmt = api.RegisterClipboardFormatW(name)
        if not fmt:
            raise ClipboardError(FORMAT, api.last_error())
        formats.append(fmt)
    return formats


def _open(api: _Win32, hwnd) -> None:
    err = 0
    for attempt in range(OPEN_RETRIES):
        if api.OpenClipboard(hwnd):
            return
        err = api.last_error()
        if attempt < OPEN_RETRIES - 1:
            time.sleep(OPEN_RETRY_DELAY)
    raise ClipboardError(BUSY, err)


def _set_data(api: _Win32, fmt: int, data: bytes) -> None:
    """Allocate a movable global block, fill it and hand it to the clipboard."""
    hmem = api.GlobalAlloc(GMEM_MOVEABLE, len(data))
    if not hmem:
        raise ClipboardError(ALLOC, api.last_error())
    try:
        ptr = api.GlobalLock(hmem)
        if not ptr:
            raise ClipboardError(LOCK, api.last_error())
        api.ctypes.memmove(ptr, data, len(data))
        # GlobalUnlock returns 0 both on error and when the lock count reaches zero;
        # only a non-zero last error means failure.
        api.ctypes.set_last_error(0)
        if not api.GlobalUnlock(hmem):
            err = api.last_error()
            if err:
                raise ClipboardError(UNLOCK, err)
        if not api.SetClipboardData(fmt, hmem):
            raise ClipboardError(SET, api.last_error())
    except BaseException:
        # Ownership passes to the system only after a successful SetClipboardData.
        api.GlobalFree(hmem)
        raise


def _helper_window(api: _Win32):
    # A NULL owner may make SetClipboardData fail, so use a hidden helper window.
    hwnd = api.CreateWindowExW(0, "STATIC", None, 0, 0, 0, 0, 0, None, None, None, None)
    if not hwnd:
        raise ClipboardError(WINDOW, api.last_error())
    return hwnd


def copy_text(text: str) -> int:
    """Place ``text`` on the clipboard together with the privacy formats.

    Privacy formats go first: if they cannot be set, the text is never placed.
    Returns the clipboard sequence number right after our change, for ``clear_if_unchanged``.
    """
    if sys.platform != "win32":
        raise ClipboardError(NOT_SUPPORTED)

    api = _win32()
    formats = _register_formats(api)
    payload = text.encode("utf-16-le") + b"\x00\x00"
    hwnd = _helper_window(api)

    opened = False
    try:
        _open(api, hwnd)
        opened = True
        if not api.EmptyClipboard():
            raise ClipboardError(EMPTY, api.last_error())
        try:
            for fmt in formats:
                _set_data(api, fmt, _DWORD_ZERO)
            _set_data(api, CF_UNICODETEXT, payload)
        except ClipboardError:
            api.EmptyClipboard()  # never leave partial data behind
            raise
    finally:
        if opened:
            api.CloseClipboard()
        api.DestroyWindow(hwnd)
    # Windows also bumps the number on CloseClipboard (synthesised formats),
    # so it is read immediately after closing.
    return api.GetClipboardSequenceNumber()


def clear_if_unchanged(sequence: int) -> bool:
    """Empty the clipboard only if nobody has changed it since our copy.

    The check happens while the clipboard is open, so no one can write in between.
    Returns True if the clipboard was cleared.
    """
    if sys.platform != "win32":
        raise ClipboardError(NOT_SUPPORTED)

    api = _win32()
    hwnd = _helper_window(api)
    opened = False
    try:
        _open(api, hwnd)
        opened = True
        if api.GetClipboardSequenceNumber() != sequence:
            return False
        if not api.EmptyClipboard():
            raise ClipboardError(EMPTY, api.last_error())
        return True
    finally:
        if opened:
            api.CloseClipboard()
        api.DestroyWindow(hwnd)
