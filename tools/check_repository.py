"""Check the Git index, never working-tree media or private runtime directories."""
import subprocess
import sys
from pathlib import PurePosixPath

MAX_FILE_BYTES = 1024 * 1024
ROOT_FILES = {".gitignore", ".gitattributes", ".editorconfig", "README.md", "LICENSE", "AGENTS.md", "CONTRIBUTING.md",
              "SECURITY.md", "CHANGELOG.md", "THIRD_PARTY_NOTICES.md", "pyproject.toml", "start.bat", "start.sh", "start.command"}
DEPENDENCIES = {"README.md", "sources.json", "python-sources.json", "appimage-sources.json", "runtime-bootstrap.tsv", "licenses/ffmpeg-GPLv3.txt"}
BRAND_ASSETS = {"assets/videomate-mark.png", "assets/videomate-mark.svg", "assets/videomate.ico", "assets/videomate.icns"}
BRAND_BINARY_ASSETS = BRAND_ASSETS - {"assets/videomate-mark.svg"}


def allowed_path(name):
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or "\\" in name:
        return False
    if name in ROOT_FILES:
        return True
    if name in BRAND_ASSETS:
        return True
    parts = path.parts
    if not parts:
        return False
    root, suffix = parts[0], path.suffix
    if root == "src":
        return name.startswith("src/videomate/") and (suffix == ".py" or name == "src/videomate/export-schema.json")
    if root == "tests":
        return len(parts) == 2 and parts[1].startswith("test_") and suffix == ".py"
    if root == "tools":
        return len(parts) == 2 and suffix in {".py", ".sh", ".ps1", ".bat", ".txt", ".manifest"}
    if root == "docs":
        return suffix == ".md" and (len(parts) == 2 or
               (len(parts) == 3 and parts[1] == "development"))
    if root == "dependencies":
        return "/".join(parts[1:]) in DEPENDENCIES
    if root == ".github":
        return suffix in {".yml", ".md"} and len(parts) <= 3
    return name in {".githooks/pre-commit", "schemas/diagnostic-export-v1.schema.json",
                    "examples/diagnostic-export.synthetic.json", "archive/README.md"}


def check():
    entries = subprocess.check_output(["git", "ls-files", "--stage", "-z"]).split(b"\0")
    count, total, largest = 0, 0, 0
    for entry in filter(None, entries):
        metadata, name = entry.split(b"\t", 1)
        mode, oid, stage = metadata.split()
        # Reject unknown paths BEFORE reading their blobs. Never print their names.
        if not allowed_path(name.decode("utf-8", errors="replace")) or mode not in {b"100644", b"100755"} or stage != b"0":
            raise ValueError("Index contains a disallowed path, link or unresolved entry. Review locally; private names were withheld.")
        size = int(subprocess.check_output(["git", "cat-file", "-s", oid.decode("ascii")]))
        if size > MAX_FILE_BYTES:
            raise ValueError("Index contains a file over the 1 MiB source limit. Its name was withheld.")
        # Only allowlisted, small source blobs reach the binary-content check.
        if name.decode("utf-8", errors="replace") not in BRAND_BINARY_ASSETS and b"\0" in subprocess.check_output(["git", "cat-file", "blob", oid.decode("ascii")]):
            raise ValueError("Index contains binary content in a source file. Its name was withheld.")
        count, total, largest = count + 1, total + size, max(largest, size)
    print(f"Repository check passed: {count} source files, {total:,} bytes total; largest {largest:,} bytes.")


if __name__ == "__main__":
    try:
        check()
    except (ValueError, subprocess.CalledProcessError) as error:
        print(str(error) if isinstance(error, ValueError) else "Git index check failed.", file=sys.stderr)
        raise SystemExit(1)
