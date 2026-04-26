"""Tests. Works with pytest or `python -m unittest discover tests`.

Covers rules engine, sufficiency, fraud, full pipeline integration,
and the rejection explainer (stage 10) with both LLM-success and
LLM-failure paths mocked.
"""
from __future__ import annotations

import json
import sys
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.models import (CalcStep, ClaimCategory, ClaimSubmission,
                        DocClassification, DocType, LineItem, ParsedDoc,
                        StageStatus, UploadedDoc)
from app.pipeline import Pipeline
from app.policy import load_policy
from app.stages import fraud, rejection_explainer, rules_engine, sufficiency


# ------------------------- fixtures --------------------------------

POLICY = load_policy(str(ROOT / "policy_terms.json"))
PIPELINE = Pipeline(POLICY)
with open(ROOT / "test_cases.json") as f:
    TEST_CASES = {tc["case_id"]: tc for tc in json.load(f)["test_cases"]}


def _submission(**overrides) -> ClaimSubmission:
    base = dict(
        member_id="EMP001",
        policy_id="PLUM_GHI_2024",
        claim_category=ClaimCategory.CONSULTATION,
        treatment_date=date(2024, 11, 1),
        claimed_amount=1500,
        documents=[UploadedDoc(file_id="F001")],
        ytd_claims_amount=0,
    )
    base.update(overrides)
    return ClaimSubmission(**base)


# ------------------------- rules engine ----------------------------

