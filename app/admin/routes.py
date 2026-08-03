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
import re
from datetime import datetime, timezone
from uuid import uuid4

from flask import Blueprint, Response, render_template, request, jsonify, g

from app.admin import live_claims
from app.admin.service import create_staff_account
from app.auth.decorators import staff_required, admin_required
from app.auth.routes import EMAIL_RE
from app.auth.service import AuthError
from app.chat.routes import user_or_ip
from app.db.admin_repo import (
    get_stats, get_emotion_overview, list_all_sessions, get_session_review,
    list_staff_accounts, set_role, list_all_resources, update_resource, list_prompts, update_prompt, list_agreements, update_agreement,
    create_prompt, delete_prompt, create_resource, delete_resource, list_tests, create_test, update_test, delete_test, get_test_analytics, get_test_attempts, get_daily_activity,
    BenchTableMissing, save_bench_results, set_bench_feedback,
    create_bench_session, list_bench_sessions, get_bench_session,
    rename_bench_session, delete_bench_session, get_bench_turns, get_bench_histories,
    resolve_pending_message, list_experiment_sessions, rename_session_admin,
    get_suicide_alerts, ALERT_PERIOD_DAYS, list_users_overview,
)
from app.db.repo import get_profile, set_message_feedback
from app.extensions import limiter
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


@admin_bp.get("/live")
def live_page():
    return render_template("admin/live.html")


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
@limiter.limit("60 per minute", key_func=user_or_ip)  # live view polls it ~4s
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


# ---------------- JSON API: live counselling (connect to a user) ----------------
@admin_api_bp.get("/live-sessions")
@staff_required
@limiter.limit("30 per minute", key_func=user_or_ip)  # the live view polls ~4s
def live_sessions():
    """Experiment sessions a counsellor can connect to, with pending counts,
    plus who currently has each user claimed. Polling this doubles as the
    caller's claim heartbeat."""
    live_claims.heartbeat(g.user["id"])
    return jsonify({
        "sessions": list_experiment_sessions(),
        "claims": live_claims.claims_by_email(),
    })


@admin_api_bp.post("/live-claim")
@staff_required
def live_claim():
    """Take charge of a user. 409 if another staff member already has them."""
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    if not email:
        return json_error("email required", 400)
    ok, holder = live_claims.claim_user(email, g.user["id"], g.user["email"])
    if not ok:
        return json_error(f"this user is being handled by {holder}", 409)
    return jsonify({"ok": True})


@admin_api_bp.post("/live-release")
@staff_required
def live_release():
    """Stop being in charge of a user (only the holder can release)."""
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    if email:
        live_claims.release_user(email, g.user["id"])
    return jsonify({"ok": True})


@admin_api_bp.post("/sessions/<session_id>/rename")
@staff_required
def session_rename_admin(session_id):
    """Staff rename of a user's session (live counselling case label)."""
    data = request.get_json(silent=True) or {}
    title = (data.get("title") or "").strip()
    if not title:
        return json_error("title required", 400)
    if len(title) > 80:
        return json_error("title too long (max 80)", 400)
    row = rename_session_admin(session_id, title)
    if not row:
        return json_error("session not found", 404)
    return jsonify({"ok": True, "title": row["title"]})


# ---------------- JSON API: experiment-mode draft resolution ----------------
@admin_api_bp.post("/review/<message_id>")
@staff_required
def review_resolve(message_id):
    """Approve a pending draft verbatim, or send an edited reply in its place
    (the edit is the feedback; the original draft is recorded as rejected)."""
    data = request.get_json(silent=True) or {}
    action = data.get("action")
    if action == "approve":
        edited = None
    elif action == "edit":
        edited = (data.get("reply") or "").strip()
        if not edited:
            return json_error("edited reply cannot be empty", 400)
        if len(edited) > 4000:
            return json_error("edited reply too long (max 4000)", 400)
    else:
        return json_error("action must be 'approve' or 'edit'", 400)

    outcome, row = resolve_pending_message(message_id, g.user["id"], edited)
    if outcome == "not_found":
        return json_error("message not found", 404)
    if outcome == "conflict":
        return json_error("this reply was already reviewed", 409)
    return jsonify({"ok": True, "status": row["status"]})


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


# ---------------- JSON API: content editors ----------------
def _write_response(ok, failure_message):
    """Editor writes report success as a bool (see admin_repo._attempt)."""
    if ok:
        return jsonify({"ok": True})
    return json_error(failure_message, 500)


