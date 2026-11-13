"""Q3 PASS interactive console UI in the Q-tools style."""

from __future__ import annotations

import os
import sys
import threading
from dataclasses import replace

from . import __version__
from .clipboard import BUSY, NOT_SUPPORTED, ClipboardError, clear_if_unchanged, copy_text
from .generator import (
    AMBIGUOUS,
    BASE_CHARS,
    MAX_LENGTH,
    MIN_LENGTH,
    Policy,
    PolicyError,
    Result,
    build_classes,
    generate,
    normalize_exclusions,
)

# --------------------------------------------------------------------------- style

BANNER = (
    " ██████╗    ██████╗ ",
    "██╔═══██╗   ╚════██╗",
    "██║   ██║    █████╔╝",
    "██║▄▄ ██║    ╚═══██╗",
    "╚██████╔╝██╗██████╔╝",
    " ╚══▀▀═╝ ╚═╝╚═════╝ ",
)
# Standard 16-colour SGR codes, same as Q.2: the terminal's own palette decides the exact shade.
RED = "91"      # bright red: banner blocks, menu
FRAME = "37"    # white: separators on sub-screens
KEY = "90"      # grey: header line, separators, hints
VALUE = "37"    # white: labels
BRIGHT = "97"   # bright white: password, ON, prompts

SEPARATOR = "  " + "-" * 65
MASK_CHAR = "•"
AUTO_CLEAR_SECONDS = 30

# --------------------------------------------------------------------------- keys

QUICK_LENGTHS = {"1": 10, "2": 12, "3": 16, "4": 20, "5": 24, "6": 32}

# Latin key + the letters produced by the same physical key in RU and UA layouts.
_KEYS = {
    "new": "rк",
    "copy": "cс",
    "custom": "lд",
    "settings": "sыі",
    "back": "bи",
    "reset": "dв",
    "hide": "hр",
    "symbols": "xч",
}

TOGGLES = {
    "1": "use_lower",
    "2": "use_upper",
    "3": "use_digits",
    "4": "use_symbols",
    "5": "exclude_ambiguous",
    "6": "require_each",
}


def map_key(ch: str | None) -> str | None:
    """Translate one key press into an action name, a digit, or None (ignored)."""
    if not ch:
        return None
    if ch == "\x03":
        return "quit"
    if ch in "0123456789":
        return ch
    low = ch.lower()
    for action, keys in _KEYS.items():
        if low in keys:
            return action
    return None


def read_key() -> str | None:
    """Read a single key without Enter (Windows); fall back to a line on other systems."""
    if sys.platform == "win32":
        import msvcrt

        ch = msvcrt.getwch()
        if ch in ("\x00", "\xe0"):  # arrows / function keys: discard the second code
            msvcrt.getwch()
            return None
        return ch
    line = input()
    return line[:1] or None


# --------------------------------------------------------------------------- policy edits


def _validated(policy: Policy) -> Policy:
    build_classes(policy)  # raises PolicyError
    return policy


def toggle_setting(policy: Policy, option: str) -> Policy:
    name = TOGGLES[option]
    return _validated(replace(policy, **{name: not getattr(policy, name)}))


def set_exclusions(policy: Policy, text: str) -> Policy:
    return _validated(replace(policy, excluded_chars=normalize_exclusions(text)))


def set_length(policy: Policy, text: str) -> Policy:
    text = text.strip()
    if not (text.isascii() and text.isdigit()):
        raise PolicyError("length must be a number")
    return _validated(replace(policy, length=int(text)))


def reset_settings(policy: Policy) -> Policy:
    """Defaults for everything on the settings screen; the length is kept."""
    return _validated(Policy(length=policy.length))


def ordered(chars) -> str:
    return "".join(ch for ch in BASE_CHARS if ch in chars)


def masked(password: str) -> str:
    """Screen-share mode: same length, no characters revealed."""
    return MASK_CHAR * len(password)


# --------------------------------------------------------------------------- console


