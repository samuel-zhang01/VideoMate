"""Migration and profiles only operate on exact newly generated test trees."""
import json
import os
import tempfile
import threading
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from videomate.errors import VideoMateError
from videomate.preferences import Preferences, load_preferences, save_preferences
from videomate.profiles import apply, builtins, describe_policy, extract, validate_profiles
from videomate.recovery import RecoveryOptions
from videomate.migration import inventory, migrate_local, verified_copy
from videomate.policy import LocalFileScope
from videomate.private_state import LIVE_REPORTS


class ProfileTests(unittest.TestCase):
    def test_legacy_settings_gain_automatic_cpu_lane_without_losing_force_choice(self):
        with tempfile.TemporaryDirectory(prefix="videomate-legacy-settings-generated-") as temporary:
            path = Path(temporary).resolve() / "settings.json"
            path.write_text(json.dumps({"schema_version": 1, "migration_cpu_encoding": False}), encoding="utf-8")
            legacy = load_preferences(path)
            self.assertTrue(legacy.migration_cpu_auto)
            self.assertFalse(legacy.migration_cpu_encoding)
            save_preferences(path, replace(legacy, migration_cpu_auto=False))
            disabled = load_preferences(path)
            self.assertFalse(disabled.migration_cpu_auto)
            self.assertFalse(disabled.migration_cpu_encoding)

    def test_profiles_roundtrip_processing_without_privacy_or_paths(self):
        original = Preferences(sensitive=True, workspace="", private_resume=True, retain_history=False,
                               migration_local_names=False, cpu_threads=4, migration_cpu_encoding=True)
        migrated = apply(original, "Migrate — MP4 video")
        self.assertEqual(migrated.workflow, "migrate")
        self.assertTrue(migrated.convert_all_mp4)
        self.assertTrue(migrated.sensitive)
        self.assertTrue(migrated.private_resume)
        self.assertFalse(migrated.migration_local_names)
        self.assertEqual(migrated.migration_unresolved, "exclude")
        self.assertTrue(migrated.hardware_decoding)
        self.assertTrue(migrated.hardware_encoding)
        self.assertTrue(migrated.migration_cpu_encoding)
        self.assertIn("software-encoding lane", describe_policy(migrated))
        smaller = apply(original, "Migrate — repair to MP4")
        self.assertFalse(smaller.convert_all_mp4)
        self.assertEqual(smaller.profile, "compatible_sdr")
        self.assertTrue(smaller.hardware_encoding)
        self.assertTrue(smaller.sensitive)
        options = extract(migrated)
        self.assertFalse({"workspace", "sensitive", "private_resume", "migration_local_names", "profiles"} & options.keys())
        saved = replace(original, profiles={"Invented preset": options})
        with tempfile.TemporaryDirectory(prefix="videomate-profile-generated-") as temporary:
            path = Path(temporary).resolve() / "settings.json"
            save_preferences(path, saved)
            restored = load_preferences(path)
            self.assertEqual(apply(restored, "Invented preset").workflow, "migrate")
        for name in builtins():
            apply(original, name).validate()

    def test_profile_rejects_private_fields_unbounded_names_and_bad_values(self):
        for value in ({"Invented": {"sensitive": False}}, {"Invented": {"workspace": "SECRET"}},
                      {"Invented": {"cpu_threads": -1}}, {"Invented": {"migration_unresolved": "delete"}},
                      {"\nSECRET": {}}, {"x" * 41: {}},
                      {str(i): {} for i in range(13)}):
            with self.assertRaises(VideoMateError):
                validate_profiles(value)

    def test_migration_selection_and_copy_change_guards_use_generated_markers(self):
        from videomate.inspection import _fingerprint
        with tempfile.TemporaryDirectory(prefix="videomate-migration-guards-") as temporary:
            root = Path(temporary).resolve()
            source = root / "source"
            source.mkdir()
            marker = source / "invented.txt"
            marker.write_bytes(b"Generated marker")
            with self.assertRaises(VideoMateError):
                inventory([str(source)], root / "workspace", source / "output", root / "code")
            with self.assertRaises(VideoMateError) as permission:
                migrate_local([str(source)], root / "workspace", sensitive=True, local_names=False)
            self.assertEqual(permission.exception.code, "migration_names_required")
            before = _fingerprint(marker)
            marker.write_bytes(b"Generated changed marker")
            staging = root / "staging"
            staging.mkdir()
            with self.assertRaises(VideoMateError):
                verified_copy(marker, root / "copy.txt", staging, LocalFileScope(frozenset({marker}), root / "code"),
                              threading.Event(), expected=before, keep_times=True)
            self.assertFalse((root / "copy.txt").exists())

    def test_cli_migration_preset_and_explicit_overrides(self):
        import contextlib
        import io
        from videomate.cli import main
        with tempfile.TemporaryDirectory(prefix="videomate-migration-cli-") as temporary:
            with patch("videomate.migration.migrate_local", return_value=0) as migrate, contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(["migrate", "--input", "GENERATED_SELECTION", "--workspace", temporary,
                    "--preset", "Migrate — MP4 video", "--local-output-names", "--rate-control", "bitrate", "--video-bitrate-kbps", "1200", "--unresolved", "copy"]), 0)
                self.assertTrue(migrate.call_args.kwargs["local_names"])
                self.assertTrue(migrate.call_args.kwargs["recovery"].convert_all_mp4)
                self.assertEqual(migrate.call_args.kwargs["recovery"].video_bitrate_kbps, 1200)
                self.assertTrue(migrate.call_args.kwargs["execute"])
                self.assertEqual(migrate.call_args.kwargs["package_layout"], "direct")
                self.assertTrue(migrate.call_args.kwargs["migration_cpu_auto"])
                self.assertFalse(migrate.call_args.kwargs["migration_cpu_encoding"])
                self.assertTrue(migrate.call_args.kwargs["recovery"].partial_salvage)
                self.assertEqual(migrate.call_args.kwargs["unresolved"], "copy")
            with patch("videomate.migration.migrate_local", return_value=0) as migrate, contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(["migrate", "--input", "GENERATED_SELECTION", "--workspace", temporary,
                    "--local-output-names", "--migration-cpu-encoding"]), 0)
                self.assertTrue(migrate.call_args.kwargs["migration_cpu_encoding"])
                self.assertFalse(migrate.call_args.kwargs["migration_cpu_auto"])
            with patch("videomate.migration.migrate_local", return_value=0) as migrate, contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(["migrate", "--input", "GENERATED_SELECTION", "--workspace", temporary,
                    "--local-output-names", "--no-migration-cpu-encoding"]), 0)
                self.assertFalse(migrate.call_args.kwargs["migration_cpu_encoding"])
                self.assertFalse(migrate.call_args.kwargs["migration_cpu_auto"])
            with patch("videomate.migration.migrate_local", return_value=0) as migrate, contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(["migrate", "--input", "GENERATED_SELECTION", "--workspace", temporary,
                                       "--preset", "Migrate · selective HEVC MP4", "--local-output-names"]), 0)
                selected = migrate.call_args.kwargs["recovery"]
                self.assertTrue(selected.convert_noncompliant_hevc)
                self.assertEqual((selected.video_codec, selected.audio_normalization), ("hevc", "playback"))


