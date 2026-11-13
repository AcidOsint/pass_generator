"""Real clipboard round-trip. Overwrites your clipboard, so it only runs on request:

    set Q3_CLIPBOARD_TEST=1   (PowerShell: $env:Q3_CLIPBOARD_TEST="1")
    py -m unittest tests.test_clipboard_win -v
"""

import os
import sys
import unittest

from q3pass import clipboard

ENABLED = sys.platform == "win32" and os.environ.get("Q3_CLIPBOARD_TEST") == "1"


@unittest.skipUnless(ENABLED, "set Q3_CLIPBOARD_TEST=1 on Windows to run")
class ClipboardRoundTrip(unittest.TestCase):
    def setUp(self):
        import ctypes
        from ctypes import wintypes

        self.ctypes = ctypes
        u32 = ctypes.WinDLL("user32", use_last_error=True)
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        u32.OpenClipboard.argtypes = [wintypes.HWND]
        u32.OpenClipboard.restype = wintypes.BOOL
        u32.CloseClipboard.restype = wintypes.BOOL
        u32.GetClipboardData.argtypes = [wintypes.UINT]
        u32.GetClipboardData.restype = wintypes.HANDLE
        u32.IsClipboardFormatAvailable.argtypes = [wintypes.UINT]
        u32.IsClipboardFormatAvailable.restype = wintypes.BOOL
        u32.RegisterClipboardFormatW.argtypes = [wintypes.LPCWSTR]
        u32.RegisterClipboardFormatW.restype = wintypes.UINT
        k32.GlobalLock.argtypes = [wintypes.HANDLE]
        k32.GlobalLock.restype = wintypes.LPVOID
        k32.GlobalUnlock.argtypes = [wintypes.HANDLE]
        k32.GlobalUnlock.restype = wintypes.BOOL
        self.u32, self.k32 = u32, k32

    def read_back(self):
        self.assertTrue(self.u32.OpenClipboard(None))
        try:
            formats = {
                name: bool(self.u32.IsClipboardFormatAvailable(self.u32.RegisterClipboardFormatW(name)))
                for name in clipboard.PRIVACY_FORMATS
            }
            handle = self.u32.GetClipboardData(clipboard.CF_UNICODETEXT)
            self.assertTrue(handle)
            ptr = self.k32.GlobalLock(handle)
            try:
                text = self.ctypes.wstring_at(ptr)
            finally:
                self.k32.GlobalUnlock(handle)
        finally:
            self.u32.CloseClipboard()
        return text, formats

    def test_round_trip_with_privacy_formats(self):
        sample = "Q3-test-NOT-A-SECRET ✓ пароль !\"#$%"
        clipboard.copy_text(sample)
        text, formats = self.read_back()
        self.assertEqual(text, sample)
        self.assertTrue(all(formats.values()), formats)

    def test_clear_if_unchanged_clears_our_copy(self):
        seq = clipboard.copy_text("Q3-test-NOT-A-SECRET")
        self.assertTrue(clipboard.clear_if_unchanged(seq))
        self.assertTrue(self.u32.OpenClipboard(None))
        try:
            self.assertFalse(self.u32.GetClipboardData(clipboard.CF_UNICODETEXT))
        finally:
            self.u32.CloseClipboard()

    def test_clear_if_unchanged_keeps_newer_content(self):
        old = clipboard.copy_text("Q3-test-old")
        clipboard.copy_text("Q3-test-newer")  # stands in for the user copying something else
        self.assertFalse(clipboard.clear_if_unchanged(old))
        text, _ = self.read_back()
        self.assertEqual(text, "Q3-test-newer")


if __name__ == "__main__":
    unittest.main()
