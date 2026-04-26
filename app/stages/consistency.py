"""Stage 6: Cross-Doc Consistency.

Checks that patient names agree across documents. Flags mismatches with the
exact names found and the files involved. TC003 is the acceptance test.
"""
from __future__ import annotations

from app.models import Mismatch, ParsedDoc, StageStatus


def _normalize(name: str) -> str:
    return " ".join(name.lower().strip().split())


def check_consistency(parsed_docs: list[ParsedDoc]) -> dict:
    # collect patient names
    names_by_file: dict[str, str] = {}
    for p in parsed_docs:
        if p.patient_name:
            names_by_file[p.file_id] = p.patient_name

    distinct = {_normalize(n) for n in names_by_file.values()}
    if len(distinct) <= 1:
        return {"status": StageStatus.PASS, "mismatches": [], "user_message": ""}

    mismatches = [
        Mismatch(
            field_name="patient_name",
            values_found=sorted(set(names_by_file.values())),
            files_involved=list(names_by_file.keys()),
        )
    ]

    # first two distinct names
    values = mismatches[0].values_found
    files = mismatches[0].files_involved
    msg = (
        f"Your documents appear to be for different people — we found "
        f"\"{values[0]}\" (file {files[0]}) and \"{values[1]}\" (file {files[1]}). "
        f"Both documents need to be for the same person. Please check and re-upload."
    )

    return {
        "status": StageStatus.STOP,
        "mismatches": mismatches,
        "user_message": msg,
    }
