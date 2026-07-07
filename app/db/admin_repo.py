"""Admin/staff data access, kept separate from the user-facing repo.py so an
admin feature can never accidentally widen a user-scoped query.

Everything here returns aggregates (counts) — no message content, no
per-user answers.
"""
from app.extensions import get_sb


def _count(table, **filters):
    q = get_sb().table(table).select("id", count="exact").limit(1)
    for column, value in filters.items():
        q = q.eq(column, value)
    return q.execute().count or 0


def get_stats():
    """Aggregate counts for the staff dashboard."""
    return {
        "users": _count("profiles"),
        "sessions": _count("sessions"),
        "messages": _count("messages"),
        "escalations": _count("messages", escalated=True),
        "testsTaken": _count("test_created"),
        "resources": _count("resources"),
    }


# ---------------------------------------------------------------------------
# Staff-account management (admin only)
# ---------------------------------------------------------------------------
def list_staff_accounts():
    res = (get_sb().table("profiles")
           .select("id, email, role, created_at")
           .in_("role", ["staff", "admin"])
           .order("created_at", desc=False)
           .execute())
    return res.data or []


def get_profile_by_email(email):
    res = (get_sb().table("profiles")
           .select("*")
           .eq("email", email)
           .limit(1)
           .execute())
    return res.data[0] if res.data else None


def set_role(user_id, role):
    get_sb().table("profiles").update({"role": role}).eq("id", user_id).execute()
