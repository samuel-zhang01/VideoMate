"""Passphrase-authenticated, path-free resume checkpoints. Not encryption."""
import hashlib
import hmac
import json
import os
import re
import secrets
from collections import Counter
from pathlib import Path
from uuid import UUID, uuid4

from . import __version__
from .diagnostics import create_export, environment
from .errors import VideoMateError
from .inspection import _fingerprint
from .policy import plain_local_path
from .private_state import from_report
from .schema import MAX_EXPORT_BYTES, load_json, validate_export

HEX32 = re.compile(r"[a-f0-9]{32}\Z")
HEX64 = re.compile(r"[a-f0-9]{64}\Z")


def canonical(value):
    return json.dumps(value, ensure_ascii=True, allow_nan=False, separators=(",", ":"), sort_keys=True).encode("ascii")


class Checkpoint:
    def __init__(self, workspace, passphrase, policy, *, identifier=None):
        if type(passphrase) is not str or not 12 <= len(passphrase) <= 1024:
            raise VideoMateError("passphrase_required")
        self.id = identifier or uuid4().hex
        if not HEX32.fullmatch(self.id):
            raise VideoMateError("checkpoint_invalid")
        self.path = plain_local_path(workspace / "state" / ("checkpoint-" + self.id + ".json"))
        self.resuming = identifier is not None
        self.tokens, self.fingerprints = {}, {}
        if self.resuming:
            try:
                with self.path.open("rb") as stream:
                    envelope = load_json(stream.read(MAX_EXPORT_BYTES + 1))
                if set(envelope) != {"payload", "mac"} or type(envelope["payload"]) is not dict:
                    raise ValueError()
                payload = envelope["payload"]
                if (set(payload) != {"version", "id", "salt", "policy", "sources", "entries"}
                        or payload["version"] != 1 or payload["id"] != self.id or not HEX32.fullmatch(payload["salt"])):
                    raise ValueError()
                self.key = hashlib.pbkdf2_hmac("sha256", passphrase.encode("utf-8"), bytes.fromhex(payload["salt"]), 600000)
                if not hmac.compare_digest(self.tag(b"checkpoint", canonical(payload)), envelope["mac"]):
                    raise ValueError()
                self.payload = payload
                self._validate()
            except (OSError, ValueError, TypeError, KeyError, VideoMateError):
                raise VideoMateError("checkpoint_invalid") from None
        else:
            salt = secrets.token_hex(16)
            self.key = hashlib.pbkdf2_hmac("sha256", passphrase.encode("utf-8"), bytes.fromhex(salt), 600000)
            self.payload = {"version": 1, "id": self.id, "salt": salt, "policy": "", "sources": [], "entries": []}
            if self.path.exists():
                raise VideoMateError("checkpoint_invalid")
        policy_tag = self.tag(b"policy", canonical({"version": __version__, **policy}))
        if self.resuming and policy_tag != self.payload["policy"]:
            raise VideoMateError("checkpoint_policy_changed")
        self.payload["policy"] = policy_tag

    def tag(self, domain, data):
        return hmac.digest(self.key, domain + b"\0" + data, "sha256").hex()

    def _validate(self):
        p = self.payload
        if not HEX64.fullmatch(p["policy"]) or type(p["sources"]) is not list or not 1 <= len(p["sources"]) <= 1000:
            raise ValueError()
        if any(type(tag) is not str or not HEX64.fullmatch(tag) for tag in p["sources"]):
            raise ValueError()
        if type(p["entries"]) is not list or len(p["entries"]) > len(p["sources"]):
            raise ValueError()
        numbers = set()
        for entry in p["entries"]:
            if type(entry) is not dict or set(entry) != {"source", "number", "report", "artifact"} or entry["source"] not in p["sources"]:
                raise ValueError()
            number = entry["number"]
            if (type(number) is not int or not 1 <= number <= len(p["sources"])
                    or number in numbers or entry["source"] != p["sources"][number - 1]):
                raise ValueError()
            numbers.add(number)
            validate_export(entry["report"])
            if len(entry["report"]["files"]) != 1:
                raise ValueError()
            artifact = entry["artifact"]
            state = entry["report"]["files"][0]["recovery_state"]
            if state not in {"not_requested", "not_needed", "verified", "verified_with_losses"}:
                raise ValueError()
            if (state in {"verified", "verified_with_losses"}) != (artifact is not None):
                raise ValueError()
            if artifact is not None and (type(artifact) is not dict or set(artifact) != {"token", "suffix", "tag", "number"}
                    or not HEX32.fullmatch(artifact["token"]) or artifact["suffix"] not in {".mp4", ".mkv"}
                    or not HEX64.fullmatch(artifact["tag"]) or type(artifact["number"]) is not int or not 1 <= artifact["number"] <= 1000):
                raise ValueError()

    def file_digest(self, path, cancel):
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            while block := stream.read(1024 * 1024):
                if cancel.is_set():
                    raise KeyboardInterrupt()
                digest.update(block)
        return digest.digest()

    def bind_sources(self, job, paths, scope, cancel, emit):
        tokens = []
        for number, source in enumerate(paths, 1):
            scope.authorize(source)
            emit(f"Matching private resume input {number}/{len(paths)}...")
            before = _fingerprint(source)
            token = self.tag(b"source", self.file_digest(source, cancel))
            if before != _fingerprint(source):
                raise VideoMateError("checkpoint_sources_changed")
            self.tokens[number], self.fingerprints[number] = token, before
            tokens.append(token)
        if self.resuming and Counter(tokens) != Counter(self.payload["sources"]):
            raise VideoMateError("checkpoint_sources_changed")
        old = list(self.payload["entries"])
        reordered = []
        for number, token in enumerate(tokens, 1):
            matched = next((entry for entry in old if entry["source"] == token), None)
            if matched:
                old.remove(matched)
                reordered.append({**matched, "number": number})
        self.payload["entries"] = reordered
        self.payload["sources"] = tokens
        self.remaining = list(self.payload["entries"])
        self.save()

    def restore(self, number, source, recovered_root, backend_version, cancel):
        for entry in list(self.remaining):
            if entry["source"] != self.tokens[number]:
                continue
            result = from_report(entry["report"])
            artifact = entry["artifact"]
            if artifact:
                output = plain_local_path(recovered_root / self.id / ("input-" + str(artifact["number"])) / (artifact["token"] + artifact["suffix"]))
                if not output.is_file():
                    continue
                before = _fingerprint(output)
                digest = self.file_digest(output, cancel)
                if before != _fingerprint(output) or self.tag(b"output", digest) != artifact["tag"]:
                    continue
                result.recovery["private_output"] = str(output)
                result.recovery["private_output_sha256"] = digest.hex()
            result.fingerprint = self.fingerprints[number]
            result.technical["backend_version"] = backend_version
            self.remaining.remove(entry)
            return result
        return None

    def remember(self, number, result, version, recovered_root):
        if result.state != "complete" or tuple(result.fingerprint or ()) != self.fingerprints[number] or any(f.category == "input_changed" for f in result.findings):
            return
        recovery = result.recovery or {}
        if recovery and recovery["recovery_state"] not in {"not_needed", "verified", "verified_with_losses"}:
            return
        report = load_json(create_export([result], UUID(hex=self.id), secrets.token_bytes(32), environment(version, version)))
        artifact = None
        if recovery.get("private_output"):
            output = Path(recovery["private_output"])
            expected = recovered_root / self.id / ("input-" + str(number))
            if output.parent != expected or not HEX32.fullmatch(output.stem) or output.suffix not in {".mp4", ".mkv"}:
                raise VideoMateError("checkpoint_invalid")
            artifact = {"number": number, "token": output.stem, "suffix": output.suffix,
                        "tag": self.tag(b"output", bytes.fromhex(recovery["private_output_sha256"]))}
        entry = {"source": self.tokens[number], "number": number, "report": report, "artifact": artifact}
        self.payload["entries"] = [e for e in self.payload["entries"] if e["number"] != number] + [entry]
        self.save()

    def save(self):
        self._validate()
        encoded = canonical({"payload": self.payload, "mac": self.tag(b"checkpoint", canonical(self.payload))})
        if len(encoded) > MAX_EXPORT_BYTES:
            raise VideoMateError("export_too_large")
        temporary = self.path.with_name("checkpoint-write-" + secrets.token_hex(16) + ".tmp")
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(descriptor, "wb") as output:
                output.write(encoded)
            plain_local_path(self.path)
            os.replace(temporary, self.path)
        finally:
            if temporary.exists():
                temporary.unlink()

    def finish(self):
        plain_local_path(self.path).unlink()
