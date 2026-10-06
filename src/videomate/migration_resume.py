"""Path-free migration journal and bounded reconnect retries. No raw logs."""
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import threading
from collections import OrderedDict
from pathlib import Path
from uuid import UUID, uuid4

from . import __version__

from .checkpoint import canonical, HEX32
from .diagnostics import create_export, environment
from .errors import VideoMateError
from .execution import parallel_inspect
from .inspection import _fingerprint
from .policy import plain_local_path
from .private_state import from_report
from .schema import MAX_EXPORT_BYTES, load_json, validate_export

TRANSIENT = {'io_error', 'source_read_failed', 'output_write_failed', 'output_publish_failed',
             'copy_verification_failed', 'output_busy', 'disk_limit', 'backend_unavailable'}

# Memory only: authenticated reports/content tokens, never source locators.
SESSION_RETRIES = OrderedDict()


def clear_session_retries():
    SESSION_RETRIES.clear()


def file_hash(path, cancel):
    before = _fingerprint(plain_local_path(path))
    value = hashlib.sha256()
    with path.open('rb') as source:
        while block := source.read(1024 * 1024):
            if cancel.is_set():
                raise KeyboardInterrupt()
            value.update(block)
    if before != _fingerprint(plain_local_path(path)):
        raise VideoMateError('input_changed')
    return value.digest()


class RoundCancel:
    """An interrupted round never clears the operator's Stop request."""
    def __init__(self, parent):
        self.parent, self.local = parent, threading.Event()

    def is_set(self):
        return self.parent.is_set() or self.local.is_set()

    def set(self):
        self.local.set()


