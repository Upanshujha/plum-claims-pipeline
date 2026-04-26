"""Stage 10: Rejection Explainer (LLM, REJECTED-only).

Why this stage exists
---------------------
Approved members glance at their decision and move on. Rejected members
read the message line by line, sometimes multiple times. The static
templates in synthesizer.py work for one rejection reason at a time, but
they get robotic when two or three reasons fire together (e.g.
PER_CLAIM_EXCEEDED + WAITING_PERIOD on the same claim). A short, humane,
LLM-written explanation reduces support tickets and rejection-driven
churn — the single largest customer-experience problem in Indian health
insurance retention numbers.

Design rules this stage holds itself to
---------------------------------------
1. **Runs only on REJECTED.** Approved/Partial/Manual-Review never call
   the LLM here. That keeps tokens spent strictly proportional to value.
2. **Never in the rupee-math path.** The rules engine has already
   produced the decision, the rejection reasons and the calc breakdown
   before this stage runs. This stage cannot change any number.
3. **Validated JSON only.** The model is asked to return a strict
   schema. Anything else → fallback (the synthesizer keeps the existing
   static template).
4. **Network/key/parse failures are silent.** A failure here returns
   None and the pipeline continues unaffected. The static template wins
   by default.
5. **No PII in the prompt beyond what the member already has.** We pass
   the rejection reasons, the calc breakdown labels, the treatment
   category, the treatment date and the claimed amount. We do not pass
   the member's full claims history or other claims on the policy.

Provider: Groq (free tier, OpenAI-compatible API). Model:
``llama-3.1-8b-instant`` — fast (sub-second latency), cheap, and good
enough for 3-sentence templated explanations. The provider is read from
``GROQ_API_KEY``; if unset, the stage no-ops.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Tunables — kept small so a misbehaving LLM can't hold up a claim.
_MODEL = os.environ.get("GROQ_REJECTION_MODEL", "llama-3.1-8b-instant")
_TIMEOUT_SECONDS = float(os.environ.get("GROQ_TIMEOUT", "8"))
_MAX_TOKENS = 220


@dataclass
class RejectionExplanation:
    """Strict, validated output of this stage.

    Three short member-facing lines — what we found, why it can't be
    paid right now, what they can do next — plus the model name we used,
    so an ops reviewer can audit which version produced any given
    explanation.
    """
    headline: str
    reason: str
    next_steps: str
    model: str

    def to_user_message(self) -> str:
        """Concat into the single ``user_message`` string the API
        already returns. Keeps the pipeline contract intact: callers
        downstream see one string, the same as before."""
        return f"{self.headline} {self.reason} {self.next_steps}".strip()


def explain(
    rejection_reasons: list[str],
    calc_breakdown: list,
    claim_category: str,
    treatment_date: Any,
    claimed_amount: int,
    fallback_message: str,
) -> Optional[RejectionExplanation]:
    """Ask the LLM for a humane explanation. Return None on any
    failure — the caller (synthesizer) will use the existing static
    template instead.

    Inputs are intentionally narrow: only the fields a member would
    already see on their own decision page. No member name, no other
    claims, no policy ID. That keeps the prompt PII-light and means
    every call is independently auditable from the trace.
    """
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        # Not an error — just a deployment without LLM credentials.
        # Pipeline continues, static template wins.
        logger.debug("GROQ_API_KEY not set; skipping rejection explainer.")
        return None

    try:
        # Imported lazily so a deployment without the SDK still boots.
        from groq import Groq
    except ImportError:
        logger.warning("groq SDK not installed; skipping rejection explainer.")
        return None

    prompt = _build_prompt(
        rejection_reasons=rejection_reasons,
        calc_breakdown=calc_breakdown,
        claim_category=claim_category,
        treatment_date=treatment_date,
        claimed_amount=claimed_amount,
        fallback_message=fallback_message,
    )

    try:
        client = Groq(api_key=api_key, timeout=_TIMEOUT_SECONDS)
        completion = client.chat.completions.create(
            model=_MODEL,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.2,
            max_tokens=_MAX_TOKENS,
        )
    except Exception as e:  # network, auth, rate-limit, anything
        logger.warning("rejection explainer LLM call failed: %s", e)
        return None

    raw = ""
    try:
        raw = completion.choices[0].message.content or ""
        return _parse_and_validate(raw, model=_MODEL)
    except Exception as e:
        # Malformed JSON, missing keys, unexpected shape — never crash.
        logger.warning("rejection explainer returned unusable output (%s): %r",
                       e, raw[:200])
        return None


# ----------------------------- prompt builders -------------------------------

_SYSTEM_PROMPT = (
    "You are the customer-experience voice of a health-insurance claims "
    "team in India. A member's claim has just been rejected. Your job is "
    "to explain the rejection in three short sentences a non-insurance "
    "person can understand, while staying factually exact about the "
    "reasons and amounts you are given. Be empathetic, not apologetic. "
    "Be specific, not generic. Do not invent rules, dates, or amounts "
    "that are not in the input. Do not promise that the claim can be "
    "appealed unless the input lists a clear next step. Always return a "
    "single JSON object with exactly these keys and nothing else:\n"
    '  {"headline": str, "reason": str, "next_steps": str}\n'
    "Each value is one sentence, in plain English, member-facing. The "
    "headline names what was decided in human terms (do not use the "
    "literal word REJECTED). The reason explains why, citing the "
    "specific rule(s). The next_steps tell the member what they can "
    "actually do — re-submit with pre-auth, wait until a date, split a "
    "claim, or contact support if nothing else applies."
)


def _build_prompt(
    *,
    rejection_reasons: list[str],
    calc_breakdown: list,
    claim_category: str,
    treatment_date: Any,
    claimed_amount: int,
    fallback_message: str,
) -> str:
    # Pass the calc breakdown as labels + amounts so the LLM can see
    # what was tried — useful for compound rejections (eg sub-limit hit
    # AND per-claim cap hit). Object format depends on whether caller
    # passed CalcStep dataclasses or already-serialized dicts.
    steps_for_prompt = []
    for s in calc_breakdown or []:
        if hasattr(s, "label"):
            steps_for_prompt.append({
                "label": s.label,
                "before": s.amount_before,
                "after": s.amount_after,
                "rule": s.rule,
            })
        elif isinstance(s, dict):
            steps_for_prompt.append({
                "label": s.get("label"),
                "before": s.get("amount_before"),
                "after": s.get("amount_after"),
                "rule": s.get("rule"),
            })

    payload = {
        "claim_category": claim_category,
        "treatment_date": str(treatment_date) if treatment_date else None,
        "claimed_amount_inr": claimed_amount,
        "rejection_reason_codes": rejection_reasons,
        "calc_breakdown": steps_for_prompt,
        "static_template_we_will_show_if_you_fail": fallback_message,
    }
    return (
        "Rewrite the rejection below into the JSON object described in "
        "your system prompt. Use rupees (₹) for currency, format like "
        "₹1,500. Do not contradict the rejection_reason_codes. Keep each "
        "sentence under 30 words.\n\n"
        f"INPUT:\n{json.dumps(payload, ensure_ascii=False, indent=2)}"
    )


# ----------------------------- output validation -----------------------------

_REQUIRED_KEYS = {"headline", "reason", "next_steps"}


def _parse_and_validate(raw: str, model: str) -> RejectionExplanation:
    """Strict JSON validator. Raises on any deviation.

    We accept exactly the three keys the prompt asked for. Extra keys
    are ignored (some models echo the input back). All three must be
    non-empty strings. Anything else and we throw → caller returns
    None → static template wins.
    """
    obj = json.loads(raw)
    if not isinstance(obj, dict):
        raise ValueError("model returned non-object JSON")
    missing = _REQUIRED_KEYS - obj.keys()
    if missing:
        raise ValueError(f"missing required keys: {sorted(missing)}")
    for k in _REQUIRED_KEYS:
        v = obj.get(k)
        if not isinstance(v, str) or not v.strip():
            raise ValueError(f"key {k!r} must be a non-empty string")

    return RejectionExplanation(
        headline=obj["headline"].strip(),
        reason=obj["reason"].strip(),
        next_steps=obj["next_steps"].strip(),
        model=model,
    )
