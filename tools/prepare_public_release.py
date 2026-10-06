"""Create a new source-only Git repository from the reviewed staged index.

No old history, refs, remotes, hooks, ignored files, or release assets are copied.
No download or publication occurs. Existing destinations are never replaced.
"""
import argparse
import os
import subprocess
import sys
from pathlib import Path

from audit_public_release import audit, git, source_entries


def prepare(output, cwd=None):
    files, findings = audit(cwd=cwd)
    if findings:
        raise ValueError("The staged source audit requires review before publication.")
    # Publication commits use only the owner's existing public noreply identity.
    identity = git("log", "-1", "--format=%ae", cwd=cwd).decode("ascii").strip()
    if not identity.endswith("@users.noreply.github.com"):
        raise ValueError("A public noreply identity is required for the publication commit.")
    root = Path(git("rev-parse", "--show-toplevel", cwd=cwd).decode().strip()).resolve()
    output = Path(os.path.abspath(output))
    if output == root or root in output.parents:
        raise ValueError("Select a new publication directory outside the source checkout.")
    for parent in (output, *output.parents):
        if parent.is_symlink():
            raise ValueError("Publication paths must not use symlinked ancestors.")
        if any(parent.name.casefold().startswith(name) for name in ("onedrive", "dropbox", "google drive", "icloud drive")):
            raise ValueError("Select non-synced local publication storage.")
    # Gather and validate all source entries before creating the destination.
    entries = list(source_entries(cwd=cwd))
    output.mkdir(mode=0o700, exist_ok=False)
    environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    names = []
    for mode, oid, _, raw_name in entries:
        name = raw_name.decode("utf-8")
        target = output / name
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as file:
            file.write(git("cat-file", "blob", oid.decode("ascii"), cwd=cwd))
        target.chmod(0o755 if mode == b"100755" else 0o644)
        names.append(name)
    def run(*args):
        subprocess.run(["git", *args], cwd=output, env=environment, check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    run("init", "--quiet", "--template=", "--initial-branch=main")
    run("config", "user.name", "samuel-zhang01")
    run("config", "user.email", identity)
    # Force the exact executable bits from the reviewed index on every host.
    # No global hooks/signing configuration may run during source preparation.
    for offset in range(0, len(names), 100):
        run("-c", "core.hooksPath=", "add", "--", *names[offset:offset + 100])
    for mode, _, _, raw_name in entries:
        run("update-index", "--chmod=" + ("+x" if mode == b"100755" else "-x"), "--", raw_name.decode("utf-8"))
    run("-c", "core.hooksPath=", "-c", "commit.gpgsign=false", "commit", "--quiet", "-m", "Prepare VideoMate public source preview")
    expected = git("write-tree", cwd=cwd).strip()
    actual = git("rev-parse", "HEAD^{tree}", cwd=output).strip()
    if expected != actual or audit(history=True, cwd=output)[1]:
        raise ValueError("Publication snapshot verification failed; no publication occurred.")
    return files


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="New local source publication directory.")
    args = parser.parse_args()
    try:
        count = prepare(args.output)
    except (OSError, ValueError, UnicodeError, subprocess.CalledProcessError) as error:
        print(str(error) if isinstance(error, ValueError) else "Source snapshot creation failed; details withheld.", file=sys.stderr)
        return 1
    print(f"Prepared and tree-verified {count} source files in a new single-commit repository. Nothing was published.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
