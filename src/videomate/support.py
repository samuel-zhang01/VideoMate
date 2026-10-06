"""A small, identifier-free summary of an already sanitized export."""
from collections import Counter

from .schema import validate_export


def support_summary(document):
    # Validate before using any field; never pass unrecognized text through.
    validate_export(document)
    files = document["files"]
    findings = Counter()
    attempts = Counter()
    encoders = Counter()
    stages, decoders, limits, worker_messages = Counter(), Counter(), Counter(), Counter()
    for entry in files:
        for finding in entry["findings"]:
            findings[finding["category"]] += finding["count"]
        for attempt in entry["attempts"]:
            attempts[attempt["outcome"] + ":" + attempt["reason"]] += 1
            encoders[attempt.get("encoder", "not_recorded")] += 1
        for detail in entry.get("diagnostics", []):
            stages[detail["stage"] + ":" + detail["outcome"]] += 1
            if detail["decoder"] != "none":
                decoders[detail["decoder"]] += 1
            if detail["limit_reason"] != "none":
                limits[detail["limit_reason"]] += 1
            for message in detail["messages"]:
                worker_messages[message["category"] + ":" + message["severity"]] += message["count"]
    return {"support_summary_version": 1, "environment": dict(document["environment"]),
            "coverage": "one_diagnostic_batch",
            **({"migration_summary": dict(document["migration_summary"])} if "migration_summary" in document else {}),
            "files_count": len(files), "files_omitted": document["files_omitted"],
            "integrity": dict(sorted(Counter(f["integrity"] for f in files).items())),
            "recovery": dict(sorted(Counter(f["recovery_state"] for f in files).items())),
            "migration": dict(sorted(Counter(f["migration"]["action"] for f in files if "migration" in f).items())),
            "migration_reasons": dict(sorted(Counter(f["migration"]["reason"] for f in files if "migration" in f).items())),
            "recovery_notes": dict(sorted(Counter(note for f in files for note in f.get("recovery_notes", [])).items())),
            "findings": dict(sorted(findings.items())), "attempts": dict(sorted(attempts.items())),
            "encoders": dict(sorted(encoders.items())),
            "stages": dict(sorted(stages.items())), "decoders": dict(sorted(decoders.items())),
            "limits": dict(sorted(limits.items())),
            "worker_messages": dict(sorted(worker_messages.items())),
            "diagnostics_omitted": sum(f.get("diagnostics_omitted", 0) for f in files),
            "findings_omitted": sum(f["findings_omitted"] for f in files)}
