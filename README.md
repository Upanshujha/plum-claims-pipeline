# Plum Claims Processing System

A ten-stage pipeline that takes a health-insurance claim submission (member, treatment, amount, documents) and produces an explainable decision: APPROVED, PARTIAL, REJECTED, or MANUAL_REVIEW.

Stages 1–9 cover everything the brief asked for. Stage 10 — the **Rejection Explainer** — is something I added on top: when a claim is rejected, a Groq-hosted LLM rewrites the rejection message into three short, humane sentences. Every other stage is pure Python. The LLM never touches the rupee math, never changes a decision, and silently falls back to the static template on any failure.

Built for the Plum AI Engineer take-home.

## Current status

**12 of 12 test cases pass end-to-end** against the provided `test_cases.json`. Run `python eval/run_eval.py` to reproduce.

```
TC001  PASS  None  (stopped before decision — wrong document)
TC002  PASS  None  (ASK_REUPLOAD — unreadable pharmacy bill)
TC003  PASS  None  (stopped — documents for different patients)
TC004  PASS  APPROVED  ₹1,350
TC005  PASS  REJECTED  (WAITING_PERIOD — diabetes)
TC006  PASS  PARTIAL   ₹8,000  (dental cosmetic line dropped)
TC007  PASS  REJECTED  (PRE_AUTH_MISSING — MRI)
TC008  PASS  REJECTED  (PER_CLAIM_EXCEEDED)
TC009  PASS  MANUAL_REVIEW  (same-day fraud signal)
TC010  PASS  APPROVED  ₹3,240  (network discount before co-pay)
TC011  PASS  APPROVED  ₹4,000  (graceful degradation, confidence 0.70)
TC012  PASS  REJECTED  (EXCLUDED_CONDITION — obesity)
```

## Quick start

```bash
# 1. create a virtualenv
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# 2. install
pip install -r requirements.txt

# 3. run the eval — proves the pipeline works against all 12 test cases
python eval/run_eval.py

# 4. start the web UI
python -m flask --app app.main run --port 5000
# open http://localhost:5000
```

The UI lets you pick any test case from the sidebar, submit it, and see the decision, calculation breakdown, fraud signals, and full stage-by-stage trace.

## Run the tests

```bash
# with pytest
pytest -v

# or without pytest
python -m unittest discover tests
```

## Project layout

```
plum_pipeline/
├── app/
│   ├── main.py                # Flask app: POST /api/claims + UI
│   ├── pipeline.py            # 9-stage orchestrator
│   ├── policy.py              # Typed wrapper over policy_terms.json
│   ├── models.py              # Dataclass contracts for every stage
│   └── stages/
│       ├── intake.py          # 1. deterministic gate — no LLM spend
│       ├── classifier.py      # 2. doc-type classification (fixture or vision)
│       ├── sufficiency.py     # 3. required-docs check + user message
│       ├── parser.py          # 4. per-doc structured extraction
│       ├── quality.py         # 5. unreadable → ASK_REUPLOAD (not REJECT)
│       ├── consistency.py     # 6. cross-doc patient-name agreement
│       ├── rules_engine.py    # 7. pure-Python rupee math, the load-bearer
│       ├── fraud.py           # 8. heuristic signals (same-day, high-value)
│       ├── synthesizer.py     # 9. final decision + full trace
│       └── rejection_explainer.py  # 10. LLM rewrite of REJECTED messages (mine)
├── tests/                     # pytest + integration coverage
├── eval/run_eval.py           # Runs all 12 test cases, writes eval_report.md
├── ui/index.html              # Minimal reviewer UI
├── policy_terms.json          # The policy configuration
├── test_cases.json            # The 12 test cases
├── requirements.txt
└── README.md
```

## The Rejection Explainer (stage 10, beyond the brief)

The brief asks for `APPROVED / PARTIAL / REJECTED / MANUAL_REVIEW` with a reason and a confidence. The static templates I wrote in `synthesizer.py` cover that. But static templates start to read robotic the moment a rejection has more than one cause, and rejection-driven churn is a real, measurable problem in Indian health insurance — approved members glance at their decision and move on, rejected members read it line by line.

Stage 10 only runs when the rules engine has already decided **REJECTED**. It hands the model the rejection codes, the calc breakdown, the claim category, the date and the claimed amount, and asks for a single JSON object with three short sentences: what was decided, why, and what the member can do next. The output is validated against a fixed schema; anything else and the stage returns `None` and the synthesizer's static template is used instead. The rules engine is never touched. No rupee math goes near the LLM.

To run the live LLM path locally:

```bash
cp .env.example .env
# Edit .env and paste your free Groq key from https://console.groq.com
# (the key starts with gsk_)
```

Without a key, every test still passes — the stage no-ops, the static templates win, and the trace records `rejection_explainer:SKIPPED` so you can see the fallback fired. Two new tests in `tests/test_all.py` lock in both the success path and the malformed-output path, with the network mocked.

## Design choices worth calling out

- **Pipeline, not an agent-swarm.** Every step has a predictable output shape; a free-form tool-calling agent would re-discover the routing on every claim and sacrifice observability. The rules engine in particular is pure Python — no LLM anywhere in the money-calculation path.
- **Fixture mode for document AI.** Document classifier and parser ship in fixture mode so the prototype runs deterministically against the provided test fixtures. There is a clean boundary (`MODE = "fixture" | "vision"` at the top of each stage file) where a real GPT-4o vision integration would plug in. The function signatures are identical.
- **Stdlib over Pydantic.** Uses `dataclasses` + a custom `to_dict` serializer instead of Pydantic v2. This keeps the dependency tree tiny (Flask + Jinja2 is all you need) and makes the code more obvious. Porting to Pydantic is a mechanical transform if runtime validation is needed.
- **Skippable stages.** The consistency stage is allowed to fail and the pipeline continues with a noted `skipped_stages` entry and reduced confidence. TC011 exercises this end-to-end.
- **Policy interpretation choices documented in code.** The non-obvious readings (per-claim limit binds only when sub-limit ≤ per-claim; consultation sub-limit applies to the consultation line item, not the whole bill; exclusions checked before waiting periods) are all commented inline in `rules_engine.py`. These interpretations were locked in by running the test cases backwards from their expected outputs — see `docs/POLICY_INTERPRETATION.md` for the reasoning trail.

## What to build next (known gaps)

- Wire in a real GPT-4o vision call behind the `MODE = "vision"` switch in classifier.py and parser.py. The fan-out + retry wrapper is already in place; just needs the LangChain wrapper.
- Persistence. Claims are currently stored in-memory by the Flask app. Swap `CLAIMS` dict for Postgres + S3 (document blobs) when moving past the prototype.
- Background queue. The API is synchronous. At volume, POST should enqueue the claim and return a claim_id; a worker runs the pipeline and writes the result.
- Authentication. The API has none. A shared-secret check on POST is the minimum next step.

## Demo

A short walkthrough is in `docs/DEMO_SCRIPT.md`. Recommended narrative:

1. TC001 — wrong document, specific user-facing error (stopped at stage 3, zero LLM tokens spent).
2. TC004 — clean consultation, full approval, walk through the trace viewer.
3. TC010 — discount-before-copay, calculation breakdown on screen.
4. One decision you're proud of, one you'd change given more time.