class MigrationJournal:
    def __init__(self, workspace, files, directories, source, output, policy, cancel, *,
                 persistent=False, passphrase=None, identifier=None, version='0.0.0', retry_state=None,
                 package_layout='versioned'):
        if retry_state:
            identifier = retry_state['id']
            if persistent or retry_state['version'] != version or retry_state['sensitive'] != policy['sensitive']:
                raise VideoMateError('checkpoint_policy_changed')
        self.id = identifier or uuid4().hex
        if not isinstance(self.id, str) or not HEX32.fullmatch(self.id):
            raise VideoMateError('checkpoint_invalid')
        if identifier and not persistent and not retry_state:
            raise VideoMateError('checkpoint_invalid')
        if persistent and (type(passphrase) is not str or not 12 <= len(passphrase) <= 1024):
            raise VideoMateError('passphrase_required')
        self.cancel, self.version, self.persistent = cancel, version, persistent
        self.lock = threading.RLock()
        self.source, self.output = source, output
        if package_layout not in {'direct', 'versioned'}:
            raise VideoMateError('invalid_arguments')
        legacy = output / ('migration-' + self.id)
        # Old checkpoints keep their original package. New direct packages use
        # an adjacent ownership marker; neither layout adopts an unknown one.
        if identifier:
            self.package = legacy if legacy.with_name(legacy.name + '.owner').is_file() else output
        else:
            self.package = output if package_layout == 'direct' else legacy
        self.path = plain_local_path(workspace / 'state' / ('migration-' + self.id + '.sqlite3')) if persistent else None
        if self.path:
            if identifier and not self.path.is_file():
                raise VideoMateError('checkpoint_invalid')
            if not identifier:
                descriptor = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                os.close(descriptor)
        self.db = sqlite3.connect(str(self.path) if self.path else ':memory:', check_same_thread=False)
        try:
            if retry_state:
                self.db.deserialize(retry_state['database'])
            self.db.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, MAX_EXPORT_BYTES + 1024)
            self.db.execute('PRAGMA trusted_schema=OFF')
            self.db.execute('PRAGMA temp_store=MEMORY')
            self.db.execute('PRAGMA synchronous=FULL')
            if not identifier:
                self.db.executescript('CREATE TABLE metadata (data BLOB, mac TEXT); CREATE TABLE results (token TEXT PRIMARY KEY, data BLOB NOT NULL, mac TEXT NOT NULL);')
                salt = secrets.token_hex(16)
            else:
                row = self.db.execute('SELECT data,mac FROM metadata').fetchall()
                if len(row) != 1:
                    raise VideoMateError('checkpoint_invalid')
                saved = load_json(row[0][0])
                salt = saved.get('salt')
                if not isinstance(salt, str) or not HEX32.fullmatch(salt):
                    raise VideoMateError('checkpoint_invalid')
            self.key = retry_state['key'] if retry_state else hashlib.pbkdf2_hmac('sha256', passphrase.encode(), bytes.fromhex(salt), 600000) if persistent else secrets.token_bytes(32)
            self.identity = (_fingerprint(self.path)[:2] if self.path else None)
            self.tokens = {i: self.tag('name', relative.as_posix().encode('utf-8')) for i, (_, relative, _) in enumerate(files, 1)}
            # Linear manifest construction; no names, raw hashes or stat tuples are persisted.
            manifest = hashlib.sha256()
            for i, (path, _, _) in enumerate(files, 1):
                if cancel.is_set():
                    raise KeyboardInterrupt()
                manifest.update(self.tokens[i].encode())
                manifest.update(self.tag('stat', canonical(_fingerprint(path))).encode())
            for relative in directories:
                manifest.update(self.tag('directory', relative.as_posix().encode('utf-8')).encode())
            meta = {'version': 1, 'id': self.id, 'salt': salt, 'manifest': self.tag('manifest', manifest.digest()),
                    'policy': self.tag('policy', canonical({'application': __version__, **policy})), 'source': self.root_tag(source), 'output': self.root_tag(output)}
            self.active_policy_tag = meta['policy']
            if identifier:
                if not hmac.compare_digest(row[0][1], self.tag('metadata', row[0][0])):
                    raise VideoMateError('checkpoint_invalid')
                if retry_state and retry_state.get('mode') == 'continue' and not hmac.compare_digest(
                        retry_state.get('active_policy', ''), self.active_policy_tag):
                    raise VideoMateError('checkpoint_policy_changed')
                expected = {**meta, 'policy': saved['policy']} if retry_state else meta
                if saved != expected:
                    # Strict was the behavior before size_policy became explicit.
                    # Accept that exact historical default, never a policy relaxation.
                    recovery_policy = policy.get('recovery', {})
                    legacy = {**policy, 'recovery': {k: v for k, v in recovery_policy.items() if k != 'size_policy'}}
                    legacy_tag = self.tag('policy', canonical({'application': __version__, **legacy}))
                    if retry_state or recovery_policy.get('size_policy') != 'strict' or saved != {**meta, 'policy': legacy_tag}:
                        raise VideoMateError('checkpoint_policy_changed' if saved.get('policy') != expected['policy']
                                             else 'checkpoint_sources_changed')
                if retry_state and retry_state['workspace'] != self.root_tag(workspace):
                    raise VideoMateError('checkpoint_sources_changed')
            else:
                blob = canonical(meta)
                with self.db:
                    self.db.execute('INSERT INTO metadata VALUES (?,?)', (blob, self.tag('metadata', blob)))
            self.source_tag = meta['source']
            self.output_tag = meta['output']
            self.marker = self.package.with_name(self.package.name + '.owner')
            self.marker_bytes = self.tag('package', self.id.encode()).encode()
            self.resuming = bool(identifier)
        except BaseException as error:
            self.db.close()
            if isinstance(error, sqlite3.Error):
                raise VideoMateError('checkpoint_invalid') from None
            raise

    def tag(self, domain, value):
        return hmac.digest(self.key, domain.encode() + b'\0' + value, 'sha256').hex()

    def root_tag(self, path):
        info = plain_local_path(path).stat()
        return self.tag('storage-root', canonical([info.st_dev, info.st_ino]))

    def initialize_package(self):
        if self.resuming:
            self.check_storage()
        else:
            if self.package == self.output and (any(self.package.iterdir()) or self.marker.exists()
                                                    or self.package.with_name(self.package.name + '.status.json').exists()
                                                    or self.package.with_name(self.package.name + '.review').exists()):
                raise VideoMateError('migration_output_not_empty')
            self.package.mkdir(mode=0o700, exist_ok=self.package == self.output)
            with self.marker.open('xb') as stream:
                stream.write(self.marker_bytes)
                stream.flush()
                os.fsync(stream.fileno())

    def check_storage(self):
        if self.root_tag(self.source) != self.source_tag or self.root_tag(self.output) != self.output_tag:
            raise VideoMateError('resume_storage_changed')
        try:
            with plain_local_path(self.marker).open('rb') as stream:
                if not hmac.compare_digest(stream.read(65), self.marker_bytes):
                    raise VideoMateError('resume_storage_changed')
        except FileNotFoundError:
            raise VideoMateError('resume_storage_changed') from None

    def wait_storage(self, emit, tracker):
        delay = 1
        interrupted = False
        while True:
            if self.cancel.is_set():
                raise KeyboardInterrupt()
            try:
                self.check_storage()
                return interrupted
            except OSError:
                interrupted = True
                tracker.update('waiting_storage', active=0, force=True)
                emit('Storage unavailable. Waiting for the selected source and output to return; Stop remains available.')
                if self.cancel.wait(delay):
                    raise KeyboardInterrupt()
                delay = min(30, delay * 2)

    def storage_operation(self, operation, emit, tracker):
        """Only call outside active worker rounds."""
        for attempt in range(4):
            try:
                return operation()
            except (OSError, VideoMateError) as error:
                if isinstance(error, VideoMateError) and error.code not in {'migration_access', 'migration_not_folder'}:
                    raise
                if attempt == 3:
                    raise
                self.wait_storage(emit, tracker)
                if hasattr(self, 'revalidate_outputs'):
                    self.revalidate_outputs()
                emit(f'Storage operation retry {attempt + 1}/3 [io_error].')
                if self.cancel.wait(2 ** attempt):
                    raise KeyboardInterrupt()

    def target(self, item, kind):
        _, _, relative, _, stem = item
        if kind == 'copy':
            return self.package / relative
        if kind == 'review':
            return self.package.with_name(self.package.name + '.review') / relative
        if kind in {'repair_mp4', 'repair_mkv'}:
            return self.package / relative.parent / (stem + ('.mp4' if kind == 'repair_mp4' else '.mkv'))
        raise VideoMateError('checkpoint_invalid')

    def stage(self, item, result, destination, source_digest, output_digest):
        """Durable intent precedes publication. A crash after publication is recoverable."""
        migration = result.technical['migration']
        kind = 'review' if migration['action'] == 'retained_for_review' else 'repair_' + destination.suffix[1:] if migration['action'] in {'repaired', 'salvaged_partial'} else 'copy'
        if plain_local_path(destination) != plain_local_path(self.target(item, kind)):
            raise VideoMateError('output_exists')
        if destination.exists():
            raise VideoMateError('resume_output_conflict')
        report = load_json(create_export([result], UUID(hex=self.id), self.key, environment(self.version, self.version)))
        payload = {'kind': kind, 'source': self.tag('content', source_digest), 'output': self.tag('content', output_digest), 'report': report}
        token = self.tokens[item[0]]
        blob = canonical(payload)
        with self.lock, self.db:
            self.db.execute('INSERT OR REPLACE INTO results VALUES (?,?,?)', (token, blob, self.tag('result:' + token, blob)))

    def restore(self, item):
        token = self.tokens[item[0]]
        with self.lock:
            row = self.db.execute('SELECT data,mac FROM results WHERE token=?', (token,)).fetchone()
        if not row:
            return None
        if not hmac.compare_digest(row[1], self.tag('result:' + token, row[0])):
            raise VideoMateError('checkpoint_invalid')
        payload = load_json(row[0])
        if set(payload) != {'kind', 'source', 'output', 'report'}:
            raise VideoMateError('checkpoint_invalid')
        validate_export(payload['report'])
        target = plain_local_path(self.target(item, payload['kind']))
        if not target.exists():
            return None
        if self.tag('content', file_hash(item[1], self.cancel)) != payload['source']:
            raise VideoMateError('checkpoint_sources_changed')
        if self.tag('content', file_hash(target, self.cancel)) != payload['output']:
            raise VideoMateError('resume_output_conflict')
        result = from_report(payload['report'])
        result.fingerprint = _fingerprint(item[1])
        result.technical['migration'] = payload['report']['files'][0]['migration']
        result.technical['source_size'] = result.fingerprint[2]
        size_key = 'private_review_bytes' if payload['kind'] == 'review' else 'private_package_bytes'
        result.technical[size_key] = target.stat().st_size
        if result.recovery:
            result.recovery.update(private_output=str(target), private_output_bytes=target.stat().st_size)
        return result

    def revalidate_published(self, items):
        """After workers stop, reject missing or changed publications before reuse."""
        for item in items:
            with self.lock:
                exists = self.db.execute('SELECT 1 FROM results WHERE token=?', (self.tokens[item[0]],)).fetchone()
            if exists and self.restore(item) is None:
                raise VideoMateError('resume_output_conflict')

    def retry_snapshot(self, workspace, sensitive, published, unresolved, policy, *, mode='retry'):
        if mode not in {'retry', 'continue'}:
            raise VideoMateError('checkpoint_invalid')
        return {'id': self.id, 'database': self.db.serialize(), 'key': self.key, 'version': self.version,
                'workspace': self.root_tag(workspace), 'sensitive': sensitive,
                'published': tuple(published), 'unresolved': unresolved, 'policy': policy,
                'mode': mode, 'active_policy': self.active_policy_tag}

    def close(self, *, complete=False):
        self.db.close()
        if complete and self.path:
            if _fingerprint(plain_local_path(self.path))[:2] != self.identity:
                raise VideoMateError('checkpoint_invalid')
            self.path.unlink()