class RulesEngineTests(unittest.TestCase):

    def test_clean_consultation_applies_copay(self):
        """TC004-style: ₹1,500 consultation, 10% co-pay → ₹1,350."""
        sub = _submission(claimed_amount=1500, ytd_claims_amount=5000)
        parsed = [ParsedDoc(
            file_id="F001", doc_type=DocType.HOSPITAL_BILL,
            patient_name="Rajesh Kumar", diagnosis="Viral Fever",
            line_items=[
                LineItem(description="Consultation Fee", amount=1000),
                LineItem(description="CBC Test", amount=300),
                LineItem(description="Dengue NS1 Test", amount=200),
            ],
        )]
        member = POLICY.find_member("EMP001")
        r = rules_engine.evaluate(sub, parsed, POLICY, member)
        self.assertEqual(r.decision.value, "APPROVED")
        self.assertEqual(r.approved_amount, 1350)

    def test_waiting_period_diabetes_rejected(self):
        """TC005-style: diabetes within 90-day waiting period → REJECTED."""
        sub = _submission(member_id="EMP005",
                          treatment_date=date(2024, 10, 15),
                          claimed_amount=3000)
        parsed = [ParsedDoc(file_id="F009", doc_type=DocType.PRESCRIPTION,
                            patient_name="Vikram Joshi",
                            diagnosis="Type 2 Diabetes Mellitus")]
        r = rules_engine.evaluate(sub, parsed, POLICY, POLICY.find_member("EMP005"))
        self.assertEqual(r.decision.value, "REJECTED")
        self.assertIn("WAITING_PERIOD", r.rejection_reasons)

    def test_dental_cosmetic_line_item_excluded(self):
        """TC006-style: root canal + teeth whitening → PARTIAL ₹8,000."""
        sub = _submission(member_id="EMP002",
                          claim_category=ClaimCategory.DENTAL,
                          claimed_amount=12000,
                          treatment_date=date(2024, 10, 15))
        parsed = [ParsedDoc(
            file_id="F011", doc_type=DocType.HOSPITAL_BILL,
            patient_name="Priya Singh",
            line_items=[
                LineItem(description="Root Canal Treatment", amount=8000),
                LineItem(description="Teeth Whitening", amount=4000),
            ],
        )]
        r = rules_engine.evaluate(sub, parsed, POLICY, POLICY.find_member("EMP002"))
        self.assertEqual(r.decision.value, "PARTIAL")
        self.assertEqual(r.approved_amount, 8000)

    def test_per_claim_limit_exceeded_rejected(self):
        """TC008-style: ₹7,500 consultation vs ₹5,000 per-claim cap → REJECTED."""
        sub = _submission(member_id="EMP003",
                          treatment_date=date(2024, 10, 20),
                          claimed_amount=7500,
                          ytd_claims_amount=10000)
        parsed = [ParsedDoc(
            file_id="F015", doc_type=DocType.HOSPITAL_BILL,
            diagnosis="Gastroenteritis",
            line_items=[
                LineItem(description="Consultation Fee", amount=2000),
                LineItem(description="Medicines", amount=5500),
            ],
        )]
        r = rules_engine.evaluate(sub, parsed, POLICY, POLICY.find_member("EMP003"))
        self.assertEqual(r.decision.value, "REJECTED")
        self.assertIn("PER_CLAIM_EXCEEDED", r.rejection_reasons)

    def test_network_discount_applied_before_copay(self):
        """TC010: ₹4,500 at Apollo → 20% discount → ₹3,600 → 10% copay → ₹3,240."""
        sub = _submission(member_id="EMP010",
                          treatment_date=date(2024, 11, 3),
                          claimed_amount=4500,
                          hospital_name="Apollo Hospitals",
                          ytd_claims_amount=8000)
        parsed = [ParsedDoc(
            file_id="F020", doc_type=DocType.HOSPITAL_BILL,
            patient_name="Deepak Shah",
            hospital_name="Apollo Hospitals",
            diagnosis="Acute Bronchitis",
            line_items=[
                LineItem(description="Consultation Fee", amount=1500),
                LineItem(description="Medicines", amount=3000),
            ],
        )]
        r = rules_engine.evaluate(sub, parsed, POLICY, POLICY.find_member("EMP010"))
        self.assertEqual(r.decision.value, "APPROVED")
        self.assertEqual(r.approved_amount, 3240)
        labels = [s.label for s in r.calc_steps]
        self.assertLess(labels.index("network_discount"), labels.index("copay"),
                        "network discount must precede copay")

    def test_obesity_excluded_before_waiting_period(self):
        """TC012-style: obesity is both an exclusion and a waiting-period condition.
        Exclusion must win."""
        sub = _submission(member_id="EMP009",
                          treatment_date=date(2024, 10, 18),
                          claimed_amount=8000)
        parsed = [ParsedDoc(
            file_id="F023", doc_type=DocType.PRESCRIPTION,
            diagnosis="Morbid Obesity — BMI 37",
            treatment="Bariatric Consultation and Customised Diet Plan",
        )]
        r = rules_engine.evaluate(sub, parsed, POLICY, POLICY.find_member("EMP009"))
        self.assertEqual(r.decision.value, "REJECTED")
        self.assertIn("EXCLUDED_CONDITION", r.rejection_reasons)
        self.assertNotIn("WAITING_PERIOD", r.rejection_reasons)


# ------------------------- sufficiency -----------------------------

class SufficiencyTests(unittest.TestCase):

    def test_passes_with_correct_docs(self):
        classes = [
            DocClassification(file_id="F1", predicted_type=DocType.PRESCRIPTION, confidence=0.98),
            DocClassification(file_id="F2", predicted_type=DocType.HOSPITAL_BILL, confidence=0.98),
        ]
        result = sufficiency.check_sufficiency(ClaimCategory.CONSULTATION, classes, POLICY)
        self.assertEqual(result["status"], StageStatus.PASS)

    def test_stops_when_bill_missing(self):
        """TC001: two prescriptions, no bill → STOP with named types in message."""
        classes = [
            DocClassification(file_id="F1", predicted_type=DocType.PRESCRIPTION, confidence=0.98),
            DocClassification(file_id="F2", predicted_type=DocType.PRESCRIPTION, confidence=0.98),
        ]
        result = sufficiency.check_sufficiency(ClaimCategory.CONSULTATION, classes, POLICY)
        self.assertEqual(result["status"], StageStatus.STOP)
        self.assertIn("hospital bill", result["user_message"].lower())
        self.assertIn("prescription", result["user_message"].lower())

    def test_diagnostic_accepts_bill_substitute(self):
        """TC007: HOSPITAL_BILL should satisfy LAB_REPORT requirement for imaging."""
        classes = [
            DocClassification(file_id="F1", predicted_type=DocType.PRESCRIPTION, confidence=0.98),
            DocClassification(file_id="F2", predicted_type=DocType.HOSPITAL_BILL, confidence=0.98),
        ]
        result = sufficiency.check_sufficiency(ClaimCategory.DIAGNOSTIC, classes, POLICY)
        self.assertEqual(result["status"], StageStatus.PASS)


