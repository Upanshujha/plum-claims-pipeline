"""Stage 8: Fraud / Anomaly detection.

Heuristic signals. Thresholds come from policy_terms.json (fraud_thresholds).
Fraud alone never REJECTS — at worst it escalates to MANUAL_REVIEW.
TC009 is the acceptance test.
"""
from __future__ import annotations

from app.models import ClaimSubmission, FraudSignal
from app.policy import Policy


def detect_fraud(submission: ClaimSubmission, policy: Policy) -> dict:
    signals: list[FraudSignal] = []
    thresholds = policy.fraud_thresholds
    score = 0.0

    # --------- same-day frequency ---------
    same_day_count = sum(
        1 for c in submission.claims_history
        if c.get("date") == submission.treatment_date.isoformat()
    )
    total_today = same_day_count + 1   # include this new claim
    if total_today > thresholds["same_day_claims_limit"]:
        signals.append(FraudSignal(
            code="SAME_DAY_FREQUENCY",
            severity="HIGH",
            description=f"{total_today} claims submitted on the same day "
                        f"(threshold {thresholds['same_day_claims_limit']})",
            value=total_today,
        ))
        score += 0.6

    # --------- high-value auto-review ---------
    if submission.claimed_amount >= thresholds.get("auto_manual_review_above", 10 ** 9):
        signals.append(FraudSignal(
            code="HIGH_VALUE_CLAIM",
            severity="MEDIUM",
            description=f"Claim amount ₹{submission.claimed_amount:,} "
                        f"is above the auto-review threshold.",
            value=submission.claimed_amount,
        ))
        score += 0.3

    # --------- provider repetition ---------
    providers = [c.get("provider") for c in submission.claims_history]
    if len(providers) >= 2 and len(set(providers)) != len(providers):
        signals.append(FraudSignal(
            code="PROVIDER_REPETITION",
            severity="LOW",
            description="Repeated provider across recent claims.",
        ))
        score += 0.1

    score = min(1.0, score)

    forces_manual_review = any(s.severity == "HIGH" for s in signals) or \
                           score >= thresholds.get("fraud_score_manual_review_threshold", 0.80)

    return {
        "score": score,
        "signals": signals,
        "forces_manual_review": forces_manual_review,
    }
