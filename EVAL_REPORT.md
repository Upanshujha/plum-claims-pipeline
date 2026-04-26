# Eval Report — 12 Test Cases

Generated: 2026-04-24T13:32:02.619623Z

Summary: **12/12 matched**


## Summary Table

| Case | Expected | Actual | Amount | Match |
|------|----------|--------|--------|-------|
| TC001 | STOP / ASK_REUPLOAD | — | — | ✅ |
| TC002 | STOP / ASK_REUPLOAD | — | — | ✅ |
| TC003 | STOP / ASK_REUPLOAD | — | — | ✅ |
| TC004 | APPROVED | APPROVED | ₹1,350 / ₹1,350 expected | ✅ |
| TC005 | REJECTED | REJECTED | — | ✅ |
| TC006 | PARTIAL | PARTIAL | ₹8,000 / ₹8,000 expected | ✅ |
| TC007 | REJECTED | REJECTED | — | ✅ |
| TC008 | REJECTED | REJECTED | — | ✅ |
| TC009 | MANUAL_REVIEW | MANUAL_REVIEW | ₹4,320 | ✅ |
| TC010 | APPROVED | APPROVED | ₹3,240 / ₹3,240 expected | ✅ |
| TC011 | APPROVED | APPROVED | ₹4,000 | ✅ |
| TC012 | REJECTED | REJECTED | — | ✅ |

## Per-case detail

### TC001 — Wrong Document Uploaded
- Expected: `{'decision': None, 'system_must': ['Stop before making any claim decision', 'Tell the member specifically what document type was uploaded and what is needed instead', 'Not return a generic error — the message must name the uploaded document type and the required document type']}`
- Actual decision: **None** (amount ₹0, confidence 0.95)
- User message: _You uploaded 2 prescriptions, but for a consultation claim we also need a hospital bill. Please add the missing document(s) and resubmit._
- Trace: `intake:PASS → classifier:PASS → sufficiency:STOP`
- Match: **True** — stopped before decision, as required

### TC002 — Unreadable Document
- Expected: `{'decision': None, 'system_must': ['Identify that the pharmacy bill cannot be read', 'Ask the member to re-upload that specific document', 'Not reject the claim outright']}`
- Actual decision: **None** (amount ₹0, confidence 0.95)
- User message: _We received your claim, but the pharmacy bill (file F004) was too unclear to read (confidence 0.12). Please re-upload a clearer photo of just that document — you don't need to resend the others._
- Trace: `intake:PASS → classifier:PASS → sufficiency:PASS → parser:PASS → quality:ASK_REUPLOAD`
- Match: **True** — stopped before decision, as required

### TC003 — Documents Belong to Different Patients
- Expected: `{'decision': None, 'system_must': ['Detect that the documents belong to different people', 'Surface this to the member with the specific names found on each document', 'Not proceed to a claim decision']}`
- Actual decision: **None** (amount ₹0, confidence 0.95)
- User message: _Your documents appear to be for different people — we found "Arjun Mehta" (file F005) and "Rajesh Kumar" (file F006). Both documents need to be for the same person. Please check and re-upload._
- Trace: `intake:PASS → classifier:PASS → sufficiency:PASS → parser:PASS → quality:PASS → consistency:STOP`
- Match: **True** — stopped before decision, as required

### TC004 — Clean Consultation — Full Approval
- Expected: `{'decision': 'APPROVED', 'approved_amount': 1350, 'notes': '10% co-pay applied on consultation category (₹150 deducted)', 'confidence_score': 'above 0.85'}`
- Actual decision: **APPROVED** (amount ₹1,350, confidence 0.95)
- User message: _Your claim has been approved for ₹1,350. Funds will be disbursed within 5 working days._
- Calc breakdown:
  - `raw_claim_amount`: ₹1,500 → ₹1,500 (starting amount after line-item exclusions)
  - `copay`: ₹1,500 → ₹1,350 (10% consultation co-pay)
