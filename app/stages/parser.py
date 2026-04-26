"""Stage 4: Document Parser.

Fixture mode maps the test input's `content` dict directly into a ParsedDoc.
Vision mode would fan out to per-document GPT-4o calls with structured output.
"""
from __future__ import annotations

from app.models import (DocClassification, DocType, LineItem, ParsedDoc,
                        Quality, UploadedDoc)


MODE = "fixture"


def parse_documents(
    docs: list[UploadedDoc],
    classifications: list[DocClassification],
) -> list[ParsedDoc]:
    parsed: list[ParsedDoc] = []
    by_fid = {c.file_id: c for c in classifications}
    for d in docs:
        cls = by_fid.get(d.file_id)
        if cls is None:
            continue
        if MODE == "fixture":
            parsed.append(_parse_from_fixture(d, cls.predicted_type))
        else:                                               # pragma: no cover
            parsed.append(_parse_with_vision(d, cls.predicted_type))
    return parsed


def _parse_from_fixture(doc: UploadedDoc, doc_type: DocType) -> ParsedDoc:
    content = doc.content or {}
    quality_str = (doc.quality or "GOOD").upper()
    try:
        quality = Quality(quality_str)
    except ValueError:
        quality = Quality.GOOD

    line_items = [
        LineItem(description=li["description"], amount=int(li["amount"]))
        for li in content.get("line_items", [])
    ]

    patient = content.get("patient_name") or doc.patient_name_on_doc

    pd = ParsedDoc(
        file_id=doc.file_id,
        doc_type=doc_type,
        patient_name=patient,
        doctor_name=content.get("doctor_name"),
        doctor_registration=content.get("doctor_registration"),
        hospital_name=content.get("hospital_name"),
        diagnosis=content.get("diagnosis"),
        treatment=content.get("treatment"),
        medicines=list(content.get("medicines", [])),
        line_items=line_items,
        total=int(content["total"]) if content.get("total") is not None else None,
        date=content.get("date"),
        quality=quality,
    )
    pd.field_confidence = _build_field_confidence(pd, quality)
    return pd


def _build_field_confidence(pd: ParsedDoc, quality: Quality) -> dict[str, float]:
    """Per-field confidence is deterministic in fixture mode: GOOD → 0.95, etc."""
    base = {Quality.GOOD: 0.95, Quality.DEGRADED: 0.60, Quality.UNREADABLE: 0.12}[quality]
    fields = []
    for f in ["patient_name", "doctor_name", "doctor_registration",
              "hospital_name", "diagnosis", "treatment", "total", "date"]:
        if getattr(pd, f) is not None:
            fields.append(f)
    if pd.line_items:
        fields.append("line_items")
    # Always include an overall signal so downstream quality checks don't
    # trip on documents whose parsed schema has fields we don't model yet
    # (e.g. lab reports with only a test_name). The overall signal carries
    # the quality level straight through.
    out = {f: base for f in fields}
    out["_overall"] = base
    return out


def _parse_with_vision(doc: UploadedDoc, doc_type: DocType) -> ParsedDoc:   # pragma: no cover
    raise NotImplementedError(
        "Vision parser is not wired in this prototype. Use fixture mode."
    )
