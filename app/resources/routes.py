"""Resource endpoints: mental-health info cards + their 'steps to overcome' tab.

Read-only for everyone signed in. Writing is admin-only (RLS + future admin UI).
"""
from flask import Blueprint, jsonify

from app.auth.decorators import login_required
from app.db.repo import list_resources, get_resource
from app.http_utils import json_error

# /api prefix keeps this JSON API distinct from the GET /resources HTML page.
resources_bp = Blueprint("resources", __name__, url_prefix="/api/resources")


@resources_bp.get("")
@login_required
def list_all():
    return jsonify({"resources": list_resources()})


@resources_bp.get("/<resource_id>")
@login_required
def get_one(resource_id):
    resource = get_resource(resource_id)
    if not resource:
        return json_error("resource not found", 404)
    return jsonify(resource)
