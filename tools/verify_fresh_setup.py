"""Test a clean source install using public software only, in an owned temp folder.

Explicit --download permits public pinned downloads. No operator input/profile can
be supplied. This tests software bootstrap, never scans media or opens the GUI.
"""
import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from videomate.dependencies import platform_tag


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--download", action="store_true", required=True)
    parser.parse_args()
    tag = platform_tag()
    with tempfile.TemporaryDirectory(prefix="videomate-fresh-software-") as temporary:
        stage = Path(temporary) / "Software space & unicode Ω"
        stage.mkdir()
        shutil.copytree(ROOT / "src/videomate", stage / "src/videomate", ignore=shutil.ignore_patterns("__pycache__"))
        for name in ("start.bat", "start.sh", "start.command", "tools/bootstrap.py", "tools/install_ffmpeg.py",
                     "tools/install_python.py", "tools/bootstrap_runtime.ps1", "tools/bootstrap_runtime.sh",
                     "dependencies/sources.json", "dependencies/python-sources.json", "dependencies/runtime-bootstrap.tsv",
                     "dependencies/licenses/ffmpeg-GPLv3.txt"):
            target = stage / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, target)
        env = {k: v for k, v in os.environ.items() if not k.startswith(("PYTHON", "CONDA", "VIDEOMATE_")) and k not in {"TCL_LIBRARY", "TK_LIBRARY", "VIRTUAL_ENV"}}
        env["PATH"] = str(Path(os.environ["SystemRoot"]) / "System32") if os.name == "nt" else "/usr/bin:/bin"
        if os.name == "nt":
            # With no Python on PATH, the actual launcher must bootstrap it.
            launcher = [str(stage / "start.bat")]
        else:
            # /usr/bin may contain Python. Exercise the no-Python helper directly,
            # then verify the launcher selects the newly installed local runtime.
            subprocess.run(["/bin/sh", str(stage / "tools/bootstrap_runtime.sh"), tag, "--yes"], env=env, check=True, timeout=900)
            launcher = ["/bin/sh", str(stage / "start.sh")]
        for options in (["--yes", "--check"], ["--offline", "--check"], ["--offline", "--cli", "--version"]):
            subprocess.run(launcher + options, cwd=temporary, env=env, shell=os.name == "nt", check=True, timeout=900)
        print("Fresh automatic setup and subsequent offline launch passed for " + tag + ".")


if __name__ == "__main__":
    main()
