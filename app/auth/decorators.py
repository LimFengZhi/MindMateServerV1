"""Route guards.

login_required validates the Supabase token and populates g.user.
session_required additionally checks that the <session_id> in the URL belongs
to the caller and loads the row into g.session.
staff_required additionally checks the profile role (admin site).
"""
from functools import wraps
from flask import request, g

from app.auth.service import get_user_from_token
from app.db.repo import get_role, get_session
from app.http_utils import json_error

STAFF_ROLES = {"staff", "admin"}


def _bearer_token():
    auth = request.headers.get("Authorization", "")
    return auth[7:].strip() if auth.startswith("Bearer ") else None


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        user = get_user_from_token(_bearer_token())
        if not user:
            return json_error("invalid or missing token", 401)
        g.user = user
        return fn(*args, **kwargs)
    return wrapper


def staff_required(fn):
    """login_required + the caller's Supabase profile role must be staff/admin.

    The role is read from the profiles table on every request, so demoting a
    staff member takes effect immediately.
    """
    @login_required
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if get_role(g.user["id"]) not in STAFF_ROLES:
            return json_error("staff access required", 403)
        return fn(*args, **kwargs)
    return wrapper


def admin_required(fn):
    """login_required + role must be 'admin' (staff-account management)."""
    @login_required
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if get_role(g.user["id"]) != "admin":
            return json_error("admin access required", 403)
        return fn(*args, **kwargs)
    return wrapper


def session_required(fn):
    """login_required + ownership check on the route's <session_id>."""
    @login_required
    @wraps(fn)
    def wrapper(*args, session_id, **kwargs):
        session = get_session(g.user["id"], session_id)
        if not session:
            return json_error("invalid session", 403)
        g.session = session
        return fn(*args, session_id=session_id, **kwargs)
    return wrapper


def get_owned_session(session_id):
    """Return the session if it exists and belongs to g.user, else None.

    For routes that read the session id from the request body/form instead of
    the URL (the chat endpoints); URL-based routes use @session_required.
    """
    return get_session(g.user["id"], session_id)
