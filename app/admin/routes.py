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
import os
from datetime import datetime, timezone

from flask import Blueprint, Response, render_template, request, jsonify, g

from app.admin.service import create_staff_account
from app.auth.decorators import staff_required, admin_required
from app.auth.routes import EMAIL_RE
from app.auth.service import AuthError
from app.db.admin_repo import (
    get_stats, get_emotion_overview, list_all_sessions, get_session_review,
    list_staff_accounts, set_role, list_all_resources, update_resource, list_prompts, update_prompt, list_agreements, update_agreement,
    create_prompt, delete_prompt, create_resource, delete_resource, list_tests, create_test, update_test, delete_test, get_test_analytics,
)
from app.db.repo import get_profile, set_message_feedback
from app.http_utils import json_error

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")
admin_api_bp = Blueprint("admin_api", __name__, url_prefix="/api/admin")
DATASET_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'resources', 'datasets')


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


@admin_api_bp.get("/resources")
@staff_required
def admin_resources_list():
    """API endpoint to get all resources for editing."""
    return jsonify({"resources": list_all_resources()})


@admin_api_bp.post("/resources/<resource_id>")
@staff_required
def admin_resource_update(resource_id):
    """API endpoint to save edited resource attributes."""
    data = request.get_json(silent=True) or {}

    title = (data.get("title") or "").strip()
    if not title:
        return json_error("A resource title is required.", 400)

    # Gather data payloads conforming to table schema definitions
    payload = {
        "title": title,
        "category": data.get("category"),
        "summary": data.get("summary"),
        "info": data.get("info"),
        "kind": data.get("kind", "article"),
        "external_url": data.get("external_url"),
        "source": data.get("source"),
        "is_published": bool(data.get("is_published", True))
    }

    if update_resource(resource_id, payload):
        return jsonify({"ok": True})
    return json_error("Failed to update resource in database.", 500)


@admin_api_bp.post("/resources")
@staff_required
def admin_resource_create():
    """API endpoint to create a new resource."""
    data = request.get_json(silent=True) or {}
    title = (data.get("title") or "").strip()

    if not title:
        return json_error("A resource title is required.", 400)

    payload = {
        "title": title,
        "category": data.get("category"),
        "summary": data.get("summary"),
        "info": data.get("info"),
        "kind": data.get("kind", "article"),
        "external_url": data.get("external_url"),
        "source": data.get("source"),
        "is_published": bool(data.get("is_published", True))
    }

    if create_resource(payload):
        return jsonify({"ok": True})
    return json_error("Failed to create resource in database.", 500)


@admin_api_bp.delete("/resources/<resource_id>")
@staff_required
def admin_resource_delete(resource_id):
    """API endpoint to delete a resource."""
    if delete_resource(resource_id):
        return jsonify({"ok": True})
    return json_error("Failed to delete resource.", 500)

@admin_api_bp.get("/dataset/<dataset_type>")
@staff_required
def get_dashboard_dataset(dataset_type):
    if dataset_type not in ["chatbot", "classifier"]:
        return json_error("Invalid dataset selection", 400)

    file_path = os.path.join(DATASET_DIR, f"{dataset_type}.json")

    if not os.path.exists(file_path):
        return jsonify({"data": [], "total": 0, "page": 1})

    page = int(request.args.get("page", 1))
    per_page = 100

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            try:
                dataset_content = json.load(f)
            except json.JSONDecodeError:
                f.seek(0)
                dataset_content = [json.loads(line) for line in f if line.strip()]

        total_items = len(dataset_content)
        start_idx = (page - 1) * per_page
        end_idx = start_idx + per_page
        paginated_data = dataset_content[start_idx:end_idx]

        return jsonify({
            "data": paginated_data,
            "total": total_items,
            "page": page,
            "total_pages": (total_items + per_page - 1) // per_page
        })
    except Exception as e:
        return json_error(f"Failed reading local dataset: {str(e)}", 500)


# --- Prompts API ---
@admin_api_bp.get("/prompts")
@staff_required
def get_dashboard_prompts():
    return jsonify({"data": list_prompts()})


