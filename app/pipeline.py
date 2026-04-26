"""Pipeline orchestrator.

Runs the nine stages sequentially, building a trace along the way. Every stage
runs inside a wrapper that catches exceptions and either raises (for
non-skippable stages) or appends a FAILED trace entry and continues
(for skippable ones).
"""
from __future__ import annotations

import time
import uuid
from typing import Any, Optional

from app.models import (ClaimCategory, ClaimDecision, ClaimSubmission, Decision,
                        StageStatus, StageTrace, to_dict)
from app.policy import Policy, load_policy
from app.stages import (classifier, consistency, fraud, intake, parser,
                        quality, rejection_explainer, rules_engine,
                        sufficiency, synthesizer)
from app.stages.intake import IntakeError


SKIPPABLE_STAGES = {"consistency"}


class Pipeline:
    def __init__(self, policy: Optional[Policy] = None):
        self.policy = policy or load_policy()

    def run(self, submission: ClaimSubmission) -> ClaimDecision:
        claim_id = f"CLM_{uuid.uuid4().hex[:8].upper()}"
        trace: list[StageTrace] = []
        skipped: list[str] = []
        base_confidence = 0.95

        # ----- Stage 1: Intake -----
        t0 = time.time()
        try:
            intake_out = intake.run_intake(submission, self.policy)
            trace.append(StageTrace(
                stage="intake",
                status=StageStatus.PASS,
                latency_ms=_ms(t0),
                warnings=intake_out.get("warnings", []),
                payload={"primary_member_id": intake_out["primary_member_id"]},
            ))
            member = intake_out["member"]
        except IntakeError as e:
            trace.append(StageTrace(
                stage="intake",
                status=StageStatus.STOP,
                latency_ms=_ms(t0),
                warnings=[e.code],
                payload={"code": e.code, "message": e.message},
            ))
            return synthesizer.synthesize(
                claim_id, None, None, base_confidence, [],
                e.message, trace,
            )

        # ----- Stage 2: Classifier -----
        t0 = time.time()
        classifications = classifier.classify_documents(submission.documents)
        trace.append(StageTrace(
            stage="classifier",
            status=StageStatus.PASS,
            latency_ms=_ms(t0),
            payload={"classifications": [to_dict(c) for c in classifications]},
        ))

        # ----- Stage 3: Sufficiency -----
        t0 = time.time()
        suff = sufficiency.check_sufficiency(
            submission.claim_category, classifications, self.policy)
        trace.append(StageTrace(
            stage="sufficiency",
            status=StageStatus(suff["status"]) if isinstance(suff["status"], str)
                   else suff["status"],
            latency_ms=_ms(t0),
            payload={
                "missing": suff["missing"],
                "wrong": suff["wrong"],
                "user_message": suff["user_message"],
            },
        ))
        if suff["status"] == StageStatus.STOP:
            return synthesizer.synthesize(
                claim_id, None, None, base_confidence, [],
                suff["user_message"], trace,
            )

        # ----- Stage 4: Parser -----
        t0 = time.time()
        parsed_docs = parser.parse_documents(submission.documents, classifications)
        trace.append(StageTrace(
            stage="parser",
            status=StageStatus.PASS,
            latency_ms=_ms(t0),
            payload={"parsed": [to_dict(p) for p in parsed_docs]},
        ))

        # ----- Stage 5: Quality -----
        t0 = time.time()
        qual = quality.check_quality(parsed_docs)
        trace.append(StageTrace(
            stage="quality",
            status=StageStatus(qual["status"]) if isinstance(qual["status"], str)
                   else qual["status"],
            latency_ms=_ms(t0),
            payload={
                "reupload_targets": qual["reupload_targets"],
                "user_message": qual["user_message"],
            },
        ))
        if qual["status"] == StageStatus.ASK_REUPLOAD:
            return synthesizer.synthesize(
                claim_id, None, None, base_confidence, [],
                qual["user_message"], trace,
            )

        # ----- Stage 6: Consistency (skippable) -----
        t0 = time.time()
        try:
            if submission.simulate_component_failure:
                # Simulate a stage-level crash to exercise TC011.
                raise RuntimeError("Simulated component failure in consistency stage.")
            cons = consistency.check_consistency(parsed_docs)
            trace.append(StageTrace(
                stage="consistency",
                status=StageStatus(cons["status"]) if isinstance(cons["status"], str)
                       else cons["status"],
                latency_ms=_ms(t0),
                payload={
                    "mismatches": [to_dict(m) for m in cons["mismatches"]],
                    "user_message": cons["user_message"],
                },
            ))
            if cons["status"] == StageStatus.STOP:
                return synthesizer.synthesize(
                    claim_id, None, None, base_confidence, [],
                    cons["user_message"], trace,
                )
        except Exception as e:
            trace.append(StageTrace(
                stage="consistency",
                status=StageStatus.FAILED,
                latency_ms=_ms(t0),
                warnings=[str(e)],
                payload={"error": str(e)},
            ))
            skipped.append("consistency")

        # ----- Stage 7: Rules Engine -----
        t0 = time.time()
        rules_result = rules_engine.evaluate(submission, parsed_docs, self.policy, member)
        trace.append(StageTrace(
            stage="rules_engine",
            status=StageStatus.PASS,
            latency_ms=_ms(t0),
            payload={
                "decision": rules_result.decision.value if hasattr(
                    rules_result.decision, "value") else str(rules_result.decision),
                "approved_amount": rules_result.approved_amount,
                "reasons": rules_result.reasons,
                "calc_steps": [to_dict(c) for c in rules_result.calc_steps],
            },
        ))

        # ----- Stage 8: Fraud -----
        t0 = time.time()
        fraud_result = fraud.detect_fraud(submission, self.policy)
        trace.append(StageTrace(
            stage="fraud",
            status=StageStatus.PASS,
            latency_ms=_ms(t0),
            payload={
                "score": fraud_result["score"],
                "signals": [to_dict(s) for s in fraud_result["signals"]],
                "forces_manual_review": fraud_result["forces_manual_review"],
            },
        ))

        # ----- Stage 9: Synthesizer -----
        t0 = time.time()
        decision = synthesizer.synthesize(
            claim_id, rules_result, fraud_result, base_confidence,
            skipped, None, trace,
        )
        trace.append(StageTrace(
            stage="synthesizer",
            status=StageStatus.PASS,
            latency_ms=_ms(t0),
            payload={
                "decision": decision.decision.value if hasattr(
                    decision.decision, "value") else str(decision.decision),
                "approved_amount": decision.approved_amount,
                "confidence": decision.confidence,
            },
        ))

        # ----- Stage 10: Rejection Explainer (REJECTED-only, beyond brief) -----
        # This stage is the only one allowed to call an external LLM. It
        # never changes the decision or the approved amount — the
        # rules_engine has already locked those. It only rewrites the
        # member-facing user_message into a humane, three-sentence
        # explanation. On any failure (no API key, network error,
        # malformed JSON) we leave the static template alone; the
        # pipeline never crashes here.
        if decision.decision == Decision.REJECTED:
            t0 = time.time()
            explanation = rejection_explainer.explain(
                rejection_reasons=decision.rejection_reasons,
                calc_breakdown=decision.calc_breakdown,
                claim_category=submission.claim_category.value,
                treatment_date=submission.treatment_date,
                claimed_amount=submission.claimed_amount,
                fallback_message=decision.user_message,
            )
            if explanation is not None:
                decision.user_message = explanation.to_user_message()
                trace.append(StageTrace(
                    stage="rejection_explainer",
                    status=StageStatus.PASS,
                    latency_ms=_ms(t0),
                    payload={
                        "model": explanation.model,
                        "headline": explanation.headline,
                        "reason": explanation.reason,
                        "next_steps": explanation.next_steps,
                    },
                ))
            else:
                trace.append(StageTrace(
                    stage="rejection_explainer",
                    status=StageStatus.SKIPPED,
                    latency_ms=_ms(t0),
                    warnings=["used_static_template"],
                    payload={"fallback_used": True},
                ))
        return decision


def _ms(t0: float) -> int:
    return int((time.time() - t0) * 1000)
