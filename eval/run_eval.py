"""Eval runner.

Loads test_cases.json and runs each one through the pipeline. Produces:
  * A Markdown eval report (eval/eval_report.md)
  * A JSON summary with actual vs expected decisions
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

# Allow running from project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.models import ClaimSubmission, Decision, to_dict
from app.pipeline import Pipeline
from app.policy import load_policy


def run_all():
    root = Path(__file__).resolve().parent.parent
    policy = load_policy(str(root / "policy_terms.json"))
    pipeline = Pipeline(policy)

    with open(root / "test_cases.json") as f:
        cases = json.load(f)

    results = []
    matches = 0

    for tc in cases["test_cases"]:
        case_id = tc["case_id"]
        case_name = tc["case_name"]
        submission_dict = tc["input"]
        expected = tc["expected"]

        # Build the ClaimSubmission
        try:
            submission = ClaimSubmission.from_dict(submission_dict)
        except Exception as e:
            results.append({
                "case_id": case_id, "case_name": case_name,
                "status": "ERROR_BUILDING_SUBMISSION",
                "error": str(e),
                "match": False,
            })
            continue

        decision = pipeline.run(submission)
        match, match_reason = _evaluate_match(decision, expected)
        if match:
            matches += 1

        results.append({
            "case_id": case_id,
            "case_name": case_name,
            "expected": expected,
            "actual_decision": decision.decision.value if decision.decision else None,
            "actual_amount": decision.approved_amount,
            "confidence": round(decision.confidence, 2),
            "user_message": decision.user_message,
            "rejection_reasons": decision.rejection_reasons,
            "calc_breakdown": [to_dict(c) for c in decision.calc_breakdown],
            "fraud_signals": [to_dict(s) for s in decision.fraud_signals],
            "skipped_stages": decision.skipped_stages,
            "trace_summary": [
                {"stage": t.stage, "status": t.status.value if hasattr(t.status, "value")
                 else str(t.status), "latency_ms": t.latency_ms}
                for t in decision.trace
            ],
            "match": match,
            "match_reason": match_reason,
        })

    summary = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "total_cases": len(results),
        "matched": matches,
        "results": results,
    }
    (root / "eval" / "eval_results.json").write_text(json.dumps(summary, indent=2, default=str))
    _write_report(root / "eval" / "eval_report.md", summary)
    print(f"\n=== Eval Summary: {matches}/{len(results)} matched ===")
    for r in results:
        mark = "PASS" if r["match"] else "FAIL"
        print(f"  {r['case_id']}  {mark}  {r['actual_decision']}  "
              f"₹{r.get('actual_amount', 0):,}  ({r['match_reason']})")
    return summary


def _evaluate_match(decision, expected) -> tuple[bool, str]:
    expected_decision = expected.get("decision")
    actual_decision = decision.decision.value if decision.decision else None

    # Cases where expected.decision is null (TC001/02/03) — the system must
    # have stopped before making a claim decision.
    if expected_decision is None:
        if actual_decision is None:
            return True, "stopped before decision, as required"
        return False, f"expected a stop but got {actual_decision}"

    if actual_decision != expected_decision:
        return False, f"expected {expected_decision} got {actual_decision}"

    expected_amount = expected.get("approved_amount")
    if expected_amount is not None and decision.approved_amount != expected_amount:
        return False, (f"decision match but amount ₹{decision.approved_amount} "
                       f"!= expected ₹{expected_amount}")

    expected_rejection = expected.get("rejection_reasons")
    if expected_rejection:
        if not all(r in decision.rejection_reasons for r in expected_rejection):
            return False, (f"missing expected rejection_reasons {expected_rejection}, "
                           f"got {decision.rejection_reasons}")

    return True, "decision and amount match expected"


def _write_report(path: Path, summary: dict):
    lines = []
    lines.append("# Eval Report — 12 Test Cases\n")
    lines.append(f"Generated: {summary['generated_at']}\n")
    lines.append(f"Summary: **{summary['matched']}/{summary['total_cases']} matched**\n")

    lines.append("\n## Summary Table\n")
    lines.append("| Case | Expected | Actual | Amount | Match |")
    lines.append("|------|----------|--------|--------|-------|")
    for r in summary["results"]:
        exp = r["expected"].get("decision") or "STOP / ASK_REUPLOAD"
        amt_exp = r["expected"].get("approved_amount")
        amt_s = f"₹{r['actual_amount']:,}" if r["actual_amount"] else "—"
        if amt_exp is not None:
            amt_s = f"₹{r['actual_amount']:,} / ₹{amt_exp:,} expected"
        mark = "✅" if r["match"] else "❌"
        lines.append(f"| {r['case_id']} | {exp} | {r['actual_decision'] or '—'} "
                     f"| {amt_s} | {mark} |")

    lines.append("\n## Per-case detail\n")
    for r in summary["results"]:
        lines.append(f"### {r['case_id']} — {r['case_name']}")
        lines.append(f"- Expected: `{r['expected']}`")
        lines.append(f"- Actual decision: **{r['actual_decision']}**"
                     f" (amount ₹{r['actual_amount']:,}, confidence {r['confidence']})")
        if r["rejection_reasons"]:
            lines.append(f"- Rejection reasons: {r['rejection_reasons']}")
        if r["user_message"]:
            lines.append(f"- User message: _{r['user_message']}_")
        if r["calc_breakdown"]:
            lines.append("- Calc breakdown:")
            for step in r["calc_breakdown"]:
                lines.append(f"  - `{step['label']}`: ₹{step['amount_before']:,} "
                             f"→ ₹{step['amount_after']:,} ({step['rule']})")
        if r["fraud_signals"]:
            lines.append(f"- Fraud signals: {[s['code'] for s in r['fraud_signals']]}")
        if r["skipped_stages"]:
            lines.append(f"- Skipped stages: {r['skipped_stages']}")
        lines.append(f"- Trace: `{' → '.join(t['stage'] + ':' + t['status'] for t in r['trace_summary'])}`")
        lines.append(f"- Match: **{r['match']}** — {r['match_reason']}")
        lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    run_all()
