# Trade-offs made on purpose

The assignment timeline is 2–3 days. Some things had to go. What I cut and why:

### Document AI — fixture mode only
The Document Classifier and Parser ship with `MODE = "fixture"` and read `actual_type` / `content` directly from the test input. The function signatures and error contracts are identical to what a real GPT-4o vision integration would need; the `MODE = "vision"` branch is where that wiring goes. This was deliberate: it lets the rest of the pipeline (the rules engine, fraud detection, orchestration, trace) run deterministically and be tested thoroughly. In a 2–3 day build, getting the business-logic right end-to-end is more valuable than a half-working vision call.

### No trained fraud model
Heuristic rules only, reading thresholds from `policy_terms.json`. With real claims history I'd add an anomaly model — per-member claim-amount distribution, time-between-claims, provider repetition — but on 12 synthetic test cases a trained model would be theatre.

### No OCR fallback
In production, GPT-4o vision handles the sample documents well enough that a Tesseract/PaddleOCR fallback would only matter for cost optimisation. The prototype doesn't need it. The place to add it is before the Parser stage, gated by a confidence threshold on the classifier's output.

### English-only extraction
The sample documents guide mentions Hindi/Tamil/Telugu mixed into Indian medical documents. The plan for those is the guide's own recommendation: extract what we can in English, flag regional fields as unextracted. I didn't build multilingual extraction.

### Minimal UI
Single-page HTML, inline CSS/JS, no build step. A reviewer can load any of the 12 test cases, submit it, and see the decision + trace. A proper reviewer dashboard (side-by-side doc preview, inline trace annotations, override buttons with audit) is the first thing I'd add with more time. This was the conscious cut — the backend is where the evaluation weight is.

### No authentication
The API is unauthenticated. Shared-secret header is a 10-line change; JWT is a day. Neither belongs in a 2–3 day prototype.

### Synchronous request handling
`POST /api/claims` runs the full pipeline synchronously. At Plum's scale (10M lives by 2030) this is the single biggest thing that would have to change — enqueue and return immediately, have workers run the pipeline, frontend polls. But adding the queue now would quadruple the setup effort without changing the logic being evaluated.

### Stdlib over Pydantic
Used `@dataclass` + a small `to_dict` serializer instead of Pydantic v2. Keeps the dependency tree to Flask + Jinja2. The port to Pydantic is mechanical if runtime validation is needed — every class would add `(BaseModel)` inheritance and the `.from_dict` classmethods become Pydantic's native parsing.

### No persistence
Claims are held in an in-memory dict in the Flask app. Postgres + S3 is noted in the architecture doc as the natural next step. Adding it without first agreeing on a schema is premature.

### No real SKU for the LLM provider
Prompts for the classifier and parser are notional — `vision_classify` etc. are placeholder function boundaries. When wiring to a real provider these would become named LangChain chains with pinned versions.

---

## What I'd change given another day

- Real vision integration for at least the classifier, so TC001/TC003 are exercised against actual model output rather than fixtures.
- Persistence layer — even SQLite would be enough to demonstrate the trace-replay story.
- A second UI view: a reviewer-override screen where an ops person can flip a MANUAL_REVIEW case to APPROVED or REJECTED with a required comment, writing the decision back to the trace.
- The eval harness already runs on every commit to main at my current job. I'd add CI here too — GitHub Actions running `pytest` + `python eval/run_eval.py` with the pass count as a required check.
