"""Source-index protection is exercised against disposable Git repositories."""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("vm_repo_guard", ROOT / "tools/check_repository.py")
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


class RepositoryTests(unittest.TestCase):
    def test_bootstrap_catalog_matches_canonical_pins(self):
        records = [line.split("\t") for line in (ROOT / "dependencies/runtime-bootstrap.tsv").read_text().splitlines()]
        pins = json.loads((ROOT / "dependencies/python-sources.json").read_text())["platforms"]
        self.assertEqual(len(records), len(pins))
        self.assertEqual({row[0] for row in records}, set(pins))
        for tag, sha, name, url in records:
            self.assertEqual((sha, name, url), (pins[tag]["sha256"], pins[tag]["filename"], pins[tag]["url"]))
            self.assertTrue(url.startswith("https://"))

    def test_private_paths_and_dependencies_are_not_allowlisted(self):
        for name in ("settings.json", "inputs/clip.MP4", "docs/raw.log", "dependencies/ffmpeg/tool.exe",
                     "archive/builds/app.zip", "tests/fixture.mp4", "src/videomate/.env", "../README.md"):
            self.assertFalse(guard.allowed_path(name))
        self.assertTrue(guard.allowed_path("src/videomate/gui.py"))

    @unittest.skipUnless(shutil.which("git"), "Git not installed")
    def test_index_guard_accepts_source_and_rejects_large_binary_and_private_entries(self):
        with tempfile.TemporaryDirectory(prefix="videomate-index-test-") as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
            def check(name, content):
                subprocess.run(["git", "read-tree", "--empty"], cwd=root, env=env, check=True)
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
                subprocess.run(["git", "add", "--", name], cwd=root, env=env, check=True)
                return subprocess.run([sys.executable, str(ROOT / "tools/check_repository.py")], cwd=root, env=env, capture_output=True, timeout=20)
            self.assertEqual(check("README.md", b"source\n").returncode, 0)
            for name, data in (("README.md", b"x" * (guard.MAX_FILE_BYTES + 1)), ("README.md", b"binary\0"),
                               ("private/SYNTHETIC_SECRET_NAME.json", b"SYNTHETIC_PRIVATE_CANARY")):
                result = check(name, data)
                self.assertEqual(result.returncode, 1)
                self.assertNotIn(b"SYNTHETIC_SECRET_NAME", result.stderr)
                self.assertNotIn(b"SYNTHETIC_PRIVATE_CANARY", result.stderr)
