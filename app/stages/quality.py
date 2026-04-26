"""Stage 5: Quality Gate.

Flags unreadable documents and asks for re-upload. Never auto-rejects the
claim because of quality alone. TC002 tests this explicitly.
"""
from __future__ import annotations

from statistics import median

from app.models import ParsedDoc, Quality, StageStatus


UNREADABLE_CONFIDENCE_THRESHOLD = 0.40


def check_quality(parsed_docs: list[ParsedDoc]) -> dict:
    reupload_targets = []
    for p in parsed_docs:
        fcs = list(p.field_confidence.values())
        field_median = median(fcs) if fcs else 0.0
        if p.quality == Quality.UNREADABLE or field_median < UNREADABLE_CONFIDENCE_THRESHOLD:
            reupload_targets.append((p.file_id, p.doc_type.value, field_median))

    if not reupload_targets:
        return {"status": StageStatus.PASS, "reupload_targets": [], "user_message": ""}

    fid, dtype, conf = reupload_targets[0]
    pretty = dtype.replace("_", " ").lower()
    msg = (
        f"We received your claim, but the {pretty} (file {fid}) was too "
        f"unclear to read (confidence {conf:.2f}). Please re-upload a clearer "
        f"photo of just that document — you don't need to resend the others."
    )

    return {
        "status": StageStatus.ASK_REUPLOAD,
        "reupload_targets": reupload_targets,
        "user_message": msg,
    }
