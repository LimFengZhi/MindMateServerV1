"""Admin/staff data access, kept separate from the user-facing repo.py so an
admin feature can never accidentally widen a user-scoped query.

Dashboard endpoints return aggregates (counts); the session-review functions
expose transcripts to staff BY DESIGN (counselling review + reply feedback) —
they are only reachable through staff_required routes.
"""
from datetime import datetime, timezone

from app.db.repo import APIError, _none_if_bad_uuid
from app.extensions import get_sb


def _retry_once(call):
    """Supabase's pooled HTTP connections can die while idle (httpx 'server
    disconnected' errors); one immediate retry runs on a fresh connection.
    Real Postgres errors (APIError) are never retried."""
    try:
        return call()
    except APIError:
        raise
    except Exception:
        return call()


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
        "pendingReviews": _count("messages", status="pending"),
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
    rows = (_retry_once(lambda: get_sb().table("profiles")
                        .select("id, email").execute())).data or []
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
        res = _retry_once(lambda: get_sb().table("sessions")
                          .select("id, user_id, title, mode, created_at")
                          .eq("id", session_id)
                          .limit(1)
                          .execute())
    except APIError as e:
        return _none_if_bad_uuid(e)
    if not res.data:
        return None
    s = res.data[0]
    emails = _emails_by_user()
    msgs = (_retry_once(lambda: get_sb().table("messages")
                        .select("id, question, reply, draft_reply, status, reviewed_at, "
                                "emotion, emotion_confidence, escalated, rating, feedback, "
                                "created_at")
                        .eq("session_id", session_id)
                        .order("created_at", desc=False)
                        .execute())).data or []
    return {
        "session": {
            "sessionID": s["id"],
            "title": s.get("title") or "New chat",
            "mode": s.get("mode") or "multi",
            "createdAt": s.get("created_at"),
            "email": emails.get(s["user_id"]) or "unknown",
        },
        "messages": [{
            "messageID": m["id"],
            "question": m["question"],
            "reply": m.get("reply"),
            "draft": m.get("draft_reply"),
            "status": m.get("status") or "delivered",
            "reviewedAt": m.get("reviewed_at"),
            "emotion": m.get("emotion"),
            "confidence": m.get("emotion_confidence"),
            "escalated": bool(m.get("escalated")),
            "rating": m.get("rating"),
            "feedback": m.get("feedback"),
            "createdAt": m.get("created_at"),
        } for m in msgs],
    }


# ---------------------------------------------------------------------------
# Live counselling (staff): connect to a user's experiment chat
# ---------------------------------------------------------------------------
def list_experiment_sessions():
    """Every experiment-mode session with its owner email, message count and
    how many turns still await review — the 'choose a user to connect' list."""
    sessions = (_retry_once(lambda: get_sb().table("sessions")
                            .select("id, user_id, title, created_at")
                            .eq("mode", "experiment")
                            .order("created_at", desc=True)
                            .execute())).data or []
    emails = _emails_by_user()
    msgs = (_retry_once(lambda: get_sb().table("messages")
                        .select("session_id, status")
                        .execute())).data or []
    counts, pending = {}, {}
    for m in msgs:
        sid = m["session_id"]
        counts[sid] = counts.get(sid, 0) + 1
        if m.get("status") == "pending":
            pending[sid] = pending.get(sid, 0) + 1
    return [{
        "sessionID": s["id"],
        "title": s.get("title") or "New chat",
        "email": emails.get(s["user_id"]) or "unknown",
        "createdAt": s.get("created_at"),
        "messageCount": counts.get(s["id"], 0),
        "pendingCount": pending.get(s["id"], 0),
    } for s in sessions]


def rename_session_admin(session_id, title):
    """Staff rename of ANY session (used from the live counselling view)."""
    try:
        upd = (get_sb().table("sessions")
               .update({"title": title})
               .eq("id", session_id)
               .execute())
    except APIError as e:
        return _none_if_bad_uuid(e)
    return upd.data[0] if upd.data else None


