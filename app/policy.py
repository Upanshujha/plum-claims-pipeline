"""Policy loader.

policy_terms.json is loaded once at startup. Policy logic is NEVER hardcoded
elsewhere in the codebase — every rule must reach through this module.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Optional


class Policy:
    def __init__(self, data: dict[str, Any]):
        self._data = data

    # ---------- top-level ----------
    @property
    def policy_id(self) -> str:
        return self._data["policy_id"]

    @property
    def raw(self) -> dict[str, Any]:
        return self._data

    # ---------- coverage ----------
    @property
    def per_claim_limit(self) -> int:
        return self._data["coverage"]["per_claim_limit"]

    @property
    def annual_opd_limit(self) -> int:
        return self._data["coverage"]["annual_opd_limit"]

    @property
    def minimum_claim_amount(self) -> int:
        return self._data["submission_rules"]["minimum_claim_amount"]

    @property
    def submission_window_days(self) -> int:
        return self._data["submission_rules"]["deadline_days_from_treatment"]

    # ---------- categories ----------
    def category(self, name: str) -> dict[str, Any]:
        name = name.lower()
        if name not in self._data["opd_categories"]:
            raise KeyError(f"Unknown category {name}")
        return self._data["opd_categories"][name]

    def category_sub_limit(self, name: str) -> int:
        return self.category(name)["sub_limit"]

    def category_copay(self, name: str) -> float:
        return self.category(name).get("copay_percent", 0) / 100.0

    def category_network_discount(self, name: str) -> float:
        return self.category(name).get("network_discount_percent", 0) / 100.0

    # ---------- waiting periods ----------
    def waiting_period_for_condition(self, diagnosis: Optional[str]) -> Optional[int]:
        """Return waiting-period days if the diagnosis maps to a named condition."""
        if not diagnosis:
            return None
        diag = diagnosis.lower()
        diag_words = set(diag.replace(",", " ").replace(".", " ")
                         .replace("-", " ").replace("(", " ").replace(")", " ")
                         .split())
        mapping = self._data["waiting_periods"]["specific_conditions"]
        # Aliases with match strategy: "contains" for phrase matches,
        # "word" for whole-word matches (avoids "hernia" matching "herniation").
        aliases = {
            "diabetes": {"contains": ["diabetes", "diabetic", "t2dm",
                                       "type 2 diabetes", "type ii diabetes"]},
            "hypertension": {"contains": ["hypertension", "htn",
                                           "high bp", "high blood pressure"]},
            "thyroid_disorders": {"contains": ["hypothyroid", "thyroid"]},
            "joint_replacement": {"contains": ["joint replacement"]},
            "maternity": {"contains": ["maternity", "pregnancy"]},
            "mental_health": {"contains": ["depression", "anxiety", "mental health"]},
            "obesity_treatment": {"contains": ["obesity", "bariatric",
                                                 "morbid obesity"]},
            # "hernia" must match as a whole word to avoid "disc herniation"
            # being misread as an abdominal hernia case.
            "hernia": {"word": ["hernia"]},
            "cataract": {"contains": ["cataract"]},
        }
        for key, rule in aliases.items():
            if key not in mapping:
                continue
            if any(t in diag for t in rule.get("contains", [])):
                return mapping[key]
            if any(w in diag_words for w in rule.get("word", [])):
                return mapping[key]
        return None

    def initial_waiting_days(self) -> int:
        return self._data["waiting_periods"]["initial_waiting_period_days"]

    # ---------- exclusions ----------
    def is_excluded_condition(self, diagnosis: Optional[str]) -> Optional[str]:
        """Return the matching exclusion string if diagnosis maps to one."""
        if not diagnosis:
            return None
        diag = diagnosis.lower()
        excl = self._data["exclusions"]["conditions"]
        # Hardcoded semantic mapping of messy diagnoses to policy exclusions.
        semantic_map = {
            "obesity": "Obesity and weight loss programs",
            "bariatric": "Obesity and weight loss programs",
            "weight loss": "Obesity and weight loss programs",
            "cosmetic": "Cosmetic or aesthetic procedures",
            "aesthetic": "Cosmetic or aesthetic procedures",
            "infertility": "Infertility and assisted reproduction",
            "ivf": "Infertility and assisted reproduction",
            "substance abuse": "Substance abuse treatment",
            "self-inflicted": "Self-inflicted injuries",
        }
        for term, exclusion in semantic_map.items():
            if term in diag and exclusion in excl:
                return exclusion
        return None

    # ---------- dental / line-item checks ----------
    def dental_excluded_procedures(self) -> list[str]:
        return [p.lower() for p in self._data["opd_categories"]["dental"]["excluded_procedures"]]

    def dental_covered_procedures(self) -> list[str]:
        return [p.lower() for p in self._data["opd_categories"]["dental"]["covered_procedures"]]

    def is_dental_excluded(self, line_desc: str) -> bool:
        d = line_desc.lower()
        return any(x in d for x in self.dental_excluded_procedures())

    # ---------- pre-auth ----------
    def requires_pre_auth(self, category: str, amount: int, description: str = "") -> bool:
        cat = self.category(category)
        threshold = cat.get("pre_auth_threshold")
        high_tests = [t.lower() for t in cat.get("high_value_tests_requiring_pre_auth", [])]
        if not threshold:
            return False
        desc = description.lower()
        if not any(t in desc for t in high_tests):
            return False
        return amount > threshold

    # ---------- network ----------
    def is_network_hospital(self, name: Optional[str]) -> bool:
        if not name:
            return False
        name_l = name.lower()
        return any(n.lower() in name_l or name_l in n.lower()
                   for n in self._data["network_hospitals"])

    # ---------- document requirements ----------
    def document_requirements(self, category: str) -> dict[str, list[str]]:
        return self._data["document_requirements"][category]

    # ---------- fraud thresholds ----------
    @property
    def fraud_thresholds(self) -> dict[str, Any]:
        return self._data["fraud_thresholds"]

    # ---------- members ----------
    def find_member(self, member_id: str) -> Optional[dict[str, Any]]:
        for m in self._data["members"]:
            if m["member_id"] == member_id:
                return m
        return None

    def eligible_from(self, member_id: str, waiting_days: int) -> Optional[date]:
        m = self.find_member(member_id)
        if not m:
            return None
        join_date = datetime.fromisoformat(m["join_date"]).date()
        return join_date + timedelta(days=waiting_days)


def load_policy(path: str = "policy_terms.json") -> Policy:
    p = Path(path)
    if not p.exists():
        # fallback: search upwards from this file
        here = Path(__file__).resolve().parent.parent
        p = here / path
    with open(p) as f:
        return Policy(json.load(f))