class Console:
    def __init__(self) -> None:
        self.vt = False
        self.color = False
        self._handle = None
        self._orig_mode = None

    def setup(self) -> None:
        self.vt = self._enable_vt() if sys.platform == "win32" else True
        self.color = self.vt and "NO_COLOR" not in os.environ

    def _enable_vt(self) -> bool:
        try:
            import ctypes
            from ctypes import wintypes

            k32 = ctypes.WinDLL("kernel32", use_last_error=True)
            k32.GetStdHandle.argtypes = [wintypes.DWORD]
            k32.GetStdHandle.restype = wintypes.HANDLE
            k32.GetConsoleMode.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
            k32.GetConsoleMode.restype = wintypes.BOOL
            k32.SetConsoleMode.argtypes = [wintypes.HANDLE, wintypes.DWORD]
            k32.SetConsoleMode.restype = wintypes.BOOL

            handle = k32.GetStdHandle(-11 & 0xFFFFFFFF)  # STD_OUTPUT_HANDLE
            if not handle or handle == ctypes.c_void_p(-1).value:
                return False
            mode = wintypes.DWORD()
            if not k32.GetConsoleMode(handle, ctypes.byref(mode)):
                return False
            if not k32.SetConsoleMode(handle, mode.value | 0x0004):  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
                return False
            self._k32, self._handle, self._orig_mode = k32, handle, mode.value
            return True
        except (OSError, AttributeError):
            return False

    def restore(self) -> None:
        if self.vt:
            sys.stdout.write("\x1b[0m")
            sys.stdout.flush()
        if self._orig_mode is not None:
            self._k32.SetConsoleMode(self._handle, self._orig_mode)
            self._orig_mode = None

    def paint(self, text: str, code: str) -> str:
        if not self.color:
            return text
        return f"\x1b[{code}m{text}\x1b[0m"

    def _clear_seq(self) -> str:
        # Same effect as `cls`: screen and scrollback are cleared.
        return "\x1b[2J\x1b[3J\x1b[H" if self.vt else "\n" * 40

    def clear(self) -> None:
        sys.stdout.write(self._clear_seq())
        sys.stdout.flush()

    def render(self, lines: list[str]) -> None:
        sys.stdout.write(self._clear_seq() + "\n".join(lines) + "\n")
        sys.stdout.flush()


# --------------------------------------------------------------------------- app


class QuitRequested(Exception):
    pass


