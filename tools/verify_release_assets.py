"""Verify only named VideoMate release archives and SHA sidecars, never media."""
import argparse
import hashlib
import re
from pathlib import Path


def verify(folder):
    count = 0
    for archive in (list(folder.glob("videomate-*-*.zip")) + list(folder.glob("videomate-*-*.AppImage"))
                    + list(folder.glob("videomate-*-macos-arm64.dmg"))):
        if not re.fullmatch(r"videomate-\d+\.\d+\.\d+-(?:windows-x86_64|windows-arm64|macos-arm64|linux-x86_64|linux-arm64)-(?:desktop|runtime|runtime-kit)\.zip|videomate-\d+\.\d+\.\d+-linux-(?:x86_64|arm64)\.AppImage|videomate-\d+\.\d+\.\d+-macos-arm64\.dmg", archive.name):
            raise ValueError("Unexpected release archive name")
        if archive.is_symlink():
            raise ValueError("Release archive cannot be a symlink")
        checksum = archive.with_suffix(archive.suffix + ".sha256")
        expected = checksum.read_text(encoding="ascii").strip()
        with archive.open("rb") as source:
            actual = hashlib.file_digest(source, "sha256").hexdigest()
        if expected != actual:
            raise ValueError("Release archive checksum mismatch")
        count += 1
    if not count:
        raise ValueError("No release archives found")
    print(f"Verified {count} release archive checksums.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path)
    verify(parser.parse_args().folder)
