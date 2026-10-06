"""Verify a freshly built public-software kit; optionally exercise it on its native host.

Never pass operator media, private reports or unrelated archives to this tool.
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from videomate.dependencies import platform_tag


def verify(archive, execute=False):
    with archive.open("rb") as file:
        checksum = hashlib.file_digest(file, "sha256").hexdigest()
    if checksum != archive.with_suffix(archive.suffix + ".sha256").read_text().strip():
        raise ValueError("Archive checksum mismatch")
    with zipfile.ZipFile(archive) as package:
        manifest = json.loads(package.read("bundle-manifest.json"))
        names = package.namelist()
        if len(names) != len(set(names)) or set(names) != set(manifest["files"]) | {"bundle-manifest.json"}:
            raise ValueError("Archive manifest membership mismatch")
        for name, expected in manifest["files"].items():
            path = PurePosixPath(name)
            if path.is_absolute() or ".." in path.parts or "\\" in name or ":" in name:
                raise ValueError("Unsafe archive member")
            with package.open(name) as file:
                if hashlib.file_digest(file, "sha256").hexdigest() != expected:
                    raise ValueError("Packaged software checksum mismatch")
        if not manifest["platform"].startswith("windows-"):
            for name in ("start.sh", "start.command", "dependencies/ffmpeg/" + manifest["platform"] + "/bin/ffmpeg",
                         "dependencies/ffmpeg/" + manifest["platform"] + "/bin/ffprobe"):
                if package.getinfo(name).external_attr >> 16 & 0o111 != 0o111:
                    raise ValueError("Unix executable permissions missing")
        if execute:
            if manifest["platform"] != platform_tag():
                raise ValueError("Cannot execute a foreign-platform kit")
            with tempfile.TemporaryDirectory(prefix="videomate-kit-check-") as temporary:
                software = Path(temporary) / "Software space & unicode Ω"
                package.extractall(software)  # exact software archive validated above
                if os.name != "nt":
                    for member in package.infolist():
                        (software / member.filename).chmod((member.external_attr >> 16) & 0o777 or 0o644)
                environment = os.environ.copy()
                for name in tuple(environment):
                    if name.startswith(("PYTHON", "CONDA", "VIDEOMATE_")) or name in {"TCL_LIBRARY", "TK_LIBRARY", "VIRTUAL_ENV"}:
                        environment.pop(name)
                if not manifest["python_included"]:
                    environment["VIDEOMATE_PYTHON"] = sys.executable
                else:
                    environment["PATH"] = "/usr/bin:/bin" if os.name != "nt" else str(Path(os.environ["SystemRoot"]) / "System32")
                launcher = [str(software / "start.bat")] if os.name == "nt" else ["/bin/sh", str(software / "start.sh")]
                for args in (["--offline", "--check"], ["--offline", "--cli", "--version"], ["--offline", "--self-test"]):
                    subprocess.run(launcher + args, shell=os.name == "nt", check=True, timeout=240,
                                   cwd=temporary, env=environment)
        print(json.dumps({"platform": manifest["platform"], "files_verified": len(manifest["files"]),
                          "python_included": manifest["python_included"], "native_execution": execute}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    verify(args.archive, args.execute)
