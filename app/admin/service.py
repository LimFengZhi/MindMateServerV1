"""Admin-side account management: create staff logins by email.

Uses the Supabase service client's auth admin API (the service key allows
creating users directly). The account is created already confirmed — the admin
hands the temporary password to the staff member. If the email already has an
account, it is promoted to staff instead.
"""
from app.auth.service import AuthError
from app.db.admin_repo import get_profile_by_email, set_role
from app.extensions import get_sb


def create_staff_account(email, password):
    """Create (or promote) a staff account. Returns {"promoted": bool}."""
    existing = get_profile_by_email(email)
    if existing:
        if existing.get("role") in ("staff", "admin"):
            raise AuthError("That account is already staff.", 409)
        set_role(existing["id"], "staff")
        return {"promoted": True}

    # New account: the password is what the staff member will log in with.
    if len(password) < 6:
        raise AuthError("Password must be at least 6 characters for a new "
                        "account.", 400)
    try:
        res = get_sb().auth.admin.create_user({
            "email": email,
            "password": password,
            "email_confirm": True,  # staff logins skip the verification email
        })
    except Exception as e:
        msg = str(e).lower()
        if "already" in msg or "exists" in msg:
            raise AuthError("That email already has an account.", 409)
        raise AuthError("Could not create the staff account. Please try "
                        "again.", 400)

    user = getattr(res, "user", None)
    if not user:
        raise AuthError("Could not create the staff account. Please try "
                        "again.", 400)

    # The DB trigger has already created the profile row; flip its role.
    set_role(user.id, "staff")
    return {"promoted": False}
