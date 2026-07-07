"""Self-test endpoints (stress / self-esteem / depression screens).

Tests live in the `test` table (seeded from definitions.py on boot). Scoring
happens server-side, and every completed attempt is recorded in `test_created`
(user, answers, score, band, date).
"""
from flask import Blueprint, request, jsonify, g

from app.auth.decorators import login_required
from app.db.repo import list_tests, get_test, save_test_result
from app.http_utils import json_error

self_test_bp = Blueprint("self_test", __name__, url_prefix="/api/tests")


def _public_summary(t):
    """Card-level shape: no questions/scoring payload."""
    return {
        "id": t["id"],
        "slug": t["slug"],
        "title": t["title"],
        "description": t.get("description"),
        "source": t.get("source"),
        "reference": t.get("reference"),
        "numQuestions": len(t.get("questions") or []),
    }


@self_test_bp.get("")
@login_required
def list_all():
    return jsonify({"tests": [_public_summary(t) for t in list_tests()]})


@self_test_bp.get("/<test_id>")
@login_required
def get_one(test_id):
    t = get_test(test_id)
    if not t:
        return json_error("test not found", 404)
    t.pop("scoring", None)  # bands stay server-side; the client just shows the result
    return jsonify(t)


@self_test_bp.post("/<test_id>/submit")
@login_required
def submit(test_id):
    t = get_test(test_id)
    if not t:
        return json_error("test not found", 404)

    data = request.get_json(silent=True) or {}
    answers = data.get("answers")
    questions = t["questions"]
    if not isinstance(answers, list) or len(answers) != len(questions):
        return json_error("please answer every question", 400)

    score = 0
    for i, (ans, q) in enumerate(zip(answers, questions)):
        options = q["options"]
        if not isinstance(ans, int) or not (0 <= ans < len(options)):
            return json_error(f"invalid answer for question {i + 1}", 400)
        score += int(options[ans]["value"])

    scoring = t["scoring"]
    band = next((b for b in scoring["bands"] if b["min"] <= score <= b["max"]),
                scoring["bands"][-1])

    # Safety net (e.g. PHQ-9 item 9): certain answers always surface crisis
    # contacts with the result, regardless of the total score.
    alert = None
    alert_q = scoring.get("alert_question")
    if alert_q is not None and answers[alert_q] >= scoring.get("alert_min", 1):
        alert = scoring.get("alert_message")

    save_test_result(g.user["id"], t["id"], answers, score, band["label"])

    return jsonify({
        "score": score,
        "max": scoring["max"],
        "band": band["label"],
        "advice": band["advice"],
        "alert": alert,
    })