@unittest.skipUnless(os.environ.get("VIDEOMATE_TEST_FFMPEG") and os.environ.get("VIDEOMATE_TEST_FFPROBE"), "Explicit generated-media backend not configured")
class MigrationIntegrationTests(unittest.TestCase):
    def setUp(self):
        from test_recovery_integration import RecoveryIntegrationTests
        f = self.fixture = RecoveryIntegrationTests()
        f.setUp()
        self.addCleanup(f.doCleanups)
        self.source = f.root / "generated-collection"
        self.source.mkdir()
        (self.source / "empty").mkdir()
        (self.source / "nested").mkdir()
        (self.source / "nested" / "PRIVATE_CANARY.txt").write_bytes(b"Entirely invented test-only document")
        (self.source / "clip.mkv").write_bytes(f.source.read_bytes())
        self.bundle = SimpleNamespace(ffmpeg=f.backend.ffmpeg, ffprobe=f.backend.ffprobe, version="9.0.2")
        self.patch = patch("videomate.migration.load_bundle", return_value=self.bundle)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.messages = []
        self.addCleanup(self.clear_report)

    def clear_report(self):
        for message in self.messages:
            if message.startswith("Job: "):
                LIVE_REPORTS.pop(message[5:], None)

    def run_migration(self, **options):
        return migrate_local([str(self.source)], self.fixture.workspace, local_names=True, hardware_decoding=False,
                             cpu_threads=2, emit=self.messages.append, **options)

    def package(self):
        identifier = next(m[5:] for m in reversed(self.messages) if m.startswith("Job: "))
        return self.fixture.outputs / ("migration-" + identifier), identifier

    def test_verified_repair_publication_survives_restart_without_duplicate_encode(self):
        from videomate.recovery import RecoveryOptions, publish
        f = self.fixture
        f.make_damaged()
        (self.source / 'damaged.avi').write_bytes(f.damaged.read_bytes())
        options = RecoveryOptions(profile='compatible_sdr', hardware_encoding=False)
        def crash(candidate, destination):
            publish(candidate, destination)
            raise KeyboardInterrupt()
        with patch('videomate.recovery.publish', side_effect=crash):
            with self.assertRaises(KeyboardInterrupt):
                self.run_migration(private_resume=True, passphrase='generated restart passphrase', recovery=options)
        package, identifier = self.package()
        repaired = next(package.glob('*.mp4'))
        before = repaired.read_bytes(), repaired.stat().st_mtime_ns
        with patch('videomate.migration.RecoveryEngine.recover', side_effect=AssertionError('Must reuse verified repair')):
            self.assertEqual(self.run_migration(private_resume=True, checkpoint_id=identifier,
                passphrase='generated restart passphrase', recovery=options), 1)
        self.assertEqual((repaired.read_bytes(), repaired.stat().st_mtime_ns), before)
        self.assertEqual(len(list(package.glob('*.mp4'))), 1)

    def test_parallel_mixed_package_overlaps_workers_and_preserves_default_names(self):
        from videomate.migration import process_file
        for number in range(2):
            (self.source / f"generated-{number}.mkv").write_bytes(self.fixture.source.read_bytes())
        barrier = threading.Barrier(3, timeout=10)
        entered, lock = [], threading.Lock()
        def process(backend, item, **kwargs):
            with lock:
                entered.append((backend.scratch, backend.threads, item[3]))
                first = len(entered) <= 3
            if first:
                barrier.wait()
            return process_file(backend, item, **kwargs)
        with patch("videomate.migration.process_file", side_effect=process):
            self.assertEqual(migrate_local([str(self.source)], self.fixture.workspace, sensitive=False,
                cpu_threads=6, max_runners=3, hardware_decoding=False, emit=self.messages.append), 0)
        package, _ = self.package()
        status = json.loads(package.with_name(package.name + ".status.json").read_bytes())
        self.assertEqual(status["state"], "complete")
        self.assertEqual(status["counts"]["copied_healthy"], 3)
        self.assertTrue(any(not item[2] for item in entered[:3]))
        self.assertEqual(len({entry[0] for entry in entered[:3]}), 3)
        self.assertEqual(sum(entry[1] for entry in entered[:3]), 6)
        self.assertEqual(status["package_bytes"], sum(p.stat().st_size for p in package.rglob("*") if p.is_file()))
        for source in self.source.rglob("*"):
            if source.is_file():
                self.assertEqual(source.read_bytes(), (package / source.relative_to(self.source)).read_bytes())
        self.assertEqual(list((self.fixture.outputs / ".candidates").iterdir()), [])

    def test_opt_in_cpu_lane_runs_beside_both_qualified_gpu_routes(self):
        from videomate.inspection import _fingerprint
        from videomate.models import ScanResult
        from videomate.recovery import RecoveryOptions
        for number in range(2):
            (self.source / f"generated-{number}.mkv").write_bytes(self.fixture.source.read_bytes())
        devices = (("software", "h264_nvenc", 0), ("software", "h264_amf", None))
        for forced, budget in ((True, 8), (False, 30)):
            with self.subTest(forced=forced):
                barrier = threading.Barrier(3, timeout=10)
                observed, lock = [], threading.Lock()
                self.messages.clear()
                def process(backend, item, **_):
                    if item[3]:
                        with lock:
                            observed.append((backend.threads, backend.decoder, tuple(backend.hardware_routes)))
                        barrier.wait()
                    source_size = item[1].stat().st_size
                    return ScanResult(integrity="quick_check_only", fingerprint=_fingerprint(item[1]),
                        technical={"source_size": source_size, "migration": {
                            "input_kind": "video" if item[3] else "other", "action": "excluded_unresolved",
                            "copy_check": "not_run", "timestamps": "not_requested", "reason": "none"}})
                with patch("videomate.migration.select_decoder", return_value=("software",)), \
                     patch("videomate.migration.select_encoder", return_value=("h264_nvenc", "h264_amf")), \
                     patch("videomate.hardware.qualify_codec_routes", return_value=tuple((d, e) for d, e, _ in devices)), \
                     patch("videomate.hardware.qualify_devices", return_value=devices), \
                     patch("videomate.migration.cpu_budget", side_effect=lambda requested: requested or 30), \
                     patch("videomate.migration.process_file", side_effect=process):
                    self.assertEqual(migrate_local([str(self.source)], self.fixture.workspace,
                        sensitive=False, recovery=RecoveryOptions(profile="compatible_sdr"),
                        hardware_decoding=False, interruption_recovery=False,
                        cpu_threads=budget, max_runners=4, migration_cpu_encoding=forced,
                        emit=self.messages.append), 1)
                self.assertEqual(len(observed), 3)
                self.assertEqual(sum(entry[0] for entry in observed), budget - 1)  # The copy lane owns one thread.
                self.assertEqual(sum(not entry[2] and entry[1] == "software" for entry in observed), 1)
                self.assertEqual({route[0][1] for _, _, route in observed if route}, {"h264_nvenc", "h264_amf"})
                self.assertTrue(any("CPU encoding lane (" + ("forced" if forced else "automatic") + "): active" in message
                    for message in self.messages))

    def test_output_preflight_failure_stops_before_inspecting_source_bytes(self):
        with patch("videomate.migration.qualify_publication", side_effect=VideoMateError("output_access_denied")), \
                patch("videomate.migration.Inspector.inspect", side_effect=AssertionError("Must fail before inspection")):
            with self.assertRaises(VideoMateError) as error:
                self.run_migration()
        self.assertEqual(error.exception.code, "output_access_denied")
        self.assertEqual(list((self.fixture.outputs / ".candidates").iterdir()), [])

    def test_copy_failure_exports_fixed_reason_and_keeps_healthy_integrity(self):
        from videomate.local_scan import report_local
        from videomate.schema import load_json
        from videomate.support import support_summary
        with patch("videomate.migration.publish", side_effect=VideoMateError("output_access_denied")):
            self.assertEqual(self.run_migration(), 2)
        package, identifier = self.package()
        report_local(identifier, self.fixture.workspace, export=True, technical_json=True, emit=lambda _: None)
        report = next((self.fixture.workspace / "export-review").glob("diagnostics-*.json"))
        summary = support_summary(load_json(report.read_bytes()))
        self.assertEqual(summary["migration_reasons"], {"output_access_denied": 2})
        self.assertEqual(summary["integrity"]["no_errors_detected"], 1)
        self.assertEqual(summary["migration"], {"failed": 2})
        self.assertTrue(any("[output_access_denied]" in m for m in self.messages))
        self.assertEqual(list((self.fixture.outputs / ".candidates").iterdir()), [])

    def test_mixed_package_preserves_copies_repairs_collision_and_retains_unresolved(self):
        from videomate.local_scan import report_local
        from videomate.schema import validate_export
        f = self.fixture
        f.make_damaged()
        (self.source / "clip.avi").write_bytes(f.damaged.read_bytes())
        (self.source / "unreadable.mp4").write_bytes(b"Generated invalid media only")
        before = {p: p.read_bytes() for p in self.source.rglob("*") if p.is_file()}
        self.assertEqual(self.run_migration(unresolved="review"), 1)
        package, identifier = self.package()
        status = json.loads((package.with_name(package.name + ".status.json")).read_bytes())
        self.assertEqual(status["state"], "needs_review")
        self.assertEqual(status["counts"], {"copied_healthy": 1, "copied_other": 1, "repaired": 1, "salvaged_partial": 0, "retained_for_review": 1,
                                          "excluded_unresolved": 0, "copied_unresolved": 0, "failed": 0})
        self.assertTrue((package / "empty").is_dir())
        self.assertTrue((package / "clip.repaired-1.mkv").is_file())
        for source, original in before.items():
            self.assertEqual(source.read_bytes(), original)
        self.assertEqual((package / "clip.mkv").read_bytes(), before[self.source / "clip.mkv"])
        self.assertEqual((package / "nested" / "PRIVATE_CANARY.txt").read_bytes(), before[self.source / "nested" / "PRIVATE_CANARY.txt"])
        self.assertEqual((package.with_name(package.name + ".review") / "unreadable.mp4").read_bytes(), before[self.source / "unreadable.mp4"])
        self.assertEqual((package / "clip.mkv").stat().st_mtime_ns, (self.source / "clip.mkv").stat().st_mtime_ns)
        report_local(identifier, f.workspace, export=True, technical_json=True, emit=lambda _: None)
        reports = list((f.workspace / "export-review").glob("*.json"))
        self.assertEqual(len(reports), 1)
        encoded = reports[0].read_text()
        validate_export(json.loads(encoded))
        malformed = json.loads(encoded)
        malformed["files"][0]["migration"]["path"] = "PRIVATE_CANARY"
        with self.assertRaises(VideoMateError):
            validate_export(malformed)
        self.assertNotIn("PRIVATE_CANARY", encoded)
        self.assertNotIn(str(self.source), encoded)
        self.assertNotIn("clip.", encoded)
        self.assertEqual(list((f.workspace / "state").glob("mapping-*.json")), [])

    def test_unresolved_policies_report_omissions_and_preserve_direct_structure(self):
        from videomate.local_scan import report_local
        marker = b"Generated invalid media only"
        (self.source / "unreadable.mp4").write_bytes(marker)
        # These ordinary source names must remain usable without reserved wrappers.
        (self.source / "content").mkdir()
        (self.source / "content" / "package-status.json").write_bytes(b"Generated document")
        for policy in (None, "copy", "review"):
            with self.subTest(policy=policy or "default"):
                self.assertEqual(self.run_migration(**({} if policy is None else {"unresolved": policy})), 1)
                package, identifier = self.package()
                status = json.loads(package.with_name(package.name + ".status.json").read_bytes())
                self.assertEqual(status["state"], "needs_review")
                self.assertEqual(status["omitted_from_output"], 0 if policy == "copy" else 1)
                self.assertEqual(status["output_files"], 4 if policy == "copy" else 3)
                self.assertEqual(status["completed_files"], 4)
                self.assertTrue((package / "clip.mkv").is_file())
                self.assertEqual((package / "content" / "package-status.json").read_bytes(), b"Generated document")
                review = package.with_name(package.name + ".review")
                self.assertEqual(review.exists(), policy == "review")
                self.assertEqual((package / "unreadable.mp4").exists(), policy == "copy")
                action = {None: "excluded_unresolved", "copy": "copied_unresolved", "review": "retained_for_review"}[policy]
                self.assertEqual(status["counts"][action], 1)
                if policy:
                    self.assertEqual(((package if policy == "copy" else review) / "unreadable.mp4").read_bytes(), marker)
                self.assertEqual((self.source / "unreadable.mp4").read_bytes(), marker)
                report_local(identifier, self.fixture.workspace, export=True, technical_json=True, emit=lambda _: None)

    def test_preview_and_cancellation_never_claim_complete(self):
        self.assertEqual(self.run_migration(execute=False), 0)
        self.assertEqual(list(self.fixture.outputs.iterdir()), [])
        cancel = threading.Event()
        def emit(message):
            self.messages.append(message)
            if message.startswith("input-1:"):
                cancel.set()
        with self.assertRaises(KeyboardInterrupt):
            migrate_local([str(self.source)], self.fixture.workspace, local_names=True, hardware_decoding=False,
                          emit=emit, cancel_event=cancel, max_runners=1)
        package, _ = self.package()
        status = json.loads((package.with_name(package.name + ".status.json")).read_bytes())
        self.assertEqual(status["state"], "interrupted")
        self.assertEqual(status["omitted_from_output"], 1)
        self.assertTrue((self.source / "clip.mkv").exists())

    def test_stopped_direct_migration_continues_in_session_without_overwriting(self):
        from videomate.migration_resume import SESSION_RETRIES
        destination = self.fixture.root / 'generated-direct-output'
        cancel = threading.Event()
        def stop_after_first(message):
            self.messages.append(message)
            if message.startswith('input-1:'):
                cancel.set()
        settings = dict(local_names=True, recovered_dir=str(destination), package_layout='direct',
                        hardware_decoding=False, cpu_threads=1, max_runners=1, interruption_recovery=True)
        with self.assertRaises(KeyboardInterrupt):
            migrate_local([str(self.source)], self.fixture.workspace, cancel_event=cancel,
                emit=stop_after_first, **settings)
        identifier = next(message[5:] for message in self.messages if message.startswith('Job: '))
        snapshot = SESSION_RETRIES[identifier]
        self.assertEqual(snapshot['mode'], 'continue')
        self.assertNotIn(str(self.source).encode(), snapshot['database'])
        published = {path.relative_to(destination): (path.read_bytes(), path.stat().st_mtime_ns)
                     for path in destination.rglob('*') if path.is_file()}
        self.assertTrue(published)
        with self.assertRaises(VideoMateError) as error:
            migrate_local([str(self.source)], self.fixture.workspace, emit=lambda _: None, **settings)
        self.assertEqual(error.exception.code, 'migration_output_not_empty')
        with self.assertRaises(VideoMateError) as error:
            migrate_local([str(self.source)], self.fixture.workspace, retry_id=identifier,
                recovery=RecoveryOptions(force=True),
                emit=lambda _: None, **settings)
        self.assertEqual(error.exception.code, 'checkpoint_policy_changed')
        relative, before = next(iter(published.items()))
        changed = destination / relative
        changed.write_bytes(b'Generated conflicting output')
        with self.assertRaises(VideoMateError) as error:
            migrate_local([str(self.source)], self.fixture.workspace, retry_id=identifier,
                emit=lambda _: None, **settings)
        self.assertEqual(error.exception.code, 'resume_output_conflict')
        changed.write_bytes(before[0])
        os.utime(changed, ns=(before[1], before[1]))
        self.assertEqual(migrate_local([str(self.source)], self.fixture.workspace,
            retry_id=identifier, emit=self.messages.append, **settings), 0)
        self.assertNotIn(identifier, SESSION_RETRIES)
        for relative, before in published.items():
            output = destination / relative
            self.assertEqual((output.read_bytes(), output.stat().st_mtime_ns), before)
        status = json.loads(destination.with_name(destination.name + '.status.json').read_bytes())
        self.assertEqual((status['state'], status['completed_files']), ('complete', status['planned_files']))

    def test_stopped_private_direct_migration_requires_checkpoint_and_resumes(self):
        from videomate.migration_resume import SESSION_RETRIES
        destination = self.fixture.root / 'generated-private-output'
        cancel = threading.Event()
        def stop_after_first(message):
            self.messages.append(message)
            if message.startswith('input-1:'):
                cancel.set()
        settings = dict(local_names=True, recovered_dir=str(destination), package_layout='direct',
                        hardware_decoding=False, cpu_threads=1, max_runners=1, interruption_recovery=True,
                        private_resume=True, passphrase='generated restart passphrase')
        with self.assertRaises(KeyboardInterrupt):
            migrate_local([str(self.source)], self.fixture.workspace, cancel_event=cancel,
                emit=stop_after_first, **settings)
        identifier = next(message[5:] for message in self.messages if message.startswith('Job: '))
        checkpoint = self.fixture.workspace / 'state' / ('migration-' + identifier + '.sqlite3')
        self.assertTrue(checkpoint.is_file())
        self.assertNotIn(identifier, SESSION_RETRIES)
        published = {path.relative_to(destination): (path.read_bytes(), path.stat().st_mtime_ns)
                     for path in destination.rglob('*') if path.is_file()}
        self.assertTrue(published)
        self.assertEqual(migrate_local([str(self.source)], self.fixture.workspace,
            checkpoint_id=identifier, emit=self.messages.append, **settings), 0)
        self.assertFalse(checkpoint.exists())
        for relative, before in published.items():
            output = destination / relative
            self.assertEqual((output.read_bytes(), output.stat().st_mtime_ns), before)

    def test_source_tree_change_marks_package_incomplete(self):
        real_copy = verified_copy
        def changed(*args, **kwargs):
            result = real_copy(*args, **kwargs)
            (self.source / "new-during-run.txt").write_bytes(b"Generated concurrent source addition")
            return result
        with patch("videomate.migration.verified_copy", side_effect=changed):
            self.assertEqual(self.run_migration(), 2)
        package, _ = self.package()
        self.assertEqual(json.loads((package.with_name(package.name + ".status.json")).read_bytes())["state"], "incomplete")

    def test_complete_package_and_optional_mp4_conversion_of_healthy_video(self):
        from videomate.recovery import RecoveryOptions
        for convert in (False, True):
            with self.subTest(convert_all_mp4=convert):
                code = self.run_migration(recovery=RecoveryOptions(convert_all_mp4=convert, hardware_encoding=False))
                self.assertEqual(code, 1 if convert else 0)
                package, _ = self.package()
                status = json.loads((package.with_name(package.name + ".status.json")).read_bytes())
                self.assertEqual(status["state"], "complete")
                self.assertTrue((package / ("clip.mp4" if convert else "clip.mkv")).is_file())
                self.assertEqual(status["counts"]["repaired" if convert else "copied_healthy"], 1)

    def test_direct_destination_is_collection_root_and_rejects_fresh_reuse(self):
        destination = self.fixture.root / "generated-empty-destination"
        self.assertEqual(self.run_migration(recovered_dir=str(destination), package_layout="direct"), 0)
        self.assertTrue((destination / "clip.mkv").is_file())
        self.assertTrue((destination / "nested" / "PRIVATE_CANARY.txt").is_file())
        self.assertFalse(any(p.name.startswith("migration-") for p in destination.iterdir()))
        self.assertTrue(destination.with_name(destination.name + ".status.json").is_file())
        self.assertTrue(destination.with_name(destination.name + ".owner").is_file())
        with self.assertRaises(VideoMateError) as error:
            self.run_migration(recovered_dir=str(destination), package_layout="direct")
        self.assertEqual(error.exception.code, "migration_output_not_empty")
        unrelated = self.fixture.root / 'generated-empty-with-review-sidecar'
        unrelated.mkdir()
        unrelated.with_name(unrelated.name + '.review').mkdir()
        with self.assertRaises(VideoMateError) as error:
            self.run_migration(recovered_dir=str(unrelated), package_layout='direct')
        self.assertEqual(error.exception.code, 'migration_output_not_empty')

    def test_direct_migration_marks_verified_partial_for_review(self):
        from videomate.recovery import RecoveryOptions
        source = self.source / 'clip.mkv'
        data = source.read_bytes()
        source.write_bytes(data[:len(data) * 2 // 3])
        destination = self.fixture.root / 'generated-partial-destination'
        code = self.run_migration(recovered_dir=str(destination), package_layout='direct',
                                  recovery=RecoveryOptions(strategy='reencode', partial_salvage=True))
        self.assertEqual(code, 1)
        status = json.loads(destination.with_name(destination.name + '.status.json').read_bytes())
        self.assertEqual(status['state'], 'needs_review')
        self.assertEqual(status['counts']['salvaged_partial'], 1)
        self.assertTrue((destination / 'clip.mkv').is_file())
        self.assertEqual(source.read_bytes(), data[:len(data) * 2 // 3])

    def test_selective_hevc_preset_copies_compliant_mp4_and_converts_other_video(self):
        from videomate.recovery import RecoveryOptions
        from videomate.inspection import Inspector
        from videomate.backend import FFmpegBackend
        from videomate.runner import Runner
        from videomate.policy import SyntheticScope
        compliant = self.source / "generated-compliant.mp4"
        generated = self.fixture.backend.runner.run([str(self.fixture.backend.ffmpeg), "-nostdin", "-v", "error", "-n",
            "-f", "lavfi", "-i", "testsrc2=size=160x120:rate=25", "-t", "1", "-c:v", "libx264",
            "-threads", "1", "-pix_fmt", "yuv420p", str(compliant)], self.fixture.root)
        self.assertEqual(generated.returncode, 0)
        before = compliant.read_bytes()
        mov = self.source / "generated-mov.mov"
        moved = self.fixture.backend.runner.run([str(self.fixture.backend.ffmpeg), "-nostdin", "-v", "error", "-n",
            "-i", str(compliant), "-c", "copy", str(mov)], self.fixture.root)
        self.assertEqual(moved.returncode, 0)
        options = RecoveryOptions(convert_noncompliant_hevc=True, hardware_encoding=False)
        self.assertEqual(self.run_migration(recovery=options), 1)
        package, _ = self.package()
        self.assertEqual((package / compliant.name).read_bytes(), before)
        converted = package / "clip.mp4"
        self.assertTrue(converted.is_file())
        self.assertTrue((package / "generated-mov.mp4").is_file())
        scope = SyntheticScope(frozenset({converted}))
        backend = FFmpegBackend(self.fixture.backend.ffmpeg, self.fixture.backend.ffprobe,
                                self.fixture.root, Runner(timeout=30), scope=scope)
        media = Inspector(backend, scope).inspect(converted)
        self.assertEqual(media.streams[0]["codec"], "hevc")
        self.assertEqual((media.streams[0]["width"], media.streams[0]["height"]), (160, 120))
        status = json.loads(package.with_name(package.name + ".status.json").read_bytes())
        self.assertEqual(status["counts"]["copied_healthy"], 1)
        self.assertEqual(status["counts"]["repaired"], 2)