def _slug_for(title):
    """Unique slug for editor-created rows (slug is NOT NULL UNIQUE in the DB).
    The random suffix keeps duplicate titles from colliding."""
    base = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-") or "untitled"
    return f"{base[:60]}-{uuid4().hex[:6]}"


def _resource_payload(data):
    return {
        "title": (data.get("title") or "").strip(),
        "category": data.get("category"),
        "summary": data.get("summary"),
        "info": data.get("info"),
        "kind": data.get("kind", "article"),
        "external_url": data.get("external_url"),
        "source": data.get("source"),
        "is_published": bool(data.get("is_published", True)),
    }


@admin_api_bp.get("/resources")
@staff_required
def admin_resources_list():
    return jsonify({"resources": list_all_resources()})


@admin_api_bp.post("/resources")
@staff_required
def admin_resource_create():
    payload = _resource_payload(request.get_json(silent=True) or {})
    if not payload["title"]:
        return json_error("A resource title is required.", 400)
    payload["slug"] = _slug_for(payload["title"])
    return _write_response(create_resource(payload),
                           "Failed to create resource in database.")


@admin_api_bp.post("/resources/<resource_id>")
@staff_required
def admin_resource_update(resource_id):
    payload = _resource_payload(request.get_json(silent=True) or {})
    if not payload["title"]:
        return json_error("A resource title is required.", 400)
    return _write_response(update_resource(resource_id, payload),
                           "Failed to update resource in database.")


@admin_api_bp.delete("/resources/<resource_id>")
@staff_required
def admin_resource_delete(resource_id):
    return _write_response(delete_resource(resource_id),
                           "Failed to delete resource.")


@admin_api_bp.get("/dataset/<dataset_type>")
@staff_required
def get_dashboard_dataset(dataset_type):
    """Page through a local training-data file (JSON array or JSONL)."""
    if dataset_type not in ("chatbot", "classifier"):
        return json_error("Invalid dataset selection", 400)

    file_path = os.path.join(DATASET_DIR, f"{dataset_type}.json")
    if not os.path.exists(file_path):
        return jsonify({"data": [], "total": 0, "page": 1})

    try:
        page = max(1, int(request.args.get("page", 1)))
    except ValueError:
        return json_error("page must be a number", 400)
    per_page = 100

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            try:
                rows = json.load(f)
            except json.JSONDecodeError:
                f.seek(0)
                rows = [json.loads(line) for line in f if line.strip()]

        start = (page - 1) * per_page
        return jsonify({
            "data": rows[start:start + per_page],
            "total": len(rows),
            "page": page,
            "total_pages": (len(rows) + per_page - 1) // per_page,
        })
    except Exception as e:
        return json_error(f"Failed reading local dataset: {str(e)}", 500)


@admin_api_bp.get("/prompts")
@staff_required
def get_dashboard_prompts():
    return jsonify({"data": list_prompts()})


@admin_api_bp.post("/prompts")
@staff_required
def add_dashboard_prompt():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    content = (data.get("content") or "").strip()
    if not name or not content:
        return json_error("Both a prompt name and content are required.", 400)

    # Prompt names double as identifiers, so normalize them on the way in.
    clean_name = name.lower().replace(" ", "_")
    success, error_msg = create_prompt(clean_name, content)
    if success:
        return jsonify({"ok": True, "name": clean_name})
    return json_error(error_msg or "Failed to create prompt.", 500)


@admin_api_bp.post("/prompts/<prompt_name>")
@staff_required
def save_dashboard_prompt(prompt_name):
    data = request.get_json(silent=True) or {}
    content = (data.get("content") or "").strip()
    if not content:
        return json_error("Prompt content cannot be empty.", 400)
    return _write_response(update_prompt(prompt_name, content),
                           "Failed to update prompt.")


@admin_api_bp.delete("/prompts/<prompt_name>")
@staff_required
def remove_dashboard_prompt(prompt_name):
    return _write_response(delete_prompt(prompt_name),
                           "Failed to delete prompt from database.")


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
    return _write_response(update_agreement(agreement_id, content),
                           "Failed to update agreement.")


@admin_api_bp.get("/tests")
@staff_required
def admin_tests_list():
    return jsonify({"data": list_tests()})


@admin_api_bp.post("/tests")
@staff_required
def admin_test_create():
    data = request.get_json(silent=True) or {}
    title = (data.get("title") or "").strip()
    if not title:
        return json_error("A test title is required.", 400)
    payload = {
        "title": title,
        "slug": _slug_for(title),
        "description": data.get("description"),
        "questions": data.get("questions", []),
        "scoring": data.get("scoring", {}),
        "is_published": True,
    }
    return _write_response(create_test(payload),
                           "Failed to create test in database.")


