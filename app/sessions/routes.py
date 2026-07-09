"""Session CRUD + transcript + per-session emotion analysis.

Every <session_id> route uses @session_required, which rejects sessions the
caller doesn't own and exposes the row as g.session.
"""
from flask import Blueprint, request, jsonify, g

from app.auth.decorators import login_required, session_required
from app.chat.routes import user_or_ip
from app.db.repo import (
    create_session, list_sessions, rename_session, delete_session,
    get_transcript, get_analysis, get_pending_status,
)
from app.extensions import limiter
from app.http_utils import json_error

sessions_bp = Blueprint("sessions", __name__, url_prefix="/sessions")

MAX_TITLE_LEN = 80
SESSION_MODES = {"multi", "experiment"}


def _public(session):
    """The client-facing shape of a session row."""
    return {
        "sessionID": session["id"],
        "title": session.get("title", "New chat"),
        "mode": session.get("mode") or "multi",
        "createdAt": session.get("created_at"),
    }


@sessions_bp.get("")
@login_required
def list_my_sessions():
    sessions = list_sessions(g.user["id"])
    return jsonify({"sessions": [_public(s) for s in sessions]})


@sessions_bp.post("")
@login_required
def new_session():
    data = request.get_json(silent=True) or {}
    title = (data.get("title") or "New chat").strip()[:MAX_TITLE_LEN] or "New chat"
    mode = (data.get("mode") or "multi").strip()
    if mode not in SESSION_MODES:
        return json_error("mode must be 'multi' or 'experiment'", 400)
    session = create_session(g.user["id"], title=title, mode=mode)
    return jsonify(_public(session)), 201


@sessions_bp.patch("/<session_id>")
@session_required
def rename_my_session(session_id):
    data = request.get_json(silent=True) or {}
    title = (data.get("title") or "").strip()
    if not title:
        return json_error("title required", 400)
    if len(title) > MAX_TITLE_LEN:
        return json_error(f"title too long (max {MAX_TITLE_LEN})", 400)
    rename_session(g.user["id"], session_id, title)
    return jsonify({"ok": True, "title": title})


@sessions_bp.delete("/<session_id>")
@session_required
def delete_my_session(session_id):
    delete_session(g.user["id"], session_id)
    return jsonify({"ok": True})


@sessions_bp.get("/<session_id>/messages")
@session_required
def session_messages(session_id):
    return jsonify({"turns": get_transcript(g.user["id"], session_id)})


@sessions_bp.get("/<session_id>/pending")
@session_required
@limiter.limit("40 per minute", key_func=user_or_ip)  # chat polls every ~3s
def session_pending(session_id):
    """Experiment-mode poll: the review state of this chat's supervised turns."""
    return jsonify({"messages": get_pending_status(g.user["id"], session_id)})


@sessions_bp.get("/<session_id>/analysis")
@session_required
def session_analysis(session_id):
    data = get_analysis(g.user["id"], session_id)
    data["title"] = g.session.get("title", "New chat")
    return jsonify(data)
