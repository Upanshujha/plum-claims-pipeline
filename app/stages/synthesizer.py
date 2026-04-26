"""Stage 9: Decision Synthesizer.

Takes output from every upstream stage and emits a single ClaimDecision:
decision, approved amount, confidence, trace, user-facing message.
"""
from __future__ import annotations

from typing import Optional

from app.models import (CalcStep, ClaimDecision, Decision, FraudSignal,
                        StageTrace)
from app.stages.rules_engine import RulesResult


def synthesize(
    claim_id: str,
    rules_result: Optional[RulesResult],
    fraud_result: Optional[dict],
    base_confidence: float,
    skipped_stages: list[str],
    user_message_override: Optional[str],
    trace: list[StageTrace],
) -> ClaimDecision:
    decision: Optional[Decision] = None
    approved_amount = 0
    reasons: list[str] = []
    rejection_reasons: list[str] = []
    calc_breakdown: list[CalcStep] = []
    user_message = user_message_override or ""
    fraud_signals: list[FraudSignal] = []
    manual_review = False

    if rules_result:
        decision = Decision(rules_result.decision) if isinstance(
            rules_result.decision, str) else rules_result.decision
        approved_amount = rules_result.approved_amount
        reasons = list(rules_result.reasons)
        rejection_reasons = list(rules_result.rejection_reasons)
        calc_breakdown = list(rules_result.calc_steps)
        if rules_result.user_message and not user_message:
            user_message = rules_result.user_message

    if fraud_result:
        fraud_signals = list(fraud_result.get("signals", []))
        if fraud_result.get("forces_manual_review"):
            decision = Decision.MANUAL_REVIEW
            reasons.append(
                "Escalated to manual review based on fraud signals: "
                + ", ".join(s.code for s in fraud_signals)
            )
            if not user_message:
                user_message = (
                    "Your claim has been flagged for manual review by our "
                    "team because of unusual recent activity on your account. "
                    "We'll get back to you within 48 hours."
                )

    # Confidence: start from base, penalize per skipped stage, floor at 0.10
    confidence = base_confidence
    for _ in skipped_stages:
        confidence -= 0.25
    confidence = max(0.10, min(0.99, confidence))

    if skipped_stages:
        manual_review = True
        reasons.append(
            f"Pipeline completed with skipped stages: {', '.join(skipped_stages)}. "
            "Manual review recommended."
        )

    if not user_message and decision == Decision.APPROVED:
        user_message = (
            f"Your claim has been approved for ₹{approved_amount:,}. "
            "Funds will be disbursed within 5 working days."
        )
    if not user_message and decision == Decision.PARTIAL:
        user_message = (
            f"Your claim has been partially approved for ₹{approved_amount:,}. "
            "See the breakdown for details on which items were covered."
        )

    return ClaimDecision(
        claim_id=claim_id,
        decision=decision,
        approved_amount=approved_amount,
        confidence=confidence,
        reasons=reasons,
        rejection_reasons=rejection_reasons,
        user_message=user_message,
        calc_breakdown=calc_breakdown,
        fraud_signals=fraud_signals,
        skipped_stages=skipped_stages,
        manual_review_recommended=manual_review,
        trace=trace,
    )
