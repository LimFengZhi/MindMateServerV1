"""Staff-only admin site: the /admin page shell + its JSON API.

Roles: 'staff' get the backoffice tools (dashboard, emotion analysis, session
review with rating/feedback, chatbot testing, JSON export); 'admin' can
additionally create staff accounts by email (and remove staff access).
Promote the first admin in Supabase:
    update public.profiles set role = 'admin' where email = '…';
The page itself is a static shell — every piece of data comes from the guarded
/api/admin endpoints, so the real access control is server-side.
"""
import json
from datetime import datetime, timezone

from flask import Blueprint, Response, render_template, request, jsonify, g

from app.admin.service import create_staff_account
from app.auth.decorators import staff_required, admin_required
from app.auth.routes import EMAIL_RE
from app.auth.service import AuthError
from app.db.admin_repo import (
    get_stats, get_emotion_overview, list_all_sessions, get_session_review,
    list_staff_accounts, set_role,
)
from app.db.repo import get_profile, set_message_feedback
from app.http_utils import json_error

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")
admin_api_bp = Blueprint("admin_api", __name__, url_prefix="/api/admin")


# ---------------- Pages ----------------
@admin_bp.get("")
def dashboard_page():
    return render_template("admin/dashboard.html")


@admin_bp.get("/login")
def staff_login_page():
    return render_template("admin/login.html")


@admin_bp.get("/testing/multi-agent")
def test_multi_page():
    return render_template("admin/test_multi.html")


# ---------------- JSON API: dashboard ----------------
@admin_api_bp.get("/stats")
@staff_required
def stats():
    return jsonify(get_stats())


@admin_api_bp.get("/emotions")
@staff_required
def emotions():
    return jsonify(get_emotion_overview())


# ---------------- JSON API: session review + feedback + export ----------------
@admin_api_bp.get("/sessions")
@staff_required
def sessions_list():
    return jsonify({"sessions": list_all_sessions()})


@admin_api_bp.get("/sessions/<session_id>")
@staff_required
def session_review(session_id):
    data = get_session_review(session_id)
    if not data:
        return json_error("session not found", 404)
    return jsonify(data)


@admin_api_bp.get("/sessions/<session_id>/export")
@staff_required
def session_export(session_id):
    """Download one session (transcript + diagnostics + feedback) as JSON."""
    data = get_session_review(session_id)
    if not data:
        return json_error("session not found", 404)
    data["exportedBy"] = g.user["email"]
    data["exportedAt"] = datetime.now(timezone.utc).isoformat()
    payload = json.dumps(data, indent=2, ensure_ascii=False)
    return Response(payload, mimetype="application/json", headers={
        "Content-Disposition": f'attachment; filename="session-{session_id}.json"',
    })


@admin_api_bp.post("/messages/<message_id>/feedback")
@staff_required
def message_feedback(message_id):
    """Staff rating (1-5) and/or feedback text for one bot reply."""
    data = request.get_json(silent=True) or {}
    rating = data.get("rating")
    feedback = (data.get("feedback") or "").strip() or None
    if rating is None and feedback is None:
        return json_error("provide a rating or feedback", 400)
    if rating is not None:
        if not isinstance(rating, int) or not (1 <= rating <= 5):
            return json_error("rating must be an integer from 1 to 5", 400)
    row = set_message_feedback(message_id, rating=rating, feedback=feedback,
                               feedback_by=g.user["id"])
    if not row:
        return json_error("message not found", 404)
    return jsonify({"ok": True, "rating": row.get("rating"),
                    "feedback": row.get("feedback")})


@admin_api_bp.get("/staff")
@admin_required
def staff_list():
    return jsonify({"staff": list_staff_accounts()})


@admin_api_bp.post("/staff")
@admin_required
def staff_create():
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""
    if not EMAIL_RE.match(email):
        return json_error("A valid email address is required.", 400)
    try:
        result = create_staff_account(email, password)
    except AuthError as e:
        return json_error(e.message, e.status)
    return jsonify({"ok": True, "promoted": result["promoted"]}), 201


@admin_api_bp.delete("/staff/<user_id>")
@admin_required
def staff_remove(user_id):
    profile = get_profile(user_id)
    if not profile:
        return json_error("account not found", 404)
    if profile.get("role") != "staff":
        return json_error("only staff accounts can be removed here", 400)
    set_role(user_id, "user")  # back to a normal user; the login still works
    return jsonify({"ok": True})
