# Demo script — 8–12 minute video

## Prep

- Start the app: `python -m flask --app app.main run --port 5000`
- Open http://localhost:5000 full-screen
- Have `docs/ARCHITECTURE.md` open in a second window for a quick architecture flash

## Running order

### Minutes 0–1: Context
- What Plum does; what this assignment is.
- One sentence: "A nine-stage pipeline with a deterministic rules engine and agentic document processing, 12 of 12 test cases passing."
- Show the README summary screen.

### Minutes 1–3: TC001 — wrong document, stopped early
- Click `TC001 — Wrong Document Uploaded` in the sidebar.
- Hit **Process Claim**.
- Point out: decision is **STOPPED** (not REJECTED), message names both what was uploaded and what's missing: "You uploaded 2 prescriptions, but for a consultation claim we also need a hospital bill…".
- Show the trace: stages 1–3 ran, stages 4–9 were skipped. Zero LLM parsing tokens were spent.
- Takeaway: "Specific, actionable messages are part of the acceptance criteria. And catching document problems before the expensive stages is how this keeps margins sane at scale."

### Minutes 3–6: TC004 — clean consultation, full approval
- Load TC004, process.
- Walk down the trace from top: intake PASS, classifier PASS, sufficiency PASS, parser PASS, quality PASS, consistency PASS, rules_engine PASS.
- Open the Calculation Breakdown table: raw ₹1,500 → 10% consultation co-pay → final ₹1,350.
- Open the reasons: "10% co-pay applied."
- Takeaway: "Every rupee in the final amount is traceable to a named rule. No black-box decisions."

### Minutes 6–8: TC010 — network discount ordering
- Load TC010, process.
- Show the calculation breakdown:
  - raw ₹4,500
  - network_discount (20%) → ₹3,600
  - copay (10%) → ₹3,240
- Point out the order: discount first, co-pay on the discounted amount. "If this ran in the other order the answer would be off by ₹90. The test case locks this ordering in."
- Takeaway: "Observability isn't just for debugging — it's what makes disputes tractable."

### Minutes 8–10: TC011 — graceful degradation
- Load TC011, process.
- Show: decision is **APPROVED**, confidence is **0.70** (down from the usual 0.95), skipped_stages shows `["consistency"]`, and `manual_review_recommended: true`.
- Scroll the trace: consistency stage is marked **FAILED** in red, but the pipeline continued past it and produced a decision.
- Takeaway: "Components will fail in production. A system that crashes on component failure doesn't pass this test case. This one limps to a decision, surfaces the failure, and lowers confidence so ops can catch it."

### Minutes 10–11: One thing I'm proud of, one I'd change
- **Proud of:** The split between a deterministic Rules Engine and an agentic Document Parser. Exclusions, sub-limits, the network-discount-before-copay order — none of that is something I want an LLM near. But document classification and field extraction genuinely benefit from vision models. Drawing that line cleanly kept the code debuggable.
- **Would change:** Persistence. The Flask app keeps processed claims in a dict. With more time I'd put Postgres behind the API and wire document blobs to S3, so the reviewer UI could actually show historical claims and not lose them on restart.

### Minute 11–12: Wrap
- Run `python eval/run_eval.py` on camera — 12/12 PASS in about a second.
- Link the repo.
- "Happy to walk through the rules engine stage by stage in the review."
