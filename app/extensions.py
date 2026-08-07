"""Shared singletons: the Supabase service client and a rate limiter.

Both are created here (not in __init__.py) to avoid circular imports with the
blueprint modules that need them.
"""
from supabase import create_client, Client
from app.config import Config

# ---------------------------------------------------------------------------
# Supabase service client (uses the secret key -> bypasses RLS).
# Ownership is enforced in the Flask layer (db/repo.py + auth/decorators.py).
# ---------------------------------------------------------------------------
_sb: Client | None = None


def get_sb() -> Client:
    global _sb
    if _sb is None:
        Config.validate()
        _sb = create_client(Config.SUPABASE_URL, Config.SUPABASE_SECRET_KEY)
    return _sb


def new_auth_client() -> Client:
    """A short-lived client for sign-in / sign-up.

    Uses the publishable/anon key when configured (least privilege for the
    user-facing auth flow), falling back to the secret key otherwise. Either
    way it's a throwaway client so sign_in_with_password doesn't mutate the
    shared service client's session.
    """
    auth_key = Config.SUPABASE_ANON_KEY or Config.SUPABASE_SECRET_KEY
    return create_client(Config.SUPABASE_URL, auth_key)


# ---------------------------------------------------------------------------
# Rate limiter. flask-limiter is optional: if it isn't installed the app still
# runs, just without per-route limits. Install flask-limiter to enable them.
#
# storage_uri is "memory://" ON PURPOSE (it is also the default, but stating it
# silences flask-limiter's "not recommended for production" warning, which it
# prints whenever storage is unspecified — it cannot tell how many workers run).
# The app is intentionally SINGLE-PROCESS: run it with one worker. Counters are
# per-process, so several workers would each grant the full quota. The limiter
# is not alone in this — live_claims.py (staff claims), email_utils._last_sent
# (crisis-email cooldown) and admin/routes._report_cache all live in process
# memory too. Going multi-worker means moving ALL of them to shared storage,
# not just swapping this line for a redis:// URI.
# ---------------------------------------------------------------------------
try:
    from flask_limiter import Limiter
    from flask_limiter.util import get_remote_address

    limiter = Limiter(key_func=get_remote_address, default_limits=["300 per hour"],
                      storage_uri="memory://")
except ImportError:  # pragma: no cover - graceful degradation
    class _NoopLimiter:
        """Drop-in no-op so @limiter.limit(...) decorators keep working."""

        def init_app(self, app):
            pass

        def limit(self, *args, **kwargs):
            def decorator(fn):
                return fn
            return decorator

    limiter = _NoopLimiter()
