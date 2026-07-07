"""Tiny HTTP helpers shared by all route modules."""
from flask import jsonify


def json_error(message, status):
    """Standard JSON error body, so every endpoint fails the same way."""
    return jsonify({"error": message}), status
