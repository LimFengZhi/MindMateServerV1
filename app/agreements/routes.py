"""Agreement endpoint. Public on purpose: the register page must show the
active User Agreement before the user has an account."""
from flask import Blueprint, jsonify

from app.db.repo import get_active_agreement
from app.http_utils import json_error

agreements_bp = Blueprint("agreements", __name__, url_prefix="/agreements")


@agreements_bp.get("/active")
def active():
    agreement = get_active_agreement()
    if not agreement:
        return json_error("no active agreement", 404)
    return jsonify({
        "id": agreement["id"],
        "version": agreement["version"],
        "title": agreement["title"],
        "content": agreement["content"],
    })