# ------------------------- fraud -----------------------------------

class FraudTests(unittest.TestCase):

    def test_fourth_same_day_claim_flags(self):
        history = [
            {"claim_id": "CLM_0081", "date": "2024-10-30", "amount": 1200, "provider": "A"},
            {"claim_id": "CLM_0082", "date": "2024-10-30", "amount": 1800, "provider": "B"},
            {"claim_id": "CLM_0083", "date": "2024-10-30", "amount": 2100, "provider": "C"},
        ]
        sub = _submission(member_id="EMP008",
                          treatment_date=date(2024, 10, 30),
                          claimed_amount=4800,
                          claims_history=history)
        result = fraud.detect_fraud(sub, POLICY)
        self.assertTrue(result["forces_manual_review"])
        codes = [s.code for s in result["signals"]]
        self.assertIn("SAME_DAY_FREQUENCY", codes)

    def test_clean_history_doesnt_fire(self):
        sub = _submission(member_id="EMP008", claims_history=[])
        result = fraud.detect_fraud(sub, POLICY)
        self.assertFalse(result["forces_manual_review"])


# ------------------------- integration (all 12 test cases) ----------

class IntegrationTests(unittest.TestCase):

    def _run(self, case_id):
        return PIPELINE.run(ClaimSubmission.from_dict(TEST_CASES[case_id]["input"]))

    def test_tc001_stops(self):
        d = self._run("TC001")
        self.assertIsNone(d.decision)
        self.assertIn("hospital bill", d.user_message.lower())

    def test_tc002_asks_reupload(self):
        d = self._run("TC002")
        self.assertIsNone(d.decision)
        self.assertIn("re-upload", d.user_message.lower())

    def test_tc003_different_patients_stops(self):
        d = self._run("TC003")
        self.assertIsNone(d.decision)
        self.assertIn("rajesh", d.user_message.lower())
        self.assertIn("arjun", d.user_message.lower())

    def test_tc004_approved_1350(self):
        d = self._run("TC004")
        self.assertEqual(d.decision.value, "APPROVED")
        self.assertEqual(d.approved_amount, 1350)
        self.assertGreaterEqual(d.confidence, 0.85)

    def test_tc005_diabetes_rejected(self):
        d = self._run("TC005")
        self.assertEqual(d.decision.value, "REJECTED")
        self.assertIn("WAITING_PERIOD", d.rejection_reasons)

    def test_tc006_dental_partial_8000(self):
        d = self._run("TC006")
        self.assertEqual(d.decision.value, "PARTIAL")
        self.assertEqual(d.approved_amount, 8000)

    def test_tc007_mri_no_preauth_rejected(self):
        d = self._run("TC007")
        self.assertEqual(d.decision.value, "REJECTED")
        self.assertIn("PRE_AUTH_MISSING", d.rejection_reasons)

    def test_tc008_per_claim_exceeded_rejected(self):
        d = self._run("TC008")
        self.assertEqual(d.decision.value, "REJECTED")
        self.assertIn("PER_CLAIM_EXCEEDED", d.rejection_reasons)

    def test_tc009_same_day_manual_review(self):
        d = self._run("TC009")
        self.assertEqual(d.decision.value, "MANUAL_REVIEW")

    def test_tc010_network_discount_3240(self):
        d = self._run("TC010")
        self.assertEqual(d.decision.value, "APPROVED")
        self.assertEqual(d.approved_amount, 3240)

    def test_tc011_component_failure_degraded(self):
        d = self._run("TC011")
        self.assertEqual(d.decision.value, "APPROVED")
        self.assertTrue(len(d.skipped_stages) > 0)
        self.assertTrue(d.manual_review_recommended)
        self.assertLess(d.confidence, 0.95)

    def test_tc012_excluded_obesity(self):
        d = self._run("TC012")
        self.assertEqual(d.decision.value, "REJECTED")
        self.assertIn("EXCLUDED_CONDITION", d.rejection_reasons)


