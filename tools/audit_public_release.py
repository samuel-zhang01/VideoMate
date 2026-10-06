"""Offline, redacted audit of Git source and optionally local history.

Unknown paths are refused before reading blobs; ignored working-tree data is
never enumerated. This heuristic check complements a separate Gitleaks scan
and human source review. It cannot certify the absence of unknown secrets.
"""
import argparse
import collections
import re
import subprocess
import sys
from pathlib import Path

# The commit hook uses isolated Python. Import only adjacent trusted tool code.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_repository import BRAND_BINARY_ASSETS, MAX_FILE_BYTES, allowed_path

# Exact obsolete project software/design paths previously reviewed as source.
# These are accepted only for history audit, never for publication/index use.
HISTORICAL_SOURCE_FILES = {
    "archive/design-v0.3.1/architecture.md",
    "archive/design-v0.3.1/preview_gui.py",
    "archive/design-v0.3.1/product-design.md",
    "archive/design-v0.3.1/validation-and-roadmap.md",
}
PATTERNS = {
    "private_key": rb"-----BEGIN (?:RSA |EC |OPENSSH |DSA |ENCRYPTED )?PRIVATE KEY-----",
    "github_token": rb"(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})",
    "cloud_access_key": rb"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b",
    "service_token": rb"(?:xox[baprs]-[A-Za-z0-9-]{15,}|sk-(?:proj-)?[A-Za-z0-9_-]{30,}|AIza[0-9A-Za-z_-]{35})",
    "credential_url": rb"https?://[^\s/<>]+:[^\s/@<>]+@",
    "personal_home_path": rb"(?:/(?:Users|home)/[A-Za-z0-9][^\s/<>\"']*|[A-Za-z]:\\Users\\[^\s\\<>\"']+)",
    "operator_derived_narrative": (
        rb"(?i)(?:sanitized (?:diagnostic )?export described|operator-stopped [0-9]+|"
        rb"previously supplied sanitized " rb"diagnostic export|explicitly approved " rb"non-sensitive collection|"
        rb"test folder " rb"named in|approved non-sensitive " rb"runs)"
    ),
}


def git(*args, cwd=None):
    # Never let Git errors echo path/config values to tool output.
    return subprocess.check_output(["git", *args], cwd=cwd, stderr=subprocess.DEVNULL)


def content_categories(data):
    return [name for name, pattern in PATTERNS.items() if re.search(pattern, data)]


def source_entries(history=False, cwd=None):
    if history:
        for commit in git("rev-list", "--all", cwd=cwd).splitlines():
            for entry in git("ls-tree", "-r", "-z", commit.decode("ascii"), cwd=cwd).split(b"\0"):
                if entry:
                    metadata, name = entry.split(b"\t", 1)
                    mode, kind, oid = metadata.split()
                    yield mode, oid, kind == b"blob", name
    else:
        for entry in git("ls-files", "--stage", "-z", cwd=cwd).split(b"\0"):
            if entry:
                metadata, name = entry.split(b"\t", 1)
                mode, oid, stage = metadata.split()
                yield mode, oid, stage == b"0", name


def audit(history=False, cwd=None):
    findings = collections.Counter()
    seen = set()
    files = 0
    for mode, oid, ordinary, raw_name in source_entries(history, cwd):
        name = raw_name.decode("utf-8", errors="replace")
        if not (allowed_path(name) or (history and name in HISTORICAL_SOURCE_FILES)):
            findings["excluded_path"] += 1
            continue
        if not ordinary or mode not in {b"100644", b"100755"}:
            findings["link_or_nonordinary_entry"] += 1
            continue
        if (name, oid) in seen:
            continue
        seen.add((name, oid))
        size = int(git("cat-file", "-s", oid.decode("ascii"), cwd=cwd))
        if size > MAX_FILE_BYTES:
            findings["oversize_source"] += 1
            continue
        files += 1
        if name in BRAND_BINARY_ASSETS:
            continue
        data = git("cat-file", "blob", oid.decode("ascii"), cwd=cwd)
        if b"\0" in data:
            findings["binary_source"] += 1
            continue
        findings.update(content_categories(data))
    # Git metadata can leak information independently of source blobs.
    if history:
        metadata = git("log", "--all", "--format=%B%n%an%n%ae%n%cn%n%ce", cwd=cwd)
        findings.update("commit_metadata_" + category for category in content_categories(metadata))
        emails = set(git("log", "--all", "--format=%ae%n%ce", cwd=cwd).splitlines())
        for email in emails:
            if not email.endswith(b"@users.noreply.github.com") and not email.endswith(b"@example.invalid"):
                findings["non_noreply_commit_email"] += 1
    if not files:
        findings["empty_source_index_or_history"] += 1
    return files, dict(sorted(findings.items()))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--history", action="store_true", help="Also inspect locally reachable history; no fetch.")
    args = parser.parse_args()
    try:
        files, findings = audit(args.history)
    except (OSError, ValueError, subprocess.CalledProcessError):
        print("Source audit could not complete; details withheld.", file=sys.stderr)
        return 2
    print(f"Reviewed {files} allowlisted source revisions; matched values and locators are never printed.")
    for category, count in findings.items():
        print(f"{category}: {count}")
    print("Audit requires review." if findings else "Source audit passed (bounded heuristic coverage).")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