@admin_api_bp.post("/tests/<test_id>")
@staff_required
def admin_test_update(test_id):
    data = request.get_json(silent=True) or {}
    # Only send the fields the client actually provided — a partial update must
    # not null out columns (title is NOT NULL in the DB).
    payload = {k: data[k] for k in ("title", "description", "questions", "scoring")
               if data.get(k) is not None}
    if not payload:
        return json_error("Nothing to update.", 400)
    return _write_response(update_test(test_id, payload),
                           "Failed to update test.")


@admin_api_bp.delete("/tests/<test_id>")
@staff_required
def admin_test_delete(test_id):
    return _write_response(delete_test(test_id), "Failed to delete test.")


@admin_api_bp.get("/activity")
@staff_required
def admin_activity_api():
    """Dashboard graphs: messages + escalations per day (last 14 days)."""
    return jsonify({"days": get_daily_activity()})


# ---------------- JSON API: Suicide Alerts ----------------
@admin_api_bp.get("/alerts/suicide")
@staff_required
def suicide_alerts_api():
    """Escalations per period (?period=today|week|month) with the affected
    users ranked by count and their Suicide Risk Check uptake in that window."""
    period = request.args.get("period", "today")
    if period not in ALERT_PERIOD_DAYS:
        return json_error("period must be today, week, or month", 400)
    return jsonify(get_suicide_alerts(period))


# ---------------- JSON API: user overview + session-analysis report ----------
# Reports are generated ONLY when staff click Generate (one summarizer-model
# call), then kept in this in-memory cache so the PDF download doesn't have to
# regenerate. Single-process, like live_claims; restart clears it.
_report_cache = {}  # user_id -> report dict


@admin_api_bp.get("/users")
@staff_required
def users_overview_api():
    """All registered users with profile info + chat aggregates (the User
    Sessions tab's level-1 list — includes users with no sessions yet)."""
    return jsonify({"users": list_users_overview()})


@admin_api_bp.post("/users/<user_id>/report")
@staff_required
@limiter.limit("6 per minute", key_func=user_or_ip)  # each run = one LLM call
def generate_user_report(user_id):
    """Generate the session-analysis report for one user's recent sessions
    (summarizer model + the 'session_analysis' DB prompt)."""
    from app.agents.report import build_session_report
    report = build_session_report(user_id)
    if report is None:
        return json_error("user not found", 404)
    _report_cache[user_id] = report
    return jsonify({"report": report})


@admin_api_bp.get("/users/<user_id>/report.pdf")
@staff_required
def download_user_report(user_id):
    """The last generated report for this user as a PDF attachment."""
    report = _report_cache.get(user_id)
    if not report:
        return json_error("no report generated yet — click Generate first", 404)
    from app.admin.pdf_report import render_report_pdf
    email = (report["user"].get("email") or "user").split("@")[0]
    date = (report.get("generatedAt") or "")[:10]
    return Response(
        render_report_pdf(report),
        mimetype="application/pdf",
        headers={"Content-Disposition":
                 f'attachment; filename="mindmate_report_{email}_{date}.pdf"'},
    )


# ---------------- JSON API: Test Chat comparison bench ----------------
_BENCH_TABLE_HINT = ("Results were generated but NOT saved: the bench tables "
                     "don't exist yet. Re-run schema.sql in the Supabase SQL "
                     "editor (full reset) to enable saving + ratings.")


@admin_api_bp.get("/bench/sessions")
@staff_required
def bench_sessions_list():
    """This staff member's comparison chats (newest first)."""
    try:
        return jsonify({"available": True,
                        "sessions": list_bench_sessions(g.user["id"])})
    except BenchTableMissing:
        return jsonify({"available": False, "sessions": [],
                        "note": _BENCH_TABLE_HINT})


@admin_api_bp.post("/bench/sessions")
@staff_required
def bench_session_create():
    from app.agents.bench import BENCH_MODES
    data = request.get_json(silent=True) or {}
    mode = data.get("mode")
    if mode not in BENCH_MODES:
        return json_error("mode must be 'models3' or 'single_vs_multi'", 400)
    try:
        row = create_bench_session(g.user["id"], mode)
    except BenchTableMissing:
        return json_error(_BENCH_TABLE_HINT, 503)
    return jsonify({"sessionID": row["id"], "mode": row["mode"],
                    "title": row["title"], "createdAt": row["created_at"]}), 201


