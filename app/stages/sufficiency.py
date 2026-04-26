"""Stage 3: Sufficiency Gate.

Compares classified document types against policy.document_requirements for
the claim category. If required documents are missing, stops the pipeline
with a specific, named message. Never generic.
"""
from __future__ import annotations

from app.models import (ClaimCategory, DocClassification, DocType,
                        StageStatus)
from app.policy import Policy


def check_sufficiency(
    category: ClaimCategory,
    classifications: list[DocClassification],
    policy: Policy,
) -> dict:
    reqs = policy.document_requirements(category.value)
    required = set(reqs["required"])
    present_types = [c.predicted_type.value for c in classifications]

    # Substitution rules: some document types can stand in for others when
    # the claim context makes the requirement redundant. For DIAGNOSTIC claims,
    # the HOSPITAL_BILL issued by the imaging lab typically serves as the
    # diagnostic report itself (MRI, CT, PET are billed and reported on the
    # same document). TC007 requires the pipeline to proceed to pre-auth
    # checks for an MRI even without a separate LAB_REPORT.
    substitutions = {
        ClaimCategory.DIAGNOSTIC: {"LAB_REPORT": ["HOSPITAL_BILL", "DIAGNOSTIC_REPORT"]},
    }
    sub_rules = substitutions.get(category, {})
    for req_type, substitutes in sub_rules.items():
        if req_type in required and req_type not in present_types:
            if any(s in present_types for s in substitutes):
                required.discard(req_type)

    missing = [r for r in required if r not in present_types]

    # identify "wrong" uploads — present types that are not required or optional
    allowed = required | set(reqs.get("optional", []))
    wrong = []
    for c in classifications:
        if c.predicted_type.value not in allowed and c.predicted_type != DocType.UNKNOWN:
            wrong.append((c.file_id, c.predicted_type.value))

    if not missing and not wrong:
        return {"status": StageStatus.PASS, "missing": [], "wrong": [],
                "user_message": ""}

    # Build a specific, named message.
    pretty_cat = category.value.replace("_", " ").lower()
    parts = []
    if missing:
        if len(missing) == 1:
            parts.append(f"we also need a {_pretty(missing[0])}")
        else:
            parts.append("we also need " + ", ".join(f"a {_pretty(m)}" for m in missing))
    if wrong:
        wrong_names = ", ".join(_pretty(w[1]) for w in wrong)
        parts.append(f"we can't accept {wrong_names} for this claim type")

    # Count uploaded types by prediction — makes the message explicit about what
    # actually arrived. This is the pattern TC001 expects.
    type_counts: dict[str, int] = {}
    for c in classifications:
        type_counts[c.predicted_type.value] = type_counts.get(c.predicted_type.value, 0) + 1
    uploaded_summary = ", ".join(
        f"{n} {_pretty(t)}{'s' if n > 1 else ''}" for t, n in type_counts.items()
    )

    msg = (
        f"You uploaded {uploaded_summary}, but for a {pretty_cat} claim "
        f"{'; '.join(parts)}. Please add the missing document(s) and resubmit."
    )

    return {
        "status": StageStatus.STOP,
        "missing": missing,
        "wrong": [w[1] for w in wrong],
        "user_message": msg,
    }


def _pretty(doc_type: str) -> str:
    return doc_type.replace("_", " ").lower()
