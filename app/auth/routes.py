"""Auth endpoints: register (email-verified), login, logout, me."""
import re
from flask import Blueprint, request, jsonify, g

from app.auth import service
from app.auth.service import AuthError
from app.auth.decorators import login_required
from app.db.repo import (
    get_profile, get_role, get_active_agreement, record_agreement_acceptance,
)
from app.extensions import limiter
from app.http_utils import json_error

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
# Optional leading +, then 7-15 digits (spaces/dashes are stripped first).
PHONE_RE = re.compile(r"^\+?\d{7,15}$")


def _read_credentials():
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""
    return data, email, password


def _normalize_phone(raw):
    """Strip spaces/dashes/parentheses; return the normalized number or None
    if what's left isn't a plausible phone number."""
    cleaned = re.sub(r"[ \-().]", "", (raw or "").strip())
    return cleaned if PHONE_RE.match(cleaned) else None


@auth_bp.post("/register")
@limiter.limit("10 per minute")
def register():
    data, email, password = _read_credentials()
    if not EMAIL_RE.match(email):
        return json_error("A valid email address is required.", 400)
    if len(password) < 6:
        return json_error("Password must be at least 6 characters.", 400)
    phone = _normalize_phone(data.get("phone"))
    if not phone:
        return json_error("A valid phone number is required "
                          "(7-15 digits, e.g. +60123456789).", 400)
    if not data.get("agree"):
        return json_error("You must accept the User Agreement to register.", 400)

    try:
        result = service.register(email, password, phone=phone)
    except AuthError as e:
        return json_error(e.message, e.status)

    # Record acceptance of the current active agreement (server decides which).
    agreement = get_active_agreement()
    if agreement and result.get("user_id"):
        try:
            record_agreement_acceptance(result["user_id"], agreement["id"])
        except Exception:
            pass  # don't fail registration if acceptance logging hiccups

    if result["needs_verification"]:
        return jsonify({
            "needsVerification": True,
            "message": "Account created! Check your email for a verification "
                       "link, then log in.",
        }), 201

    # Email confirmation disabled on the project -> already logged in.
    return jsonify({
        "needsVerification": False,
        "token": result["access_token"],
        "refreshToken": result["refresh_token"],
        "message": "Account created!",
    }), 201


@auth_bp.post("/login")
@limiter.limit("10 per minute")
def login():
    _data, email, password = _read_credentials()
    if not email or not password:
        return json_error("Email and password are required.", 400)

    try:
        result = service.login(email, password)
    except AuthError as e:
        return json_error(e.message, e.status)

    return jsonify({
        "token": result["access_token"],
        "refreshToken": result["refresh_token"],
        "user": {"id": result["user_id"], "email": result["email"]},
        "role": get_role(result["user_id"]),
    })


@auth_bp.post("/logout")
@login_required
def logout():
    # Stateless from the server's view: the client discards the token.
    return jsonify({"ok": True})


@auth_bp.get("/me")
@login_required
def me():
    profile = get_profile(g.user["id"]) or {}
    return jsonify({
        "id": g.user["id"],
        "email": g.user["email"],
        "role": profile.get("role", "user"),
        "phone": profile.get("phone"),
    })
