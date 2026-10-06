"""Entry point for the self-contained, offline desktop application."""
import json
import sys
from pathlib import Path


def main():
    if sys.argv[1:] == ["--check"]:
        try:
            from videomate.setup_local import check_backend
            import tkinter
            check_backend()
            return 0
        except Exception:
            return 2
    if len(sys.argv) == 3 and sys.argv[1] == "--self-test":
        # Exclusive output: never replace an existing report. Self-test accepts no media inputs.
        with Path(sys.argv[2]).open("x", encoding="utf-8") as output:
            try:
                from videomate.selftest import run_self_test
                report = run_self_test()
            except Exception:
                report = {"status": "failed", "synthetic_only": True}
            json.dump(report, output, indent=2)
        return 0 if report["status"] == "passed" else 1
    config_path = Path(sys.argv[2]) if len(sys.argv) == 3 and sys.argv[1] == "--config" else None
    if sys.argv[1:] and config_path is None:
        return 2  # Never silently ignore misspelled options or launch the GUI.
    from videomate.gui import launch
    try:
        return launch(config_path=config_path)
    except Exception:
        # No tracebacks or private exception values in packaged GUI errors.
        try:
            import tkinter.messagebox
            tkinter.messagebox.showerror("VideoMate", "The desktop application could not start. Please use a complete native VideoMate package.")
        except Exception:
            pass
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