@admin_api_bp.post("/bench/sessions/<session_id>/rename")
@staff_required
def bench_session_rename(session_id):
    data = request.get_json(silent=True) or {}
    title = (data.get("title") or "").strip()
    if not title or len(title) > 80:
        return json_error("title required (max 80 chars)", 400)
    row = rename_bench_session(g.user["id"], session_id, title)
    if not row:
        return json_error("comparison chat not found", 404)
    return jsonify({"ok": True, "title": row["title"]})


@admin_api_bp.delete("/bench/sessions/<session_id>")
@staff_required
def bench_session_delete(session_id):
    delete_bench_session(g.user["id"], session_id)
    return jsonify({"ok": True})


@admin_api_bp.get("/bench/sessions/<session_id>")
@staff_required
def bench_session_detail(session_id):
    sess = get_bench_session(g.user["id"], session_id)
    if not sess:
        return json_error("comparison chat not found", 404)
    return jsonify({"session": {"sessionID": sess["id"], "mode": sess["mode"],
                                "title": sess["title"],
                                "createdAt": sess["created_at"]},
                    "turns": get_bench_turns(session_id)})


@admin_api_bp.post("/bench/run")
@staff_required
@limiter.limit("10 per minute", key_func=user_or_ip)  # each run = LLM generations
def bench_run():
    """Run one comparison turn ('models3' or 'single_vs_multi'). With a
    sessionID, each variant continues its own history from the session's
    earlier turns, and the results become the session's next turn. The extra
    models for 'models3' lazy-load on the first run (can take a minute)."""
    from app.agents.bench import BENCH_MODES, run_bench
    data = request.get_json(silent=True) or {}
    mode = data.get("mode")
    message = (data.get("message") or "").strip()
    session_id = (data.get("sessionID") or "").strip() or None
    if mode not in BENCH_MODES:
        return json_error("mode must be 'models3' or 'single_vs_multi'", 400)
    if not message or len(message) > 2000:
        return json_error("message required (max 2000 chars)", 400)

    histories = {}
    if session_id:
        sess = get_bench_session(g.user["id"], session_id)
        if not sess:
            return json_error("comparison chat not found", 404)
        if sess["mode"] != mode:
            return json_error("this comparison chat uses a different mode", 400)
        histories = get_bench_histories(session_id)

    results = run_bench(mode, message, histories)
    run_id = str(uuid4())
    persisted, note, title = True, None, None
    try:
        ids = save_bench_results(g.user["id"], run_id, mode, message, results,
                                 session_id=session_id)
        for r in results:
            r["benchID"] = ids.get(r["variant"])
        # First turn auto-names the comparison chat, like the user chat.
        if session_id and sess["title"] == "New comparison":
            renamed = rename_bench_session(g.user["id"], session_id, message[:40])
            title = renamed and renamed["title"]
    except BenchTableMissing:
        persisted, note = False, _BENCH_TABLE_HINT
    return jsonify({"runID": run_id, "mode": mode, "results": results,
                    "sessionID": session_id, "title": title,
                    "persisted": persisted, "note": note})


@admin_api_bp.post("/bench/<bench_id>/feedback")
@staff_required
def bench_feedback(bench_id):
    """Staff rating (1-5) and/or feedback text for one bench variant."""
    data = request.get_json(silent=True) or {}
    rating = data.get("rating")
    feedback = (data.get("feedback") or "").strip() or None
    if rating is None and feedback is None:
        return json_error("provide a rating or feedback", 400)
    if rating is not None and (not isinstance(rating, int) or not 1 <= rating <= 5):
        return json_error("rating must be an integer from 1 to 5", 400)
    try:
        row = set_bench_feedback(bench_id, rating=rating, feedback=feedback)
    except BenchTableMissing:
        return json_error(_BENCH_TABLE_HINT, 503)
    if not row:
        return json_error("bench result not found", 404)
    return jsonify({"ok": True, "rating": row.get("rating"),
                    "feedback": row.get("feedback")})


@admin_api_bp.get("/analytics/tests")
@staff_required
def admin_test_analytics_api():
    return jsonify({"data": get_test_analytics()})


@admin_api_bp.get("/analytics/tests/<test_id>/attempts")
@staff_required
def admin_test_attempts_api(test_id):
    """Individual logs for one test: every attempt with the answer picked for
    each question (resolved to option labels server-side)."""
    data = get_test_attempts(test_id)
    if data is None:
        return json_error("test not found", 404)
    return jsonify(data)