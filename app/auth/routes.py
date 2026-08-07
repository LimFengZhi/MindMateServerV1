"""Auth endpoints: register (email-verified), login, logout, me."""
import re
from flask import Blueprint, request, jsonify, g

from app.auth import service
from app.auth.service import AuthError
from app.auth.decorators import login_required
from app.db.repo import (
    get_profile, get_role, get_active_agreement, record_agreement_acceptance,
    update_profile,
)
from app.extensions import limiter
from app.http_utils import json_error
from app.profile_utils import GENDERS, age_from_dob, dob_error, parse_dob

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
# Optional leading +, then 7-15 digits (spaces/dashes are stripped first).
PHONE_RE = re.compile(r"^\+?\d{7,15}$")
MAX_NAME_LEN = 60


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

    # Profile details. All required, like phone — the trigger in schema.sql
    # copies them out of the signup metadata into profiles.
    name = (data.get("name") or "").strip()
    if not name:
        return json_error("Your name is required.", 400)
    if len(name) > MAX_NAME_LEN:
        return json_error(f"Name must be {MAX_NAME_LEN} characters or fewer.", 400)
    phone = _normalize_phone(data.get("phone"))
    if not phone:
        return json_error("A valid phone number is required "
                          "(7-15 digits, e.g. +60123456789).", 400)
    gender = (data.get("gender") or "").strip()
    if gender not in GENDERS:
        return json_error("Please select a gender.", 400)
    dob_problem = dob_error(data.get("dateOfBirth"))
    if dob_problem:
        return json_error(dob_problem, 400)
    dob = parse_dob(data.get("dateOfBirth"))

    if not data.get("agree"):
        return json_error("You must accept the User Agreement to register.", 400)

    try:
        result = service.register(email, password, phone=phone, name=name,
                                  gender=gender, date_of_birth=dob.isoformat())
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


def _public_profile(user_id, email, profile):
    """The profile shape the user's own pages read. `age` is derived, never
    stored (see profile_utils)."""
    return {
        "id": user_id,
        "email": email,
        "role": profile.get("role", "user"),
        "name": profile.get("display_name"),
        "phone": profile.get("phone"),
        "gender": profile.get("gender"),
        "dateOfBirth": profile.get("date_of_birth"),
        "age": age_from_dob(profile.get("date_of_birth")),
        "joinedAt": profile.get("created_at"),
    }


@auth_bp.get("/me")
@login_required
def me():
    profile = get_profile(g.user["id"]) or {}
    return jsonify(_public_profile(g.user["id"], g.user["email"], profile))


@auth_bp.patch("/me")
@login_required
def update_me():
    """Edit your own details from the profile page. Email, role and the join
    date are NOT editable here — email is Supabase's to change, and role must
    never be self-assignable. Only the fields actually sent are written."""
    data = request.get_json(silent=True) or {}
    updates = {}

    if "name" in data:
        name = (data.get("name") or "").strip()
        if not name:
            return json_error("Your name is required.", 400)
        if len(name) > MAX_NAME_LEN:
            return json_error(f"Name must be {MAX_NAME_LEN} characters or fewer.", 400)
        updates["display_name"] = name

    if "phone" in data:
        phone = _normalize_phone(data.get("phone"))
        if not phone:
            return json_error("A valid phone number is required "
                              "(7-15 digits, e.g. +60123456789).", 400)
        updates["phone"] = phone

    if "gender" in data:
        if data.get("gender") not in GENDERS:
            return json_error("Please select a gender.", 400)
        updates["gender"] = data["gender"]

    if "dateOfBirth" in data:
        problem = dob_error(data.get("dateOfBirth"))
        if problem:
            return json_error(problem, 400)
        updates["date_of_birth"] = parse_dob(data["dateOfBirth"]).isoformat()

    if not updates:
        return json_error("Nothing to update.", 400)

    profile = update_profile(g.user["id"], updates)
    if profile is None:
        return json_error("Could not save your details.", 500)
    return jsonify(_public_profile(g.user["id"], g.user["email"], profile))