# ------------------------- rejection explainer (stage 10) ----------
# These tests do NOT require a real GROQ_API_KEY. They patch the parts
# of the stage that touch the network so the test suite stays fast,
# deterministic, and runnable on CI without secrets. The point is to
# prove two things:
#   (a) when the LLM behaves, we get a structured explanation that the
#       pipeline patches into user_message;
#   (b) when the LLM misbehaves (no key, network blip, malformed JSON),
#       the stage returns None and the pipeline falls back to the
#       existing static template — without raising.

class _FakeMessage:
    def __init__(self, content): self.content = content
class _FakeChoice:
    def __init__(self, content): self.message = _FakeMessage(content)
class _FakeCompletion:
    def __init__(self, content): self.choices = [_FakeChoice(content)]
class _FakeChat:
    def __init__(self, content): self._content = content
    @property
    def completions(self):
        outer = self
        class C:
            def create(self, **kwargs):
                return _FakeCompletion(outer._content)
        return C()
class _FakeGroqClient:
    def __init__(self, content): self.chat = _FakeChat(content)


class RejectionExplainerTests(unittest.TestCase):

    def test_success_replaces_user_message(self):
        """When Groq returns valid JSON, the explainer parses it and
        the pipeline overwrites user_message with the LLM output. The
        underlying decision and amount must NOT change."""
        good_json = json.dumps({
            "headline": "We can't approve this claim right now.",
            "reason": ("Your policy has a 90-day waiting period for "
                       "diabetes-related treatment from your join date."),
            "next_steps": ("You'll be eligible for diabetes-related "
                           "claims from 30-Nov-2024 — please resubmit then."),
        })
        with patch.dict("os.environ", {"GROQ_API_KEY": "test-key-not-real"}), \
             patch("groq.Groq",
                   return_value=_FakeGroqClient(good_json)):
            d = PIPELINE.run(ClaimSubmission.from_dict(TEST_CASES["TC005"]["input"]))
        # Decision and amount unchanged.
        self.assertEqual(d.decision.value, "REJECTED")
        self.assertIn("WAITING_PERIOD", d.rejection_reasons)
        # User message comes from the LLM.
        self.assertIn("90-day waiting period", d.user_message)
        self.assertIn("30-Nov-2024", d.user_message)
        # Trace records a PASS for the new stage.
        stages = [t.stage for t in d.trace]
        self.assertIn("rejection_explainer", stages)
        re_entry = next(t for t in d.trace if t.stage == "rejection_explainer")
        self.assertEqual(re_entry.status, StageStatus.PASS)

    def test_malformed_llm_output_falls_back_to_template(self):
        """When Groq returns junk, the stage swallows the error and
        the pipeline keeps the static template. Pipeline never crashes."""
        bad_payload = "this is not json {{{"
        with patch.dict("os.environ", {"GROQ_API_KEY": "test-key-not-real"}), \
             patch("groq.Groq",
                   return_value=_FakeGroqClient(bad_payload)):
            d = PIPELINE.run(ClaimSubmission.from_dict(TEST_CASES["TC005"]["input"]))
        self.assertEqual(d.decision.value, "REJECTED")
        # Static template wording is still present.
        self.assertIn("waiting period", d.user_message.lower())
        # Trace shows the stage was tried but skipped.
        re_entry = next(t for t in d.trace if t.stage == "rejection_explainer")
        self.assertEqual(re_entry.status, StageStatus.SKIPPED)
        self.assertTrue(re_entry.payload.get("fallback_used"))


if __name__ == "__main__":
    unittest.main()