# ---------------------------------------------------------------------------
# Draft resolution (staff): approve/replace a pending experiment-mode turn
# ---------------------------------------------------------------------------
def resolve_pending_message(message_id, reviewer_id, edited_reply=None):
    """Approve (edited_reply=None) or replace a pending draft.

    Returns ("ok", row) on success, ("conflict", row) if another staff member
    already resolved it, ("not_found", None) if the message doesn't exist.
    The UPDATE is conditioned on status='pending' so two simultaneous reviews
    can't both win — the loser's update matches zero rows.
    """
    try:
        res = _retry_once(lambda: get_sb().table("messages")
                          .select("id, status, draft_reply")
                          .eq("id", message_id)
                          .limit(1)
                          .execute())
    except APIError as e:
        return ("not_found", _none_if_bad_uuid(e))
    if not res.data:
        return ("not_found", None)
    row = res.data[0]
    if row["status"] != "pending":
        return ("conflict", row)

    if edited_reply is None:
        # Approve: deliver the draft verbatim.
        update = {"status": "approved", "reply": row.get("draft_reply")}
    else:
        # Edit: the staff text is delivered; the draft is recorded as rejected.
        update = {"status": "rejected", "reply": edited_reply}
    update["reviewed_by"] = reviewer_id
    update["reviewed_at"] = datetime.now(timezone.utc).isoformat()

    upd = _retry_once(lambda: get_sb().table("messages")
                      .update(update)
                      .eq("id", message_id)
                      .eq("status", "pending")   # the race guard
                      .execute())
    if not upd.data:
        # Zero rows: another staff member won the race — OR our first attempt
        # committed and only its response was lost before the retry. Check who
        # actually reviewed it before calling it a conflict.
        check = _retry_once(lambda: get_sb().table("messages")
                            .select("id, status, reply, reviewed_by")
                            .eq("id", message_id)
                            .limit(1)
                            .execute())
        settled = check.data[0] if check.data else None
        if settled and settled.get("reviewed_by") == reviewer_id:
            return ("ok", settled)
        return ("conflict", settled or row)
    return ("ok", upd.data[0])


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


# ---------------------------------------------------------------------------
# Content editors (staff): resources, prompts, agreements, tests
# ---------------------------------------------------------------------------
def _attempt(write):
    """Run one Supabase write, reporting success as a bool. The editor
    endpoints turn False into a generic 500 rather than leaking DB errors."""
    try:
        write()
        return True
    except Exception:
        return False


def list_all_resources():
    res = (get_sb().table("resources")
           .select("*")
           .order("sort_order", desc=False)
           .execute())
    return res.data or []


def create_resource(data):
    return _attempt(lambda: get_sb().table("resources").insert(data).execute())


def update_resource(resource_id, data):
    return _attempt(lambda: get_sb().table("resources")
                    .update(data).eq("id", resource_id).execute())


def delete_resource(resource_id):
    return _attempt(lambda: get_sb().table("resources")
                    .delete().eq("id", resource_id).execute())


# Prompts are keyed by their `key` column (the editor passes keys as ids) —
# the same identifier the app's prompt loader resolves ('composed', 'summarise').
def list_prompts():
    return (get_sb().table("prompts").select("*").execute()).data or []


def create_prompt(name, content):
    """Returns (ok, error_message) so a duplicate name gets a clear message."""
    try:
        existing = get_sb().table("prompts").select("key").eq("key", name).execute()
        if existing.data:
            return False, "A prompt with this name already exists."
        get_sb().table("prompts").insert({"key": name, "content": content}).execute()
        return True, None
    except Exception as e:
        return False, str(e)


def update_prompt(name, content):
    return _attempt(lambda: get_sb().table("prompts")
                    .update({"content": content}).eq("key", name).execute())


def delete_prompt(name):
    return _attempt(lambda: get_sb().table("prompts")
                    .delete().eq("key", name).execute())


def list_agreements():
    return (get_sb().table("agreements").select("*").execute()).data or []


def update_agreement(agreement_id, content):
    return _attempt(lambda: get_sb().table("agreements")
                    .update({"content": content}).eq("id", agreement_id).execute())


def list_tests():
    return (get_sb().table("test").select("*").execute()).data or []


def create_test(data):
    return _attempt(lambda: get_sb().table("test").insert(data).execute())


def update_test(test_id, data):
    return _attempt(lambda: get_sb().table("test")
                    .update(data).eq("id", test_id).execute())


def delete_test(test_id):
    return _attempt(lambda: get_sb().table("test")
                    .delete().eq("id", test_id).execute())


# ---------------------------------------------------------------------------
# Test analytics (staff)
# ---------------------------------------------------------------------------
def _test_attempt_rows():
    """Completed attempts with the owning test's title (FK-embedded)."""
    try:
        res = (get_sb().table("test_created")
               .select("score, band, created_at, test(title)")
               .execute())
        return res.data or []
    except Exception:
        return []


def get_test_analytics():
    """Per-test aggregate: {title: {total_takes, total_score, avg_score,
    bands: {band: count}}}. Attempts whose test was deleted are skipped."""
    analytics = {}
    for row in _test_attempt_rows():
        test_info = row.get("test")
        if not test_info:
            continue
        title = test_info.get("title", "Unknown Assessment")
        stats = analytics.setdefault(
            title, {"total_takes": 0, "total_score": 0, "bands": {}})
        stats["total_takes"] += 1
        stats["total_score"] += row.get("score") or 0
        band = row.get("band") or "Unscored"
        stats["bands"][band] = stats["bands"].get(band, 0) + 1

    for stats in analytics.values():
        takes = stats["total_takes"]
        stats["avg_score"] = round(stats["total_score"] / takes, 1) if takes else 0
    return analytics