@admin_api_bp.post("/prompts")
@staff_required
def add_dashboard_prompt():
    """Create a completely new system prompt."""
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    content = (data.get("content") or "").strip()

    if not name or not content:
        return json_error("Both a prompt name and content are required.", 400)

    # Ensure name is formatted safely (no spaces, lowercase)
    clean_name = name.lower().replace(" ", "_")

    success, error_msg = create_prompt(clean_name, content)
    if success:
        return jsonify({"ok": True, "name": clean_name})
    return json_error(error_msg or "Failed to create prompt.", 500)

@admin_api_bp.post("/prompts/<prompt_id>")
@staff_required
def save_dashboard_prompt(prompt_id):
    data = request.get_json(silent=True) or {}
    content = (data.get("content") or "").strip()
    if not content:
        return json_error("Prompt content cannot be empty.", 400)

    if update_prompt(prompt_id, content):
        return jsonify({"ok": True})
    return json_error("Failed to update prompt.", 500)

@admin_api_bp.delete("/prompts/<prompt_id>")
@staff_required
def remove_dashboard_prompt(prompt_id):
    """API endpoint to delete a system prompt."""
    if delete_prompt(prompt_id):
        return jsonify({"ok": True})
    return json_error("Failed to delete prompt from database.", 500)

# --- Agreements API ---
@admin_api_bp.get("/agreements")
@staff_required
def get_dashboard_agreements():
    return jsonify({"data": list_agreements()})


@admin_api_bp.post("/agreements/<agreement_id>")
@staff_required
def save_dashboard_agreement(agreement_id):
    data = request.get_json(silent=True) or {}
    content = (data.get("content") or "").strip()
    if not content:
        return json_error("Agreement content cannot be empty.", 400)

    if update_agreement(agreement_id, content):
        return jsonify({"ok": True})
    return json_error("Failed to update agreement.", 500)


@admin_api_bp.get("/tests")
@staff_required
def admin_tests_list():
    """API endpoint to fetch all tests."""
    return jsonify({"data": list_tests()})


@admin_api_bp.post("/tests")
@staff_required
def admin_test_create():
    """API endpoint to create a new test."""
    data = request.get_json(silent=True) or {}
    title = (data.get("title") or "").strip()

    if not title:
        return json_error("A test title is required.", 400)

    slug = title.lower().replace(" ", "-")

    payload = {
        "title": title,
        "slug": slug,
        "description": data.get("description"),
        "questions": data.get("questions", []),
        "scoring": data.get("scoring", {}),
        "is_published": True
    }

    if create_test(payload):
        return jsonify({"ok": True})
    return json_error("Failed to create test in database.", 500)


@admin_api_bp.post("/tests/<test_id>")
@staff_required
def admin_test_update(test_id):
    """API endpoint to update an existing test."""
    data = request.get_json(silent=True) or {}

    payload = {
        "title": data.get("title"),
        "description": data.get("description"),
        "questions": data.get("questions")
    }

    if update_test(test_id, payload):
        return jsonify({"ok": True})
    return json_error("Failed to update test.", 500)

@admin_api_bp.delete("/tests/<test_id>")
@staff_required
def admin_test_delete(test_id):
    """API endpoint to delete a test."""
    if delete_test(test_id):
        return jsonify({"ok": True})
    return json_error("Failed to delete test.", 500)


@admin_api_bp.get("/analytics/tests")
@staff_required
def admin_test_analytics_api():
    """API endpoint to aggregate and serve test results analytics."""
    raw_data = get_test_analytics()

    analytics = {}
    for row in raw_data:
        # Handle cases where the test might have been deleted but records remain
        test_info = row.get("test")
        if not test_info:
            continue

        title = test_info.get("title", "Unknown Assessment")
        score = row.get("score") or 0
        band = row.get("band") or "Unscored"

        # Initialize the dictionary structure for a new test
        if title not in analytics:
            analytics[title] = {"total_takes": 0, "total_score": 0, "bands": {}}

        analytics[title]["total_takes"] += 1
        analytics[title]["total_score"] += score

        # Count the severity bands
        if band not in analytics[title]["bands"]:
            analytics[title]["bands"][band] = 0
        analytics[title]["bands"][band] += 1

    # Calculate final averages
    for title, stats in analytics.items():
        if stats["total_takes"] > 0:
            stats["avg_score"] = round(stats["total_score"] / stats["total_takes"], 1)
        else:
            stats["avg_score"] = 0

    return jsonify({"data": analytics})