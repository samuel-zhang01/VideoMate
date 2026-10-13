"""Local-by-default checkpoint policy; no real data or runner mutation."""
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('vm_ci_support', ROOT / 'tools/ci_support.py')
support = importlib.util.module_from_spec(spec)
spec.loader.exec_module(support)


class CIRoutingTests(unittest.TestCase):
    def test_default_runs_both_python_versions_only_on_matching_local_listeners(self):
        for repo, slug in support.REPOS.items():
            rows = support.matrix('tests', repo)['include']
            self.assertEqual(len(rows), 4)
            self.assertEqual({(r['platform'], r['python']) for r in rows},
                             {(p, v) for p in ('linux-x86_64', 'macos-arm64') for v in ('3.11', '3.13')})
            for row in rows:
                self.assertFalse(row['hosted'])
                self.assertEqual(row['runner'], ['local-macos' if row['platform']=='macos-arm64' else 'deploy-vps', slug])

    def test_paid_hosted_opt_in_preserves_all_eight_original_platform_version_combinations(self):
        rows = support.matrix('tests', 'samuel-zhang01/VideoMate', True)['include']
        self.assertEqual(len(rows), 8)
        self.assertEqual({(r['os'],r['python']) for r in rows},
                         {(p,v) for p in ('windows-latest','macos-15','ubuntu-24.04','ubuntu-24.04-arm') for v in ('3.11','3.13')})
        self.assertEqual({r['platform'] for r in rows if r['hosted']}, {'windows-x86_64','linux-arm64'})

    def test_unknown_repository_cannot_select_owner_listeners(self):
        with self.assertRaises(KeyError):
            support.matrix('tests', 'untrusted/VideoMate')

    def test_manual_release_retains_all_platform_definitions_but_defaults_to_two_local_builds(self):
        for hosted, count in ((False,2),(True,4)):
            rows = support.matrix('release','samuel-zhang01/VideoMate-private',hosted)['include']
            self.assertEqual(len(rows),count)
            self.assertTrue(all(r['python']=='3.13' for r in rows))
            self.assertEqual({r['platform'] for r in rows if r['desktop']},
                             {'macos-arm64','windows-x86_64'} if hosted else {'macos-arm64'})
