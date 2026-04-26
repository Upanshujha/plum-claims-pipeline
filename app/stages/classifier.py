"""Stage 2: Document Classifier.

Two modes:
  * 'fixture' — used in tests and the eval runner. Reads `actual_type` from the
    submitted document. This lets us test the rest of the pipeline deterministically.
  * 'vision' — production hook for a vision LLM (GPT-4o). Not wired to a real
    provider in this prototype; left as a function boundary with the same return shape.

The prototype ships in fixture mode. Flipping the mode is a single line change.
"""
from __future__ import annotations

from app.models import DocClassification, DocType, UploadedDoc


MODE = "fixture"   # "fixture" | "vision"


def classify_documents(docs: list[UploadedDoc]) -> list[DocClassification]:
    if MODE == "fixture":
        return [_classify_from_fixture(d) for d in docs]
    return [_classify_with_vision(d) for d in docs]   # pragma: no cover


def _classify_from_fixture(doc: UploadedDoc) -> DocClassification:
    """Use the actual_type field already present on the test input."""
    t = doc.actual_type or "UNKNOWN"
    try:
        predicted = DocType(t)
    except ValueError:
        predicted = DocType.UNKNOWN
    return DocClassification(
        file_id=doc.file_id,
        predicted_type=predicted,
        confidence=0.98 if predicted is not DocType.UNKNOWN else 0.0,
        reasons=["classified from test fixture"],
    )


def _classify_with_vision(doc: UploadedDoc) -> DocClassification:   # pragma: no cover
    """Placeholder for a real GPT-4o vision call.

    Production flow:
      - read doc bytes from blob store
      - call vision model with a closed-set classification prompt
      - parse response into DocClassification
      - on timeout, fall back to a filename-heuristic classifier
    """
    raise NotImplementedError(
        "Vision classifier is not wired in this prototype. Use fixture mode."
    )
