from dataclasses import dataclass, field
from enum import Enum
from uuid import UUID, uuid4


class Depth(str, Enum):
    QUICK = "quick"
    FULL = "full"


@dataclass
class Finding:
    category: str
    severity: str = "error"
    evidence: str = "decoder_reported"
    count: int = 1
    stream_index: int | None = None
    # No times are inferred from stderr order or worker progress.


@dataclass
class ScanResult:
    input_id: UUID = field(default_factory=uuid4, repr=False)
    depth: Depth = Depth.FULL
    state: str = "complete"
    integrity: str = "inconclusive"
    completeness: str = "unknown"
    container: str = "unknown"
    duration_us: int | None = None
    streams: list[dict] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    technical: dict = field(default_factory=dict, repr=False)
    fingerprint: tuple | None = field(default=None, repr=False)
    recovery: dict | None = field(default=None, repr=False)
    diagnostics: list[dict] = field(default_factory=list)
    diagnostics_omitted: int = 0

    @property
    def exit_code(self) -> int:
        if self.state == "cancelled":
            return 130
        if self.state in {"failed", "blocked"}:
            return 2
        return 0 if self.integrity == "no_errors_detected" else 1


def recovery_suggestion(result: ScanResult) -> str:
    """A plan hint, never a claim that recovery was attempted."""
    if result.state != "complete":
        return "review"
    if result.integrity == "no_errors_detected":
        return "not_needed"
    categories = {finding.category for finding in result.findings}
    if "missing_initialization" in categories:
        return "specialist_review"
    if result.integrity in {"unsupported", "unreadable", "inconclusive", "quick_check_only"}:
        return "review"
    if categories & {"decoder_error", "packet_error"}:
        return "reencode_candidate"
    if categories & {"container_error", "index_error", "timestamp_error"}:
        return "container_repair_candidate"
    return "review"
