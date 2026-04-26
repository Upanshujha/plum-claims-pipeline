"""Flask app — claim submission API and reviewer UI.

Two surfaces:
  * POST /api/claims — accepts a ClaimSubmission (JSON) and runs the pipeline.
  * GET  /         — minimal UI that posts the JSON and renders the trace.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Load .env early so GROQ_API_KEY is set before pipeline imports check
# os.environ. python-dotenv is optional — if it's not installed (e.g.
# the user only ran the eval, not the Flask server) we silently skip.
try:
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=Path(__file__).resolve().parent.parent / ".env")
except ImportError:
    pass

from flask import Flask, jsonify, render_template, request

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.models import ClaimSubmission, to_dict
from app.pipeline import Pipeline
from app.policy import load_policy


ROOT = Path(__file__).resolve().parent.parent
app = Flask(
    __name__,
    template_folder=str(ROOT / "ui"),
    static_folder=str(ROOT / "ui"),
)
_policy = load_policy(str(ROOT / "policy_terms.json"))
_pipeline = Pipeline(_policy)

# Simple in-memory store for recently processed claims (reviewer can reopen them).
CLAIMS: dict[str, dict] = {}


@app.route("/")
def index():
    # Load test cases so the UI can pre-populate sample payloads.
    with open(ROOT / "test_cases.json") as f:
        test_cases = json.load(f)["test_cases"]
    return render_template("index.html", test_cases=test_cases)


@app.route("/api/claims", methods=["POST"])
def submit_claim():
    payload = request.get_json(force=True)
    try:
        submission = ClaimSubmission.from_dict(payload)
    except Exception as e:
        return jsonify({"error": f"invalid submission: {e}"}), 400

    decision = _pipeline.run(submission)
    d = to_dict(decision)
    CLAIMS[decision.claim_id] = d
    return jsonify(d)


@app.route("/api/claims/<claim_id>")
def get_claim(claim_id):
    if claim_id not in CLAIMS:
        return jsonify({"error": "claim not found"}), 404
    return jsonify(CLAIMS[claim_id])


@app.route("/api/test_cases")
def list_test_cases():
    with open(ROOT / "test_cases.json") as f:
        return jsonify(json.load(f)["test_cases"])


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
