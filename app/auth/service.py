"""Authentication via Supabase Auth (GoTrue).

Registration sends an email-verification link; users cannot sign in until they
confirm. Tokens are Supabase-issued JWTs, validated on each request by
get_user_from_token().
"""
from app.config import Config
from app.extensions import get_sb, new_auth_client

# The auth error class moved around across supabase-py versions; import
# defensively so a version bump never breaks the app.
try:
    from supabase_auth.errors import AuthApiError
except Exception:  # pragma: no cover
    try:
        from gotrue.errors import AuthApiError
    except Exception:
        AuthApiError = Exception


class AuthError(Exception):
    """Raised for any auth failure; carries a user-safe message + HTTP status."""

    def __init__(self, message, status=400):
        super().__init__(message)
        self.message = message
        self.status = status


def register(email, password, phone=None):
    """Create an account and trigger the verification email.

    `phone` travels as signup metadata: the handle_new_user trigger copies it
    into profiles.phone, so it is stored even before the email is verified.

    Returns a dict describing whether verification is still pending. If the
    project has email confirmation disabled, Supabase returns a session and the
    user is logged in immediately.
    """
    client = new_auth_client()
    try:
        res = client.auth.sign_up({
            "email": email,
            "password": password,
            "options": {
                "email_redirect_to": Config.SITE_URL + "/login",
                "data": {"phone": phone} if phone else {},
            },
        })
    except AuthApiError as e:
        msg = str(e).lower()
        if "rate limit" in msg or "too many" in msg or "over_email_send_rate_limit" in msg:
            # Supabase's email service is throttled (the built-in SMTP allows
            # only a few signup emails per hour). Surface a clear 429.
            raise AuthError(
                "Too many verification emails have been sent from this project "
                "recently. Please wait a while and try again, or configure a "
                "custom SMTP provider in Supabase.", 429)
        if "already registered" in msg or "already been registered" in msg or \
                ("user" in msg and "exists" in msg):
            # Avoid an account-enumeration oracle: respond exactly as a fresh
            # sign-up would. Supabase won't re-send a link to a confirmed user.
            return {"user_id": None, "email": email, "needs_verification": True,
                    "access_token": None, "refresh_token": None}
        raise AuthError(_friendly(str(e)), 400)

    user = getattr(res, "user", None)
    if not user:
        raise AuthError("Could not create the account. Please try again.", 400)

    session = getattr(res, "session", None)
    return {
        "user_id": user.id,
        "email": user.email,
        "needs_verification": session is None,
        "access_token": getattr(session, "access_token", None) if session else None,
        "refresh_token": getattr(session, "refresh_token", None) if session else None,
    }


def login(email, password):
    """Exchange email + password for a Supabase access token."""
    client = new_auth_client()
    try:
        res = client.auth.sign_in_with_password({"email": email, "password": password})
    except AuthApiError as e:
        msg = str(e).lower()
        if "not confirmed" in msg or "not verified" in msg:
            raise AuthError(
                "Please verify your email first — check your inbox for the "
                "confirmation link.", 403)
        raise AuthError("Invalid email or password.", 401)

    session = getattr(res, "session", None)
    if not session or not getattr(session, "access_token", None):
        raise AuthError(
            "Please verify your email first — check your inbox for the "
            "confirmation link.", 403)

    return {
        "access_token": session.access_token,
        "refresh_token": session.refresh_token,
        "user_id": res.user.id,
        "email": res.user.email,
    }


def get_user_from_token(token):
    """Validate a Supabase JWT and return its user, or None if invalid/expired."""
    if not token:
        return None
    try:
        res = get_sb().auth.get_user(token)
    except Exception:
        return None
    user = getattr(res, "user", None)
    if not user:
        return None
    return {"id": user.id, "email": user.email}


def _friendly(message):
    low = message.lower()
    # Note: the "already registered" case is intercepted in register() to avoid
    # account enumeration, so it is intentionally not surfaced here.
    if "password" in low and ("least" in low or "weak" in low or "6" in low):
        return "Password is too weak — use at least 6 characters."
    if "invalid" in low and "email" in low:
        return "That email address doesn't look valid."
    return message or "Registration failed."
