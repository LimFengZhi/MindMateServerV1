"""Application factory. Each setup concern lives in its own small helper so
create_app reads as an overview."""
import os

from flask import Flask, jsonify, render_template, redirect, request, send_from_directory

from app.config import Config
from app.extensions import limiter
from app.http_utils import json_error
from app.agents.registry import registry


def create_app(load_models=True, seed=True):
    app = Flask(
        __name__,
        static_folder="static",
        static_url_path="/static",
        template_folder="templates",
    )
    app.config.from_object(Config)  # includes MAX_CONTENT_LENGTH

    limiter.init_app(app)

    if seed:
        _seed_database()
    if load_models:
        # Load ML models when AI_MODE=real (no-op + instant in stub mode).
        registry.load_all()

    _register_pages(app)
    _register_blueprints(app)
    _register_security_headers(app)
    _register_error_handlers(app)
    return app


def _seed_database():
    """Seed the agreement, prompts, and self-tests (idempotent; resources
    are owned by scripts/scrape_resources.py, never seeded here)."""
    try:
        from app.db.seed import ensure_seed
        ensure_seed()
    except Exception as e:
        print(f"[seed] skipped ({type(e).__name__}: {e}). "
              f"Has schema.sql been run in Supabase yet?")


def _register_pages(app):
    """HTML pages plus bundled assets and the health probe."""

    @app.route("/")
    def root():
        return redirect("/chat")

    # min_age reaches the date-of-birth field as a data attribute so the
    # client-side courtesy check uses the SAME number as the server (the real
    # gate is profile_utils.dob_error). Tuned in config.yaml, not here.
    @app.route("/login")
    def login_page():
        return render_template("login.html", min_age=Config.PROFILE_MIN_AGE)

    @app.route("/chat")
    def chat_page():
        return render_template("chat.html")

    @app.route("/analysis")
    def analysis_page():
        return render_template("analysis.html")

    @app.route("/resources")
    def resources_page():
        return render_template("resources.html")

    @app.route("/profile")
    def profile_page():
        return render_template("profile.html", min_age=Config.PROFILE_MIN_AGE)

    # Serve bundled assets (logo, etc.) from app/assets/.
    @app.route("/assets/<path:filename>")
    def assets(filename):
        return send_from_directory(os.path.join(app.root_path, "assets"), filename)

    # Favicon: reuse the logo. Covers the browser's implicit /favicon.ico request.
    @app.route("/favicon.ico")
    def favicon():
        return send_from_directory(
            os.path.join(app.root_path, "assets", "images"),
            "logo.png", mimetype="image/png")

    @app.route("/health")
    def health():
        return jsonify({
            "status": "ok",
            "ai_mode": Config.AI_MODE,
            "models": {
                "chatbot": registry.chatbot_ready,
                "classifier": registry.classifier_ready,
                "summarizer": registry.summarizer_ready,
                "voice": registry.voice_ready,
            },
        })


def _register_blueprints(app):
    from app.admin.routes import admin_bp, admin_api_bp
    from app.auth.routes import auth_bp
    from app.chat.routes import chat_bp
    from app.sessions.routes import sessions_bp
    from app.resources.routes import resources_bp
    from app.resources.self_test.routes import self_test_bp
    from app.agreements.routes import agreements_bp
    app.register_blueprint(admin_bp)
    app.register_blueprint(admin_api_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(chat_bp)
    app.register_blueprint(sessions_bp)
    app.register_blueprint(resources_bp)
    app.register_blueprint(self_test_bp)
    app.register_blueprint(agreements_bp)


def _register_security_headers(app):
    # CSP allows 'unsafe-inline' because the UI uses inline onclick handlers and
    # style attributes; output is HTML-escaped in JS (see static/js/common.js).
    # It still restricts sources (fonts, images) for defense-in-depth.
    csp = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' https: data:; "
        "connect-src 'self'; base-uri 'self'; form-action 'self'; "
        "frame-ancestors 'none'"
    )

    @app.after_request
    def security_headers(resp):
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Referrer-Policy"] = "no-referrer"
        resp.headers["Content-Security-Policy"] = csp
        if request.is_secure:
            resp.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return resp


def _register_error_handlers(app):
    # Body-too-large -> JSON instead of an HTML error page.
    @app.errorhandler(413)
    def too_large(_e):
        return json_error("request body too large", 413)

    # Any unhandled exception (e.g. a transient Supabase error) -> clean JSON
    # so the front-end's api() helper always gets parseable output.
    _TRANSIENT_ERRORS = {
        # httpx transport failures from a dropped Supabase connection: the
        # request is safe to retry, so say that instead of "internal error".
        "RemoteProtocolError", "ReadError", "WriteError", "ConnectError",
        "ReadTimeout", "ConnectTimeout", "PoolTimeout",
    }

    @app.errorhandler(Exception)
    def on_error(e):
        from werkzeug.exceptions import HTTPException
        if isinstance(e, HTTPException):
            return json_error(e.description, e.code)
        if type(e).__name__ in _TRANSIENT_ERRORS:
            app.logger.warning("Transient DB connection error: %r", e)
            return json_error("temporary connection problem — please try again", 503)
        app.logger.exception("Unhandled error")
        return json_error("internal server error", 500)