def sweep_staging(job, staging, emit):
    """Only the current session's exclusive, flat, neutral candidate directory."""
    if job.cleanup_blocked.is_set():
        raise VideoMateError('worker_cleanup_failed')
    info = plain_local_path(staging).stat()
    if job.owned_identities.get(staging) != (info.st_dev, info.st_ino):
        raise VideoMateError('cleanup_incomplete')
    removed, retained = 0, 0
    for path in staging.iterdir():
        try:
            if not re.fullmatch(r'[a-f0-9]{32}\.(part|mp4|mkv)', path.name) or not plain_local_path(path).is_file():
                retained += 1
                continue
            path.unlink()
            removed += 1
        except (OSError, VideoMateError):
            retained += 1
    emit(f'Owned staging sweep: {removed} stopped-worker candidates removed; {retained} unrecognized/unavailable entries retained.')
    if retained:
        job.retained_directories.add(staging)


def retry_queue(items, workers, process, started, cancel, journal, rediscover, emit, tracker, *, retries=3, on_retry=None, copy_lane=False, sweep=None):
    """Drain a failed round before rediscovery, cleanup or a replacement worker."""
    pending = {item[0]: item for item in items}
    attempts = {}
    history = {}
    round_cancel = RoundCancel(cancel)
    for backend in workers:
        backend.runner.cancel_event = round_cancel
    while pending:
        round_cancel.local.clear()
        retry_needed = False
        from itertools import chain
        round_items = list(pending.values())
        queues = None
        if copy_lane:
            videos = iter(item for item in round_items if item[3])
            others = iter(item for item in round_items if not item[3])
            queues = [videos] * (len(workers) - 1) + [chain(others, videos)]
        iterator = parallel_inspect(round_items, workers, process, started, round_cancel, queues=queues, drain_on_cancel=True)
        try:
            for item, result in iterator:
                reason = result.technical['migration']['reason']
                timed_out = any(d['limit_reason'] == 'timeout' for d in result.diagnostics)
                io_evidence = any(f.category == 'io_error' for f in result.findings) or any(
                    d['error_code'] in TRANSIENT or any(m['category'] == 'io_error' for m in d['messages'])
                    for d in result.diagnostics)
                retryable = result.technical['migration']['action'] in {'failed', 'excluded_unresolved'}
                if retryable and (reason in TRANSIENT or timed_out or io_evidence) and attempts.get(item[0], 0) < retries:
                    attempts[item[0]] = attempts.get(item[0], 0) + 1
                    emit(f"input-{item[0]}: temporary failure [{reason}]; retry {attempts[item[0]]}/{retries} queued after workers stop.")
                    retry_needed = True
                    previous, omitted = history.get(item[0], ([], 0))
                    combined = previous + result.diagnostics
                    history[item[0]] = (combined[:1024], omitted + result.diagnostics_omitted + max(0, len(combined) - 1024))
                    if on_retry:
                        on_retry(result, item[0])
                    round_cancel.set()
                else:
                    pending.pop(item[0])
                    if item[0] in history:
                        previous, omitted = history.pop(item[0])
                        combined = previous + result.diagnostics
                        result.diagnostics = combined[:1024]
                        result.diagnostics_omitted += omitted + max(0, len(combined) - 1024)
                    yield item, result
        except KeyboardInterrupt:
            if cancel.is_set() or not retry_needed:
                raise
        finally:
            iterator.close()
        if cancel.is_set():
            raise KeyboardInterrupt()
        if retry_needed:
            if any(w.runner.cleanup_blocked.is_set() for w in workers):
                raise VideoMateError('worker_cleanup_failed')
            journal.wait_storage(emit, tracker)
            if sweep:
                sweep()
            rediscover()
            tracker.update('retrying', active=0, force=True)
            # Backoff is interruptible and no worker holds a resource slot here.
            if cancel.wait(min(8, 2 ** (max(attempts.values()) - 1))):
                raise KeyboardInterrupt()
            emit(f'Rediscovery complete; retrying {len(pending)} unfinished inputs. Verified outputs are checked before reuse.')
