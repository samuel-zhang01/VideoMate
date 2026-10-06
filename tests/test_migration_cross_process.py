"""Private migration restart checks using only newly generated local fixtures."""

import hashlib
import multiprocessing
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


def _migration_process(source, workspace, output, dependency_root, passphrase, checkpoint_id,
                       stop_after_publish, result_queue):
    """Run in a spawned interpreter so no in-memory job state crosses the restart."""
    from videomate import migration
    from videomate.recovery import RecoveryOptions

    messages = []
    if stop_after_publish:
        original_publish = migration.publish

        def interrupt_after_publication(candidate, destination):
            original_publish(candidate, destination)
            raise KeyboardInterrupt()

        migration.publish = interrupt_after_publication
    try:
        code = migration.migrate_local(
            [source], workspace, dependencies=Path(dependency_root),
            recovered_dir=output, package_layout='direct', sensitive=True, local_names=True,
            private_resume=True, checkpoint_id=checkpoint_id, passphrase=passphrase,
            recovery=RecoveryOptions(profile='compatible_sdr', hardware_encoding=False),
            hardware_decoding=False, migration_cpu_auto=False, cpu_threads=2, max_runners=1,
            emit=messages.append)
        state = 'finished'
    except KeyboardInterrupt:
        code, state = None, 'stopped'
    except BaseException as error:
        code, state = getattr(error, 'code', type(error).__name__), 'error'
    identifier = next((message[5:] for message in messages if message.startswith('Job: ')), None)
    result_queue.put({
        'state': state, 'code': code, 'identifier': identifier,
        'source_leaked': any('SYNTHETIC_PRIVATE_CANARY' in message or source in message
                             for message in messages),
    })


@unittest.skipUnless(os.environ.get('VIDEOMATE_TEST_FFMPEG') and os.environ.get('VIDEOMATE_TEST_FFPROBE'),
                     'Explicit synthetic-test FFmpeg/FFprobe binaries not configured')
class CrossProcessMigrationTests(unittest.TestCase):
    def setUp(self):
        from videomate.setup_local import ensure_workspace

        self.temp = tempfile.TemporaryDirectory(prefix='videomate-cross-process-generated-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.source = self.root / 'SYNTHETIC_PRIVATE_CANARY'
        self.source.mkdir()
        self.workspace = ensure_workspace(self.root / 'workspace')
        self.output = self.root / 'output'
        self.passphrase = 'generated-only-test-passphrase'
        ffmpeg = Path(os.environ['VIDEOMATE_TEST_FFMPEG']).resolve()
        if not (ffmpeg.parent.parent / 'manifest.json').is_file():
            self.skipTest('Cross-process migration needs a verified local FFmpeg bundle')
        self.dependency_root = ffmpeg.parents[2]
        self.note = self.source / '00-note.txt'
        self.note.write_bytes(b'Generated cross-process marker')

    def run_fresh_process(self, *, checkpoint_id=None, stop_after_publish=False):
        context = multiprocessing.get_context('spawn')
        result_queue = context.Queue()
        process = context.Process(target=_migration_process, args=(
            str(self.source), str(self.workspace), str(self.output), str(self.dependency_root),
            self.passphrase, checkpoint_id, stop_after_publish, result_queue))
        process.start()
        process.join(timeout=120)
        if process.is_alive():
            process.terminate()
            process.join(timeout=10)
            self.fail('Generated migration did not finish within 120 seconds')
        self.assertEqual(process.exitcode, 0, 'Generated migration worker exited unexpectedly')
        return result_queue.get(timeout=5)

    def test_restart_after_publication_reuses_verified_output(self):
        video = self.source / '01-video.mp4'
        generation = subprocess.run([
            os.environ['VIDEOMATE_TEST_FFMPEG'], '-nostdin', '-hide_banner', '-v', 'error',
            '-f', 'lavfi', '-i', 'testsrc2=size=96x64:rate=12', '-t', '1',
            '-c:v', 'mpeg4', str(video)], capture_output=True, timeout=30)
        self.assertEqual(generation.returncode, 0, 'Generated video creation failed')
        original_hashes = {item.name: hashlib.sha256(item.read_bytes()).digest()
                           for item in (self.note, video)}

        stopped = self.run_fresh_process(stop_after_publish=True)
        self.assertEqual(stopped['state'], 'stopped')
        self.assertFalse(stopped['source_leaked'])
        identifier = stopped['identifier']
        self.assertIsNotNone(identifier)
        checkpoint = self.workspace / 'state' / f'migration-{identifier}.sqlite3'
        self.assertTrue(checkpoint.is_file())
        self.assertNotIn(b'SYNTHETIC_PRIVATE_CANARY', checkpoint.read_bytes())
        first_output = self.output / self.note.name
        self.assertTrue(first_output.is_file())
        published_before = (hashlib.sha256(first_output.read_bytes()).digest(), first_output.stat().st_mtime_ns)

        resumed = self.run_fresh_process(checkpoint_id=identifier)
        self.assertEqual((resumed['state'], resumed['code']), ('finished', 0))
        self.assertFalse(resumed['source_leaked'])
        self.assertFalse(checkpoint.exists())
        self.assertEqual((hashlib.sha256(first_output.read_bytes()).digest(), first_output.stat().st_mtime_ns),
                         published_before)
        copied_video = self.output / video.name
        self.assertTrue(copied_video.is_file())
        self.assertEqual(hashlib.sha256(copied_video.read_bytes()).digest(), original_hashes[video.name])
        for item in (self.note, video):
            self.assertEqual(hashlib.sha256(item.read_bytes()).digest(), original_hashes[item.name])

    def test_restart_of_completed_package_keeps_unresolved_file_excluded(self):
        broken = self.source / '01-unreadable.mp4'
        broken.write_bytes(b'Generated invalid media, not an actual MP4')
        original_hashes = {item.name: hashlib.sha256(item.read_bytes()).digest()
                           for item in (self.note, broken)}

        first = self.run_fresh_process()
        self.assertEqual((first['state'], first['code']), ('finished', 1))
        self.assertFalse(first['source_leaked'])
        identifier = first['identifier']
        self.assertIsNotNone(identifier)
        checkpoint = self.workspace / 'state' / f'migration-{identifier}.sqlite3'
        self.assertTrue(checkpoint.is_file())
        published_note = self.output / self.note.name
        self.assertTrue(published_note.is_file())
        published_before = (hashlib.sha256(published_note.read_bytes()).digest(), published_note.stat().st_mtime_ns)
        self.assertFalse((self.output / broken.name).exists())

        resumed = self.run_fresh_process(checkpoint_id=identifier)
        self.assertEqual((resumed['state'], resumed['code']), ('finished', 1))
        self.assertFalse(resumed['source_leaked'])
        self.assertTrue(checkpoint.is_file())
        self.assertFalse((self.output / broken.name).exists())
        self.assertEqual((hashlib.sha256(published_note.read_bytes()).digest(), published_note.stat().st_mtime_ns),
                         published_before)
        for item in (self.note, broken):
            self.assertEqual(hashlib.sha256(item.read_bytes()).digest(), original_hashes[item.name])
