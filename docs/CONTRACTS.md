# Component Contracts

Each stage below is defined by its inputs, outputs, and the errors it can raise. Precise enough that another engineer could reimplement any single one of these from the contract alone.

All input/output shapes are defined in `app/models.py` as dataclasses.

---

## 1. Intake — `app/stages/intake.py`

**Owner:** Python, synchronous. No LLM.

**Input:**
- `submission: ClaimSubmission` — member_id, policy_id, claim_category, treatment_date, claimed_amount, documents, hospital_name, ytd_claims_amount, claims_history.
- `policy: Policy`

**Output (dict):**
- `member: dict` — roster entry for this member.
- `primary_member_id: str` — resolves dependents to their employee.
- `warnings: list[str]` — non-blocking notes (e.g. `"treatment_date outside policy validity window"`).
- `status: StageStatus.PASS`

**Errors (raised as `IntakeError` with a `code`):**
- `POLICY_MISMATCH`
- `MEMBER_NOT_FOUND`
- `AMOUNT_BELOW_MINIMUM`
- `SUBMISSION_WINDOW_EXCEEDED` *(not enforced in prototype — see note in code)*
- `INVALID_CATEGORY` *(raised by Pydantic-style enum validation)*

**Notes:** Runs first; never calls an LLM. Nothing downstream spends tokens until intake passes.

---

## 2. Document Classifier — `app/stages/classifier.py`

**Owner:** LLM agent (vision) in production; fixture mode in the prototype.

**Input:**
- `docs: list[UploadedDoc]`

**Output:**
- `list[DocClassification]` — one per document with `file_id`, `predicted_type: DocType`, `confidence: float`, `reasons: list[str]`.

**Errors:**
- None raised. On timeout or parse failure, individual docs are returned with `predicted_type = UNKNOWN` and `confidence = 0.0`. Downstream stages interpret UNKNOWN appropriately.

**Notes:** Closed-set classification over `DocType` enum. `MODE = "fixture"` reads `actual_type` from the input; `MODE = "vision"` would call GPT-4o.

---

## 3. Sufficiency Gate — `app/stages/sufficiency.py`

**Owner:** Python. A small LLM optional for phrasing the user message; prototype uses a deterministic template.

**Input:**
- `category: ClaimCategory`
- `classifications: list[DocClassification]`
- `policy: Policy`

**Output (dict):**
- `status: StageStatus.PASS | STOP`
- `missing: list[str]` — required doc types not present
- `wrong: list[str]` — types uploaded that aren't in required or optional
- `user_message: str` — single sentence naming the specific types

**Errors:** None. This stage always PASSes or STOPs.

**Notes:**
- Substitution rules live here. DIAGNOSTIC accepts HOSPITAL_BILL as a stand-in for LAB_REPORT (imaging claims produce a bill but not a lab report) — see TC007.
- Message never generic. TC001 requires it name both the uploaded and the required types.

---

## 4. Document Parser — `app/stages/parser.py`

**Owner:** Per-doc LangChain agent in production; fixture mode in prototype.

**Input:**
- `docs: list[UploadedDoc]`
- `classifications: list[DocClassification]`

**Output:**
- `list[ParsedDoc]` — each carries extracted fields, `field_confidence: dict[str, float]`, and `quality: GOOD | DEGRADED | UNREADABLE`.

**Errors:**
- `PARSE_FAILED` — returns a `ParsedDoc` with `quality=UNREADABLE` and empty fields instead of raising.
- `MODEL_TIMEOUT` — same degraded-return behaviour.

**Notes:** Fan-out in production via `asyncio.gather`. Prototype runs sequentially in fixture mode for deterministic tests.

---

## 5. Quality Gate — `app/stages/quality.py`

**Owner:** Python.

**Input:**
- `parsed_docs: list[ParsedDoc]`

**Output (dict):**
- `status: StageStatus.PASS | ASK_REUPLOAD`
- `reupload_targets: list[tuple[file_id, doc_type, confidence]]`
- `user_message: str` — names the specific file

**Errors:** None.

**Notes:** A single unreadable document pauses the claim rather than rejecting it. TC002 acceptance test.

---

## 6. Cross-Doc Consistency — `app/stages/consistency.py`

**Owner:** Python, optional LLM for fuzzy name matching.

**Input:**
- `parsed_docs: list[ParsedDoc]`

**Output (dict):**
- `status: StageStatus.PASS | STOP`
- `mismatches: list[Mismatch]` — `{field_name, values_found, files_involved}`
- `user_message: str`

**Errors:** None. But this stage is **skippable** — if it throws, the orchestrator adds it to `skipped_stages` and continues.

**Notes:** Patient names are normalized (lowercased, whitespace collapsed). For short/ambiguous names an LLM tie-breaker is the planned extension.

---

## 7. Rules Engine — `app/stages/rules_engine.py`

**Owner:** Pure Python. The only stage that does rupee math. **No LLM.**

**Input:**
- `submission: ClaimSubmission`
- `parsed_docs: list[ParsedDoc]`
- `policy: Policy`
- `member: dict`

**Output (`RulesResult` object):**
- `decision: Decision` — APPROVED | PARTIAL | REJECTED
- `approved_amount: int` (rupees)
- `reasons: list[str]`
- `rejection_reasons: list[str]` (e.g. `["WAITING_PERIOD"]`, `["PER_CLAIM_EXCEEDED"]`)
- `calc_steps: list[CalcStep]` — full rupee breakdown
- `user_message: str` — only set for REJECTED cases

**Errors:**
- `POLICY_CONFIG_ERROR` — raised at policy-load time if config is malformed. Never at request time.

**Notes:** Order of operations is fixed and documented in the source. See `docs/ARCHITECTURE.md` for why each test case locks in a specific step order.

---

## 8. Fraud / Anomaly — `app/stages/fraud.py`

**Owner:** Python.

**Input:**
- `submission: ClaimSubmission`
- `policy: Policy`

**Output (dict):**
- `score: float` — in `[0, 1]`
- `signals: list[FraudSignal]` — `{code, severity, description, value}`
- `forces_manual_review: bool`

**Errors:** None.

**Notes:** Fraud alone never rejects. At worst it sets `forces_manual_review=True` and the synthesizer escalates the final decision to MANUAL_REVIEW.

---

## 9. Decision Synthesizer — `app/stages/synthesizer.py`

**Owner:** Python.

**Input:**
- `claim_id: str`
- `rules_result: RulesResult | None`
- `fraud_result: dict | None`
- `base_confidence: float`
- `skipped_stages: list[str]`
- `user_message_override: str | None`
- `trace: list[StageTrace]`

**Output:**
- `ClaimDecision` — the complete response: `decision`, `approved_amount`, `confidence`, `reasons`, `rejection_reasons`, `user_message`, `calc_breakdown`, `fraud_signals`, `skipped_stages`, `manual_review_recommended`, `trace`.

**Errors:** None.

**Notes:** Confidence starts at 0.95, drops by 0.25 per skipped stage, floors at 0.10. TC011 exercises the degraded path (consistency skipped → 0.70 confidence, `manual_review_recommended=True`).
