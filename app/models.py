"""Data models for the claims pipeline.

Uses stdlib dataclasses to keep the prototype dependency-free. In production
I would port these to Pydantic v2 for runtime validation; the field shapes
map 1:1. Every stage of the pipeline accepts and returns typed objects —
no free-form dicts crossing stage boundaries.
"""
from __future__ import annotations

from dataclasses import dataclass, field, fields
from datetime import date, datetime
from enum import Enum
from typing import Any, Optional


# ----------------------------- enums -----------------------------------------

class ClaimCategory(str, Enum):
    CONSULTATION = "CONSULTATION"
    DIAGNOSTIC = "DIAGNOSTIC"
    PHARMACY = "PHARMACY"
    DENTAL = "DENTAL"
    VISION = "VISION"
    ALTERNATIVE_MEDICINE = "ALTERNATIVE_MEDICINE"


class DocType(str, Enum):
    PRESCRIPTION = "PRESCRIPTION"
    HOSPITAL_BILL = "HOSPITAL_BILL"
    PHARMACY_BILL = "PHARMACY_BILL"
    LAB_REPORT = "LAB_REPORT"
    DIAGNOSTIC_REPORT = "DIAGNOSTIC_REPORT"
    DENTAL_REPORT = "DENTAL_REPORT"
    DISCHARGE_SUMMARY = "DISCHARGE_SUMMARY"
    UNKNOWN = "UNKNOWN"


class Decision(str, Enum):
    APPROVED = "APPROVED"
    PARTIAL = "PARTIAL"
    REJECTED = "REJECTED"
    MANUAL_REVIEW = "MANUAL_REVIEW"


class Quality(str, Enum):
    GOOD = "GOOD"
    DEGRADED = "DEGRADED"
    UNREADABLE = "UNREADABLE"


class StageStatus(str, Enum):
    PASS = "PASS"
    STOP = "STOP"
    ASK_REUPLOAD = "ASK_REUPLOAD"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


# ----------------------------- serialization helper --------------------------

def to_dict(obj):
    """Recursively convert dataclass/enum/list/dict structures to plain dicts."""
    if obj is None:
        return None
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    if isinstance(obj, (list, tuple)):
        return [to_dict(x) for x in obj]
    if isinstance(obj, dict):
        return {k: to_dict(v) for k, v in obj.items()}
    if hasattr(obj, "__dataclass_fields__"):
        return {f.name: to_dict(getattr(obj, f.name)) for f in fields(obj)}
    return obj


# ----------------------------- inputs ----------------------------------------

@dataclass
class UploadedDoc:
    file_id: str
    file_name: Optional[str] = None
    actual_type: Optional[str] = None
    patient_name_on_doc: Optional[str] = None
    quality: Optional[str] = None
    content: Optional[dict] = None


@dataclass
class ClaimSubmission:
    member_id: str
    policy_id: str
    claim_category: ClaimCategory
    treatment_date: date
    claimed_amount: int
    documents: list = field(default_factory=list)
    hospital_name: Optional[str] = None
    ytd_claims_amount: int = 0
    claims_history: list = field(default_factory=list)
    simulate_component_failure: bool = False

    @classmethod
    def from_dict(cls, d: dict) -> "ClaimSubmission":
        """Build from the kind of dict we get out of test_cases.json."""
        allowed = {f.name for f in fields(UploadedDoc)}
        docs = [UploadedDoc(**{k: v for k, v in doc.items() if k in allowed})
                for doc in d.get("documents", [])]
        raw = d["treatment_date"]
        tdate = datetime.strptime(raw, "%Y-%m-%d").date() if isinstance(raw, str) else raw
        return cls(
            member_id=d["member_id"],
            policy_id=d["policy_id"],
            claim_category=ClaimCategory(d["claim_category"]),
            treatment_date=tdate,
            claimed_amount=int(d["claimed_amount"]),
            documents=docs,
            hospital_name=d.get("hospital_name"),
            ytd_claims_amount=int(d.get("ytd_claims_amount") or 0),
            claims_history=list(d.get("claims_history", [])),
            simulate_component_failure=bool(d.get("simulate_component_failure", False)),
        )


# ----------------------------- intermediate ----------------------------------

@dataclass
class DocClassification:
    file_id: str
    predicted_type: DocType
    confidence: float
    reasons: list = field(default_factory=list)


@dataclass
class LineItem:
    description: str
    amount: int


@dataclass
class ParsedDoc:
    file_id: str
    doc_type: DocType
    patient_name: Optional[str] = None
    doctor_name: Optional[str] = None
    doctor_registration: Optional[str] = None
    hospital_name: Optional[str] = None
    diagnosis: Optional[str] = None
    treatment: Optional[str] = None
    medicines: list = field(default_factory=list)
    line_items: list = field(default_factory=list)
    total: Optional[int] = None
    date: Optional[str] = None
    field_confidence: dict = field(default_factory=dict)
    quality: Quality = Quality.GOOD


@dataclass
class Mismatch:
    field_name: str
    values_found: list
    files_involved: list


@dataclass
class FraudSignal:
    code: str
    severity: str
    description: str
    value: Any = None


@dataclass
class CalcStep:
    label: str
    amount_before: int
    amount_after: int
    rule: str


# ----------------------------- outputs ---------------------------------------

@dataclass
class StageTrace:
    stage: str
    status: StageStatus
    latency_ms: int
    warnings: list = field(default_factory=list)
    payload: dict = field(default_factory=dict)


@dataclass
class ClaimDecision:
    claim_id: str
    decision: Optional[Decision] = None
    approved_amount: int = 0
    confidence: float = 0.0
    reasons: list = field(default_factory=list)
    rejection_reasons: list = field(default_factory=list)
    user_message: str = ""
    calc_breakdown: list = field(default_factory=list)
    fraud_signals: list = field(default_factory=list)
    skipped_stages: list = field(default_factory=list)
    manual_review_recommended: bool = False
    trace: list = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