class App:
    def __init__(self, console: Console) -> None:
        self.c = console
        self.policy = Policy()
        self.result: Result | None = None
        self.status: tuple[str, bool] | None = None  # (text, is_error)
        self.hidden = False
        self.auto_clear = True
        self._lock = threading.Lock()
        self._clear_timer: threading.Timer | None = None
        self._pending_seq: int | None = None
        self._notice: str | None = None  # set by the timer thread, shown on the next redraw

    def _consume_notice(self) -> None:
        with self._lock:
            notice, self._notice = self._notice, None
        if notice and not (self.status and self.status[1]):
            self._ok(notice)

    # ---- clipboard auto-clear

    def _schedule_clear(self, seq: int) -> None:
        with self._lock:
            if self._clear_timer:
                self._clear_timer.cancel()
            self._pending_seq = seq
            self._clear_timer = threading.Timer(AUTO_CLEAR_SECONDS, self._auto_clear, args=(seq,))
            self._clear_timer.daemon = True
            self._clear_timer.start()

    def _cancel_clear(self) -> None:
        with self._lock:
            if self._clear_timer:
                self._clear_timer.cancel()
            self._clear_timer = None
            self._pending_seq = None

    def _auto_clear(self, seq: int) -> None:
        """Timer thread: clear only if this copy is still the pending one and nobody overwrote it."""
        with self._lock:
            if self._pending_seq != seq:
                return
            self._pending_seq = None
            self._clear_timer = None
            try:
                if clear_if_unchanged(seq):
                    self._notice = "CLIPBOARD CLEARED"
            except (ClipboardError, OSError):
                pass  # nowhere to report from a background thread; never crash

    def shutdown(self) -> None:
        """On exit a pending password is cleared at once instead of outliving the program."""
        with self._lock:
            if self._clear_timer:
                self._clear_timer.cancel()
            seq, self._pending_seq, self._clear_timer = self._pending_seq, None, None
        if seq is not None:
            try:
                clear_if_unchanged(seq)
            except (ClipboardError, OSError):
                pass

    # ---- helpers

    def _ok(self, text: str) -> None:
        self.status = (text, False)

    def _error(self, text: str) -> None:
        self.status = (text, True)

    def _status_lines(self) -> list[str]:
        if not self.status:
            return [""]
        text, is_error = self.status
        if is_error:
            return ["  " + self.c.paint("> ERROR: " + text, RED)]
        return ["  " + self.c.paint("> " + text, BRIGHT)]

    def _prompt(self, text: str, plain: bool = False) -> str:
        try:
            return input(text if plain else self.c.paint(text, BRIGHT))
        except (EOFError, KeyboardInterrupt):
            raise QuitRequested from None

    def _key(self) -> str | None:
        try:
            action = map_key(read_key())
        except (EOFError, KeyboardInterrupt):
            raise QuitRequested from None
        if action == "quit":
            raise QuitRequested
        return action

    def _apply(self, change) -> bool:
        try:
            self.policy = change(self.policy)
            return True
        except PolicyError as exc:
            self._error(str(exc))
            return False

    def _keys(self, text: str) -> str:
        """Colour `[X]` markers red and the rest grey."""
        out, i = [], 0
        while i < len(text):
            if text[i] == "[":
                j = text.index("]", i) + 1
                out.append(self.c.paint(text[i:j], RED))
                i = j
            else:
                j = text.find("[", i)
                j = len(text) if j == -1 else j
                out.append(self.c.paint(text[i:j], KEY))
                i = j
        return "".join(out)

    # ---- main menu

    def _banner(self) -> list[str]:
        # Q-tools standard: blocks and the frame "wave" are both red.
        return [self.c.paint(row, RED) for row in BANNER]

    def _header(self) -> list[str]:
        pairs = (("AUTHOR", "AcidOsint"), ("BUILD", "personal"),
                 ("VERSION", __version__), ("UNIT", "Q3 PASS"))
        plain = " | ".join(f"{k} {v}" for k, v in pairs)
        # Q-tools standard: the whole header line and the separator are one grey tone.
        return [self.c.paint(plain, KEY), self.c.paint("=" * len(plain), KEY)]

    def run(self) -> None:
        try:
            while self._main_menu():
                pass
        except QuitRequested:
            pass

    def _main_menu(self) -> bool:
        items = ("GENERATE PASSWORD", "SETTINGS", "ABOUT", "EXIT")
        lines = self._banner() + [""] + self._header() + [""]
        lines += [self.c.paint(f"  {n:02d} * {name}", RED) for n, name in enumerate(items, 1)]
        lines += [""]
        self._consume_notice()
        if self.status:
            lines += self._status_lines() + [""]
        self.c.render(lines)
        choice = self._prompt("Choice > ", plain=True).strip()
        self.status = None
        if choice in ("1", "01"):
            self._generate_screen()
        elif choice in ("2", "02"):
            self._settings_screen()
        elif choice in ("3", "03"):
            self._about_screen()
        elif choice in ("4", "04"):
            return False
        else:
            self._error("INVALID CHOICE")
        return True

    # ---- generate

    def _regenerate(self) -> None:
        try:
            self.result = generate(self.policy)
        except PolicyError as exc:
            self.result = None
            self._error(str(exc))

    def _copy(self) -> None:
        if self.result is None:
            self._error("nothing to copy")
            return
        with self._lock:
            self._notice = None  # an older "cleared" notice must not hide this copy's status
        try:
            seq = copy_text(self.result.password)
        except ClipboardError as exc:
            if exc.reason == BUSY:
                self._error("CLIPBOARD BUSY, PRESS C TO RETRY")
            elif exc.reason == NOT_SUPPORTED:
                self._error("CLIPBOARD NOT SUPPORTED ON THIS OS")
            else:
                self._error(f"COPY FAILED ({exc.reason}, WinError {exc.winerror})")
            return
        if self.auto_clear:
            self._schedule_clear(seq)
            self._ok(f"COPIED TO CLIPBOARD, CLEARS IN {AUTO_CLEAR_SECONDS}s")
        else:
            self._cancel_clear()
            self._ok("COPIED TO CLIPBOARD")

    def _draw_generate(self) -> None:
        self._consume_notice()
        p, r = self.policy, self.result
        classes = "".join(
            sym if on else "-"
            for sym, on in (("a", p.use_lower), ("A", p.use_upper), ("0", p.use_digits), ("#", p.use_symbols))
        )
        info = (
            f"LENGTH {p.length} | SET {' '.join(classes)} | "
            f"AMBIGUOUS {'OFF' if p.exclude_ambiguous else 'ON'} | "
            f"EXCLUDED {ordered(p.excluded_chars) or 'none'} | "
            f"REQUIRE {'ON' if p.require_each else 'OFF'}"
        )
        lines = [
            "",
            self.c.paint("  01 * GENERATE PASSWORD", RED),
            self.c.paint(SEPARATOR, FRAME),
            "  " + self.c.paint(info, KEY),
            "  " + self.c.paint(f"ALPHABET {r.alphabet_size}" if r else "ALPHABET -", KEY),
            "",
            "      " + (
                self.c.paint(masked(r.password) if self.hidden else r.password, BRIGHT)
                if r else self.c.paint("-", KEY)
            ),
            "",
            "  " + self.c.paint(f"ENTROPY {r.entropy_bits:.1f} bit" if r else "ENTROPY -", VALUE),
            self.c.paint(SEPARATOR, FRAME),
            "  " + self._keys(
                f"[R] NEW  [C] COPY  [H] {'SHOW' if self.hidden else 'HIDE'}  "
                f"[X] SYMBOLS {'ON' if p.use_symbols else 'OFF'}  [S] SETTINGS  [B] BACK"
            ),
            "  " + self._keys("LENGTH  [1] 10  [2] 12  [3] 16  [4] 20  [5] 24  [6] 32  [L] CUSTOM"),
            "",
        ]
        self.c.render(lines + self._status_lines())

    def _generate_screen(self) -> None:
        self._regenerate()
        while True:
            self._draw_generate()
            action = self._key()
            if action is None:
                continue
            self.status = None
            if action == "new":
                self._regenerate()
            elif action == "copy":
                self._copy()
            elif action == "hide":
                self.hidden = not self.hidden
            elif action == "symbols":
                if self._apply(lambda p: toggle_setting(p, "4")):
                    self._regenerate()
            elif action in QUICK_LENGTHS:
                length = QUICK_LENGTHS[action]
                if self._apply(lambda p: _validated(replace(p, length=length))):
                    self._regenerate()
            elif action == "custom":
                text = self._prompt(f"  Length ({MIN_LENGTH}-{MAX_LENGTH}) > ")
                if text.strip() and self._apply(lambda p: set_length(p, text)):
                    self._regenerate()
            elif action == "settings":
                self._settings_screen()
                self.status = None
                self._regenerate()
            elif action == "back":
                self.result = None
                return

    # ---- settings

    def _draw_settings(self) -> None:
        self._consume_notice()
        p = self.policy

        def onoff(flag: bool) -> str:
            return self.c.paint("ON ", BRIGHT) if flag else self.c.paint("OFF", RED)

        def row(key: str, label: str, chars: str, flag: bool, extra: str = "") -> str:
            cell = (f"{label:<16}{chars}" if len(label) < 16 else f"{label} {chars}".rstrip()).ljust(27)
            text = self._keys(f"[{key}] ") + self.c.paint(cell, VALUE)
            return "  " + text + onoff(flag) + (self.c.paint("   " + extra, KEY) if extra else "")

        lines = [
            "",
            self.c.paint("  02 * SETTINGS", RED),
            self.c.paint(SEPARATOR, FRAME),
            row("1", "Lowercase", "a-z", p.use_lower),
            row("2", "Uppercase", "A-Z", p.use_upper),
            row("3", "Digits", "0-9", p.use_digits),
            row("4", "Symbols", '!"#$...', p.use_symbols),
            row("5", "Exclude ambiguous", "", p.exclude_ambiguous, " ".join(AMBIGUOUS)),
            row("6", "Require each class", "", p.require_each),
            "  " + self._keys("[7] ") + self.c.paint(f"{'Exclude custom chars':<27}", VALUE)
            + self.c.paint(ordered(p.excluded_chars) or "none", BRIGHT),
            row("8", "Clear clipboard after", f"{AUTO_CLEAR_SECONDS}s", self.auto_clear),
            row("9", "Hide password on screen", "", self.hidden),
            "  " + self._keys("[D] ") + self.c.paint("Reset to defaults", VALUE),
            "  " + self._keys("[B] ") + self.c.paint("Back", VALUE),
            "",
        ]
        self.c.render(lines + self._status_lines())

    def _settings_screen(self) -> None:
        while True:
            self._draw_settings()
            action = self._key()
            if action is None:
                continue
            self.status = None
            if action in TOGGLES:
                self._apply(lambda p: toggle_setting(p, action))
            elif action == "7":
                text = self._prompt("  Exclude chars (empty = clear) > ")
                self._apply(lambda p: set_exclusions(p, text))
            elif action == "8":
                self.auto_clear = not self.auto_clear
                if not self.auto_clear:
                    self._cancel_clear()
            elif action == "9":
                self.hidden = not self.hidden
            elif action == "reset":
                self._apply(reset_settings)
            elif action == "back":
                return

    # ---- about

    def _about_screen(self) -> None:
        lines = [
            "",
            self.c.paint("  03 * ABOUT", RED),
            self.c.paint(SEPARATOR, FRAME),
            "  " + self.c.paint(f"Q3 PASS {__version__}  |  AUTHOR AcidOsint", VALUE),
            "  " + self.c.paint("RANDOMNESS  secrets -> OS CSPRNG (Windows: BCryptGenRandom)", KEY),
            "  " + self.c.paint("NO NETWORK CALLS | NO SECRET STORAGE | NO HISTORY", VALUE),
            "",
            "  " + self.c.paint("Does not protect against a compromised system, keyloggers or screen capture.", KEY),
            "  " + self.c.paint("Clipboard privacy flags are honoured by Windows, not necessarily by", KEY),
            "  " + self.c.paint("third-party clipboard managers. See README.md.", KEY),
            "",
            "  " + self._keys("[B] BACK"),
        ]
        while True:
            self.c.render(lines)
            if self._key() == "back":
                return
