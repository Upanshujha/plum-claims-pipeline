# Architecture

## Why a pipeline

A claim submission is four stacked decisions, each one gating the next:

1. Are the right documents here, and do they all belong to the same person?
2. What is actually written on these documents?
3. Does the policy cover this treatment for this member on this date?
4. If yes, how much do we owe — after sub-limits, network discount, co-pay, YTD usage, and the per-claim cap?

Each step has a different shape. Step 1 has to be aggressive — if the wrong document is attached the system should stop before spending a single token on a vision call. Step 2 has to be forgiving — Indian medical documents are messy. Step 3 has to be deterministic so a reviewer six weeks later can explain why a claim got its decision. Step 4 is arithmetic that has to land to the rupee.

That mix is what pushed the design toward small single-purpose components in a fixed order instead of one large LLM agent that plans and acts.

## The nine stages

| # | Stage | Type | Failure mode |
|---|-------|------|--------------|
| 1 | Intake | Python | Raises `IntakeError`, pipeline stops with specific message |
| 2 | Document Classifier | LLM agent (vision) | Falls back to filename heuristic |
| 3 | Sufficiency Gate | Python + small LLM | Stops pipeline with named message; never raises |
| 4 | Document Parser | LLM agent, per-doc fan-out | Returns `quality=UNREADABLE` instead of raising |
| 5 | Quality Gate | Python | Pauses (ASK_REUPLOAD), never rejects |
| 6 | Cross-Doc Consistency | Python + small LLM | Skippable — marked FAILED, pipeline continues |
| 7 | Rules Engine | Pure Python | The only step that raises on malformed policy; never at request time |
| 8 | Fraud / Anomaly | Python | Never raises; at worst adds a signal |
| 9 | Decision Synthesizer | Python | Never raises; always returns a `ClaimDecision` |

## Order of financial operations (locked)

Exclusions → waiting period → pre-auth → line-item exclusions → sub-limits → network discount → co-pay → per-claim cap → YTD / family floater.

The ordering is not cosmetic. Two test cases lock it in:
- **TC010** proves network discount must be applied before co-pay (₹4,500 × 0.8 × 0.9 = ₹3,240, not ₹4,500 × 0.9 × 0.8, which would give the same number but fails the assignment's ordering requirement).
- **TC012** proves exclusions must be checked before waiting periods (obesity is both an exclusion and a waiting-period condition; the rejection reason must be `EXCLUDED_CONDITION`).

## Policy interpretations

Every non-obvious policy reading is commented inline in `app/stages/rules_engine.py`. The three that matter most:

- **Consultation sub-limit (₹2,000) caps the consultation *line item*, not the whole bill.** This is required by TC010 where a ₹4,500 consultation bill is approved at ₹3,240. If the sub-limit applied to the whole bill, the bill would cap at ₹2,000 and never reach ₹3,240.
- **Per-claim limit (₹5,000) applies only to categories where `sub_limit ≤ per_claim_limit`.** Those are the categories where per-claim is the binding constraint (CONSULTATION, VISION). For DENTAL (sub-limit ₹10,000), PHARMACY (₹15,000), DIAGNOSTIC (₹10,000), ALTERNATIVE_MEDICINE (₹8,000), the category sub-limit is the binding cap and per-claim is redundant. This lets TC006 approve ₹8,000 on a dental claim.
- **Exclusions are checked before waiting periods.** An excluded condition is permanently out of scope, not just gated by time.

## Trace shape

Every stage appends a `StageTrace` entry:

```python
{
  "stage": "rules_engine",
  "status": "PASS",
  "latency_ms": 2,
  "warnings": [],
  "payload": {
    "decision": "APPROVED",
    "approved_amount": 3240,
    "calc_steps": [
      {"label": "raw_claim_amount", "amount_before": 4500, "amount_after": 4500, "rule": "..."},
      {"label": "network_discount", "amount_before": 4500, "amount_after": 3600, "rule": "Network discount 20%"},
      {"label": "copay",            "amount_before": 3600, "amount_after": 3240, "rule": "10% consultation co-pay"}
    ]
  }
}
```

A reviewer can open any claim in the UI and reconstruct exactly what happened at each stage, including which stage took how long.

## What changes at 10× load

- **Async task queue.** POST /api/claims should enqueue and return immediately. Celery or SQS consumers run the pipeline.
- **Batched vision calls.** Parser currently fans out per-document. At scale, batch N documents of the same type into a single structured call.
- **Fast-lane router.** Before the pipeline: if claim < ₹2,000, network hospital, clean docs, no fraud signals — run a shorter path. Likely 30–40% of claims qualify.
- **Compile the policy.** `policy_terms.json` is reloaded every request via the `Policy` wrapper. Past ~100 policies this becomes a per-tenant Python object graph.
- **Semantic fraud.** Embed every historical claim into a vector store. New claim gets its top-k neighbours; tight clusters across different members are suspicious.
- **Per-stage SLOs.** Right now the trace only records latency. Add alerts when p95 for stage N breaches a per-stage budget.
- **Multi-tenancy.** Policies move from JSON to versioned Postgres rows; members move from JSON to a members table keyed by policy_id.
- **Human review capacity.** MANUAL_REVIEW queue has to be designed at scale, not just a label. SLA-aware routing, reviewer-productivity metrics.

## Limitations in the current prototype

- Document classifier and parser run in **fixture mode** (read `actual_type` and `content` directly from test input). The vision-LLM path is a function boundary but not wired. This is the single biggest build-out gap; the rest of the pipeline is real.
- No persistence. The Flask app keeps processed claims in an in-memory dict.
- No authentication.
- No retries / timeouts around the LLM calls (because there are no LLM calls in fixture mode).
- English-only document extraction.
- Heuristic fraud only — no trained model.
