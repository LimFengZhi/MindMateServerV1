"""Staff-only admin site: the /admin page shell + its JSON API.

Roles: 'staff' can view the dashboard; 'admin' can additionally create staff
accounts by email (and remove staff access). Promote the first admin in
Supabase: update public.profiles set role = 'admin' where email = '…';
The page itself is a static shell — every piece of data comes from the guarded
/api/admin endpoints, so the real access control is server-side.
"""
from flask import Blueprint, render_template, request, jsonify

from app.admin.service import create_staff_account
from app.auth.decorators import staff_required, admin_required
from app.auth.routes import EMAIL_RE
from app.auth.service import AuthError
from app.db.admin_repo import get_stats, list_staff_accounts, set_role
from app.db.repo import get_profile
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


# ---------------- JSON API ----------------
@admin_api_bp.get("/stats")
@staff_required
def stats():
    return jsonify(get_stats())


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
