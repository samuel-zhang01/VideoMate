"""Publication boundary checks use fresh source-only Git repositories."""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import audit_public_release as audit
import prepare_public_release as publication
import release_documents


class PublicReleaseTests(unittest.TestCase):
    def test_release_documents_are_complete_and_exclude_unreviewed_notes(self):
        documents = release_documents.source_documents(ROOT)
        self.assertEqual(len(documents), len(set(documents)))
        self.assertIn("LICENSE", documents)
        expected = {name.decode() for name in audit.git("ls-files", "-z", "--", "docs/").split(b"\0")
                    if name and name.endswith(b".md")}
        self.assertEqual({name for name in documents if name.startswith("docs/")}, expected)
        with tempfile.TemporaryDirectory(prefix="videomate-document-test-") as temporary:
            source = Path(temporary).resolve()
            for name in documents:
                target = source / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("Synthetic public document")
            (source / "docs" / "SYNTHETIC_PRIVATE_NOTE.md").write_text("Excluded local fixture")
            self.assertNotIn("docs/SYNTHETIC_PRIVATE_NOTE.md", release_documents.source_documents(source))

    def test_excluded_entry_is_rejected_before_any_blob_is_read(self):
        entries = [(b"100644", b"0" * 40, True, b"private/SYNTHETIC_NAME.json")]
        with patch.object(audit, "source_entries", return_value=entries), patch.object(audit, "git") as git:
            count, findings = audit.audit()
        git.assert_not_called()
        self.assertEqual(count, 0)
        self.assertIn("excluded_path", findings)

    def test_categories_never_include_secret_values(self):
        value = b"ghp_" + b"SYNTHETIC" * 5
        findings = audit.content_categories(value)
        self.assertEqual(findings, ["github_token"])
        self.assertNotIn(value.decode(), repr(findings))
        self.assertEqual(audit.content_categories(b"https://example.invalid/public/source.zip"), [])

    def test_symlink_entry_is_rejected_before_blob_read(self):
        entries = [(b"120000", b"0" * 40, True, b"README.md")]
        with patch.object(audit, "source_entries", return_value=entries), patch.object(audit, "git") as git:
            _, findings = audit.audit()
        git.assert_not_called()
        self.assertIn("link_or_nonordinary_entry", findings)

    def test_clean_snapshot_excludes_history_ignored_files_and_remote_settings(self):
        with tempfile.TemporaryDirectory(prefix="videomate-public-source-") as temporary:
            base = Path(temporary).resolve()
            source, output = base / "source", base / "publication"
            source.mkdir()
            env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
            def git(*args):
                return subprocess.check_output(["git", *args], cwd=source, env=env, stderr=subprocess.DEVNULL)
            git("init", "--quiet", "--template=")
            git("config", "user.name", "Synthetic contributor")
            git("config", "user.email", "synthetic@users.noreply.github.com")
            (source / "README.md").write_text("Synthetic historical disclosure\n")
            git("add", "README.md")
            git("-c", "core.hooksPath=", "-c", "commit.gpgsign=false", "commit", "-qm", "Synthetic private history")
            old_commit = git("rev-parse", "HEAD").strip()
            (source / "README.md").write_text("Reviewed synthetic public source\n")
            (source / ".gitignore").write_text("private/\n")
            (source / "private").mkdir()
            (source / "private" / "SYNTHETIC_IGNORED.txt").write_text("Never inspect or copy this fixture")
            git("add", "README.md", ".gitignore")
            git("remote", "add", "origin", "https://example.invalid/private-source")
            with patch.dict(os.environ, env, clear=True):
                self.assertEqual(publication.prepare(output, cwd=source), 2)
            self.assertFalse((output / "private").exists())
            self.assertEqual((output / "README.md").read_text(), "Reviewed synthetic public source\n")
            self.assertEqual(audit.git("rev-list", "--all", "--count", cwd=output).strip(), b"1")
            self.assertEqual(audit.git("remote", cwd=output), b"")
            self.assertEqual(audit.git("tag", cwd=output), b"")
            self.assertNotIn(old_commit, audit.git("rev-list", "--all", cwd=output))
            self.assertEqual(audit.git("write-tree", cwd=source), audit.git("rev-parse", "HEAD^{tree}", cwd=output))
            self.assertEqual(audit.audit(history=True, cwd=output)[1], {})
            with self.assertRaises(FileExistsError):
                publication.prepare(output, cwd=source)
            self.assertEqual(audit.git("rev-parse", "HEAD", cwd=source).strip(), old_commit)
