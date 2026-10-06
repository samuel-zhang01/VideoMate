"""Scripted synthetic responses. This demo is not an FFmpeg integration test."""

import json
import tempfile
from pathlib import Path
from uuid import uuid4

from .diagnostics import create_export, environment
from .inspection import Inspector
from .policy import SyntheticScope
from .runner import ProcessResult

# Public test material only, never a production credential.
SYNTHETIC_KEY = bytes(range(32))


class SyntheticBackend:
    def __init__(self, scenario: str):
        self.scenario = scenario

    def probe(self, source):
        if self.scenario == "unreadable":
            return ProcessResult(1, stderr=b"[error] moov atom not found: SYNTHETIC_PRIVATE_FILENAME\n")
        streams = [
            {"index": 0, "codec_type": "video", "codec_name": "h264", "width": 320,
             "height": 240, "avg_frame_rate": "25/1", "duration": "2.0",
             "tags": {"title": "SYNTHETIC_PRIVATE_METADATA"}},
            {"index": 1, "codec_type": "audio", "codec_name": "aac", "sample_rate": "48000",
             "channels": 2, "duration": "2.0"},
        ]
        return ProcessResult(0, json.dumps({"streams": streams,
                                           "format": {"format_name": "mov,mp4,m4a,3gp,3g2,mj2", "duration": "2.0"}}).encode())

    def decode(self, source, index):
        error = b"[error] Error while decoding stream: SYNTHETIC_PRIVATE_FILENAME\n" if self.scenario == "damaged_audio" and index == 1 else b""
        return ProcessResult(0, b"frame=50\nout_time_us=2000000\nprogress=end\n", error)


def run_demo():
    # The demo creates only an inert marker, which a scripted backend never reads.
    with tempfile.TemporaryDirectory(prefix="videomate-synthetic-") as temporary:
        source = Path(temporary).resolve() / "generated-marker.bin"
        source.write_bytes(b"VideoMate synthetic marker, not a video")
        scope = SyntheticScope(frozenset({source.absolute()}))
        results = [Inspector(SyntheticBackend(scenario), scope).inspect(source)
                   for scenario in ("healthy", "damaged_audio", "unreadable")]
    export = create_export(results, uuid4(), SYNTHETIC_KEY, environment("0.0.0", "0.0.0"), synthetic=True)
    return results, export
