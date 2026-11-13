"""Key mapping and settings validation (no console needed)."""

import sys
import unittest
from unittest import mock

from q3pass import ui
from q3pass.generator import Policy, PolicyError


class KeyMapTests(unittest.TestCase):
    def test_latin_both_cases(self):
        for ch, action in (("r", "new"), ("R", "new"), ("c", "copy"), ("C", "copy"),
                           ("l", "custom"), ("s", "settings"), ("b", "back"), ("D", "reset")):
            self.assertEqual(ui.map_key(ch), action, ch)

    def test_russian_layout(self):
        for ch, action in (("к", "new"), ("С", "copy"), ("д", "custom"),
                           ("ы", "settings"), ("и", "back"), ("в", "reset")):
            self.assertEqual(ui.map_key(ch), action, ch)

    def test_ukrainian_layout(self):
        for ch, action in (("К", "new"), ("с", "copy"), ("Д", "custom"),
                           ("і", "settings"), ("І", "settings"), ("И", "back")):
            self.assertEqual(ui.map_key(ch), action, ch)

    def test_hide_key_all_layouts(self):
        for ch in ("h", "H", "р", "Р"):
            self.assertEqual(ui.map_key(ch), "hide", ch)

    def test_symbols_key_all_layouts(self):
        for ch in ("x", "X", "ч", "Ч"):
            self.assertEqual(ui.map_key(ch), "symbols", ch)

    def test_mask_reveals_nothing_but_length(self):
        self.assertEqual(ui.masked("k7#Vq"), "•••••")
        self.assertTrue(set(ui.masked("abc!123")) == {"•"})

    def test_digits_and_control(self):
        self.assertEqual(ui.map_key("3"), "3")
        self.assertEqual(ui.map_key("\x03"), "quit")
        self.assertIsNone(ui.map_key("q"))
        self.assertIsNone(ui.map_key(None))
        self.assertIsNone(ui.map_key(""))

    @unittest.skipUnless(sys.platform == "win32", "msvcrt is Windows-only")
    def test_special_key_prefix_discarded(self):
        for prefix in ("\x00", "\xe0"):
            with mock.patch("msvcrt.getwch", side_effect=[prefix, "H"]) as getwch:
                self.assertIsNone(ui.read_key())
                self.assertEqual(getwch.call_count, 2)


class SettingsTests(unittest.TestCase):
    def test_disabling_last_class_rejected(self):
        only_lower = Policy(use_upper=False, use_digits=False, use_symbols=False)
        with self.assertRaises(PolicyError):
            ui.toggle_setting(only_lower, "1")

    def test_exclusions_emptying_class_rejected(self):
        with self.assertRaises(PolicyError):
            ui.set_exclusions(Policy(), "23456789")

    def test_set_length(self):
        self.assertEqual(ui.set_length(Policy(), " 20 ").length, 20)
        for bad in ("abc", "7", "65", "-8", "1.5", "١٢"):
            with self.assertRaises(PolicyError, msg=bad):
                ui.set_length(Policy(), bad)

    def test_reset_keeps_length(self):
        changed = Policy(length=32, use_symbols=False, excluded_chars=frozenset("a"))
        self.assertEqual(ui.reset_settings(changed), Policy(length=32))

    def test_invalid_change_not_applied(self):
        app = ui.App(ui.Console())
        app.policy = Policy(use_upper=False, use_digits=False, use_symbols=False)
        before = app.policy
        self.assertFalse(app._apply(lambda p: ui.toggle_setting(p, "1")))
        self.assertEqual(app.policy, before)
        self.assertTrue(app.status[1])


class AutoClearTests(unittest.TestCase):
    """Timer bookkeeping with the clipboard API mocked out (no real clipboard touched)."""

    def setUp(self):
        self.app = ui.App(ui.Console())
        self.app._regenerate()
        self.copy = mock.patch.object(ui, "copy_text", side_effect=[101, 102]).start()
        self.clear = mock.patch.object(ui, "clear_if_unchanged", return_value=True).start()
        self.addCleanup(mock.patch.stopall)
        self.addCleanup(self.app._cancel_clear)

    def test_copy_schedules_clear(self):
        self.app._copy()
        self.assertEqual(self.app._pending_seq, 101)
        self.assertTrue(self.app._clear_timer.is_alive())
        self.assertIn("CLEARS IN", self.app.status[0])

    def test_new_copy_replaces_pending(self):
        self.app._copy()
        first = self.app._clear_timer
        self.app._copy()
        self.assertEqual(self.app._pending_seq, 102)
        first.join(1)
        self.assertFalse(first.is_alive())

    def test_timer_fires_clear(self):
        self.app._copy()
        self.app._auto_clear(101)
        self.clear.assert_called_once_with(101)
        self.assertIsNone(self.app._pending_seq)

    def test_cleared_notice_shown_once(self):
        self.app._copy()
        self.app._auto_clear(101)
        self.app.status = None
        self.app._consume_notice()
        self.assertEqual(self.app.status, ("CLIPBOARD CLEARED", False))
        self.app.status = None
        self.app._consume_notice()
        self.assertIsNone(self.app.status)

    def test_no_notice_when_clipboard_was_changed(self):
        self.clear.return_value = False
        self.app._copy()
        self.app._auto_clear(101)
        self.app.status = None
        self.app._consume_notice()
        self.assertIsNone(self.app.status)

    def test_new_copy_drops_old_notice(self):
        self.app._copy()
        self.app._auto_clear(101)
        self.app._copy()
        self.app._consume_notice()
        self.assertIn("COPIED", self.app.status[0])

    def test_stale_timer_does_nothing(self):
        self.app._copy()
        self.app._copy()
        self.app._auto_clear(101)
        self.clear.assert_not_called()

    def test_shutdown_clears_pending_now(self):
        self.app._copy()
        self.app.shutdown()
        self.clear.assert_called_once_with(101)
        self.assertIsNone(self.app._clear_timer)

    def test_auto_clear_off(self):
        self.app.auto_clear = False
        self.app._copy()
        self.assertIsNone(self.app._pending_seq)
        self.app.shutdown()
        self.clear.assert_not_called()


if __name__ == "__main__":
    unittest.main()