- Trace: `intake:PASS → classifier:PASS → sufficiency:PASS → parser:PASS → quality:PASS → consistency:PASS → rules_engine:PASS → fraud:PASS → synthesizer:PASS`
- Match: **True** — decision and amount match expected

### TC005 — Waiting Period — Diabetes
- Expected: `{'decision': 'REJECTED', 'rejection_reasons': ['WAITING_PERIOD'], 'system_must': ['State the date from which the member will be eligible for diabetes-related claims']}`
- Actual decision: **REJECTED** (amount ₹0, confidence 0.95)
- Rejection reasons: ['WAITING_PERIOD']
- User message: _This claim is for type 2 diabetes mellitus treatment, which has a 90-day waiting period from your join date. You will be eligible for diabetes-related claims from 30-Nov-2024._
- Trace: `intake:PASS → classifier:PASS → sufficiency:PASS → parser:PASS → quality:PASS → consistency:PASS → rules_engine:PASS → fraud:PASS → synthesizer:PASS`
- Match: **True** — decision and amount match expected

### TC006 — Dental Partial Approval — Cosmetic Exclusion
- Expected: `{'decision': 'PARTIAL', 'approved_amount': 8000, 'system_must': ['Itemize which line items were approved and which were rejected', 'State the reason for each rejection at the line-item level']}`
- Actual decision: **PARTIAL** (amount ₹8,000, confidence 0.95)
- User message: _Your claim has been partially approved for ₹8,000. See the breakdown for details on which items were covered._
- Calc breakdown:
  - `raw_claim_amount`: ₹8,000 → ₹8,000 (starting amount after line-item exclusions)
- Trace: `intake:PASS → classifier:PASS → sufficiency:PASS → parser:PASS → quality:PASS → consistency:PASS → rules_engine:PASS → fraud:PASS → synthesizer:PASS`
- Match: **True** — decision and amount match expected

### TC007 — MRI Without Pre-Authorization
- Expected: `{'decision': 'REJECTED', 'rejection_reasons': ['PRE_AUTH_MISSING'], 'system_must': ['Explain that pre-authorization was required and not obtained', 'Tell the member what they should do to resubmit with pre-auth']}`
- Actual decision: **REJECTED** (amount ₹0, confidence 0.95)
- Rejection reasons: ['PRE_AUTH_MISSING']
- User message: _Pre-authorization is required for this test above ₹10,000. To resubmit, please request pre-auth via the member portal before the scan, attach the approval reference to your claim, and submit again._
- Trace: `intake:PASS → classifier:PASS → sufficiency:PASS → parser:PASS → quality:PASS → consistency:PASS → rules_engine:PASS → fraud:PASS → synthesizer:PASS`
- Match: **True** — decision and amount match expected

### TC008 — Per-Claim Limit Exceeded
- Expected: `{'decision': 'REJECTED', 'rejection_reasons': ['PER_CLAIM_EXCEEDED'], 'system_must': ['State the per-claim limit and the claimed amount clearly in the rejection message']}`
- Actual decision: **REJECTED** (amount ₹0, confidence 0.95)
- Rejection reasons: ['PER_CLAIM_EXCEEDED']
- User message: _Your claimed amount of ₹7,500 exceeds the per-claim limit of ₹5,000 for this policy. If the treatment genuinely cost more, please split it into separate claims by provider or by date._
- Calc breakdown:
  - `raw_claim_amount`: ₹7,500 → ₹7,500 (starting amount after line-item exclusions)
  - `copay`: ₹7,500 → ₹6,750 (10% consultation co-pay)
- Trace: `intake:PASS → classifier:PASS → sufficiency:PASS → parser:PASS → quality:PASS → consistency:PASS → rules_engine:PASS → fraud:PASS → synthesizer:PASS`
- Match: **True** — decision and amount match expected

