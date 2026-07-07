"""Admin/staff data access, kept separate from the user-facing repo.py so an
admin feature can never accidentally widen a user-scoped query.

Dashboard endpoints return aggregates (counts); the session-review functions
expose transcripts to staff BY DESIGN (counselling review + reply feedback) —
they are only reachable through staff_required routes.
"""
from app.db.repo import APIError, _none_if_bad_uuid
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
# Emotion analysis across ALL users (staff)
# ---------------------------------------------------------------------------
def get_emotion_overview():
    """Emotion distribution + escalation count over every message."""
    rows = (get_sb().table("messages")
            .select("emotion, escalated")
            .execute()).data or []
    counts = {}
    escalations = 0
    for r in rows:
        emotion = r.get("emotion") or "Unknown"
        counts[emotion] = counts.get(emotion, 0) + 1
        if r.get("escalated"):
            escalations += 1
    dominant = max(counts, key=counts.get) if counts else None
    return {"total": len(rows), "counts": counts,
            "dominant": dominant, "escalations": escalations}


# ---------------------------------------------------------------------------
# Session review (staff): list every session, read one transcript
# ---------------------------------------------------------------------------
def _emails_by_user():
    rows = (get_sb().table("profiles").select("id, email").execute()).data or []
    return {p["id"]: p.get("email") for p in rows}


def list_all_sessions():
    """Every user's sessions, newest first, with owner email, message count,
    and how many replies already carry staff feedback (rating or text)."""
    sessions = (get_sb().table("sessions")
                .select("id, user_id, title, created_at")
                .order("created_at", desc=True)
                .execute()).data or []
    emails = _emails_by_user()
    msgs = (get_sb().table("messages")
            .select("session_id, rating, feedback")
            .execute()).data or []
    counts, reviewed = {}, {}
    for m in msgs:
        sid = m["session_id"]
        counts[sid] = counts.get(sid, 0) + 1
        if m.get("rating") is not None or m.get("feedback"):
            reviewed[sid] = reviewed.get(sid, 0) + 1
    return [{
        "sessionID": s["id"],
        "title": s.get("title") or "New chat",
        "createdAt": s.get("created_at"),
        "email": emails.get(s["user_id"]) or "unknown",
        "messageCount": counts.get(s["id"], 0),
        "reviewedCount": reviewed.get(s["id"], 0),
    } for s in sessions]


def get_session_review(session_id):
    """One session's transcript with diagnostic + feedback fields, or None."""
    try:
        res = (get_sb().table("sessions")
               .select("id, user_id, title, created_at")
               .eq("id", session_id)
               .limit(1)
               .execute())
    except APIError as e:
        return _none_if_bad_uuid(e)
    if not res.data:
        return None
    s = res.data[0]
    emails = _emails_by_user()
    msgs = (get_sb().table("messages")
            .select("id, question, reply, emotion, emotion_confidence, "
                    "escalated, rating, feedback, created_at")
            .eq("session_id", session_id)
            .order("created_at", desc=False)
            .execute()).data or []
    return {
        "session": {
            "sessionID": s["id"],
            "title": s.get("title") or "New chat",
            "createdAt": s.get("created_at"),
            "email": emails.get(s["user_id"]) or "unknown",
        },
        "messages": [{
            "messageID": m["id"],
            "question": m["question"],
            "reply": m.get("reply"),
            "emotion": m.get("emotion"),
            "confidence": m.get("emotion_confidence"),
            "escalated": bool(m.get("escalated")),
            "rating": m.get("rating"),
            "feedback": m.get("feedback"),
            "createdAt": m.get("created_at"),
        } for m in msgs],
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
