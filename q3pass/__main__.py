"""Entry point: python -m q3pass"""

import sys


def main() -> int:
    if sys.version_info < (3, 13):
        print("Q3 PASS requires Python 3.13 or newer.", file=sys.stderr)
        return 1
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        print("Q3 PASS: interactive terminal required.", file=sys.stderr)
        return 2

    from .ui import App, Console

    console = Console()
    console.setup()
    app = App(console)
    error = None
    try:
        app.run()
    except KeyboardInterrupt:
        pass
    except Exception as exc:  # no traceback, no values: only the exception type
        error = type(exc).__name__
    finally:
        app.shutdown()     # pending clipboard auto-clear happens now
        console.clear()    # no password left on screen or in scrollback
        console.restore()
    if error:
        print(f"INTERNAL ERROR: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