### TC009 — Fraud Signal — Multiple Same-Day Claims
- Expected: `{'decision': 'MANUAL_REVIEW', 'system_must': ['Flag the unusual same-day claim pattern', 'Route to manual review rather than auto-rejecting', 'Include the specific signals that triggered the flag in the output']}`
- Actual decision: **MANUAL_REVIEW** (amount ₹4,320, confidence 0.95)
- User message: _Your claim has been flagged for manual review by our team because of unusual recent activity on your account. We'll get back to you within 48 hours._
- Calc breakdown:
  - `raw_claim_amount`: ₹4,800 → ₹4,800 (starting amount after line-item exclusions)
  - `copay`: ₹4,800 → ₹4,320 (10% consultation co-pay)
- Fraud signals: ['SAME_DAY_FREQUENCY']
- Trace: `intake:PASS → classifier:PASS → sufficiency:PASS → parser:PASS → quality:PASS → consistency:PASS → rules_engine:PASS → fraud:PASS → synthesizer:PASS`
- Match: **True** — decision and amount match expected

### TC010 — Network Hospital — Discount Applied
- Expected: `{'decision': 'APPROVED', 'approved_amount': 3240, 'notes': 'Network discount (20%) applied first on ₹4,500 = ₹3,600. Co-pay (10%) applied on ₹3,600 = ₹360 deducted. Final: ₹3,240.', 'system_must': ['Apply network discount before co-pay, not after', 'Show the breakdown of discount and co-pay in the decision output']}`
- Actual decision: **APPROVED** (amount ₹3,240, confidence 0.95)
- User message: _Your claim has been approved for ₹3,240. Funds will be disbursed within 5 working days._
- Calc breakdown:
  - `raw_claim_amount`: ₹4,500 → ₹4,500 (starting amount after line-item exclusions)
  - `network_discount`: ₹4,500 → ₹3,600 (Network discount 20%)
  - `copay`: ₹3,600 → ₹3,240 (10% consultation co-pay)
- Trace: `intake:PASS → classifier:PASS → sufficiency:PASS → parser:PASS → quality:PASS → consistency:PASS → rules_engine:PASS → fraud:PASS → synthesizer:PASS`
- Match: **True** — decision and amount match expected

### TC011 — Component Failure — Graceful Degradation
- Expected: `{'decision': 'APPROVED', 'system_must': ['Not crash or return a 500 error', 'Indicate in the output that a component failed and was skipped', 'Return a confidence score lower than a normal full-pipeline approval', 'Include a note that manual review is recommended due to incomplete processing']}`
- Actual decision: **APPROVED** (amount ₹4,000, confidence 0.7)
- User message: _Your claim has been approved for ₹4,000. Funds will be disbursed within 5 working days._
- Calc breakdown:
  - `raw_claim_amount`: ₹4,000 → ₹4,000 (starting amount after line-item exclusions)
- Skipped stages: ['consistency']
- Trace: `intake:PASS → classifier:PASS → sufficiency:PASS → parser:PASS → quality:PASS → consistency:FAILED → rules_engine:PASS → fraud:PASS → synthesizer:PASS`
- Match: **True** — decision and amount match expected

### TC012 — Excluded Treatment
- Expected: `{'decision': 'REJECTED', 'rejection_reasons': ['EXCLUDED_CONDITION'], 'confidence_score': 'above 0.90'}`
- Actual decision: **REJECTED** (amount ₹0, confidence 0.95)
- Rejection reasons: ['EXCLUDED_CONDITION']
- User message: _This claim is for a condition that is not covered under your policy ("Obesity and weight loss programs"). We can't process it. Please refer to the policy exclusions list for details._
- Trace: `intake:PASS → classifier:PASS → sufficiency:PASS → parser:PASS → quality:PASS → consistency:PASS → rules_engine:PASS → fraud:PASS → synthesizer:PASS`
- Match: **True** — decision and amount match expected
