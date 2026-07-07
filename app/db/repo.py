"""Data-access layer. Every Supabase table read/write lives here so routes stay
thin and the storage details are in one place.

The backend uses the Supabase *service* key (bypasses RLS), so every
user-scoped query filters by user_id explicitly — that is what actually
enforces ownership.
"""
from datetime import datetime, timezone

from app.extensions import get_sb

# APIError import path has moved across postgrest versions; import defensively.
try:
    from postgrest.exceptions import APIError
except Exception:  # pragma: no cover
    try:
        from postgrest import APIError
    except Exception:
        class APIError(Exception):
            code = None


def _first(res):
    """Return the first row of an insert/update representation, or raise a clear
    error if Postgres returned nothing (e.g. the insert was silently rejected)."""
    if not res.data:
        raise RuntimeError("database write returned no row")
    return res.data[0]


def _none_if_bad_uuid(exc):
    """A malformed UUID in a Postgres uuid column raises 22P02. For lookups by
    an externally-supplied id, treat that as 'not found' (None) rather than a
    500. Re-raise anything else."""
    code = getattr(exc, "code", None)
    msg = str(exc).lower()
    if code == "22P02" or "invalid input syntax for type uuid" in msg:
        return None
    raise exc


# ---------------------------------------------------------------------------
# Profiles / roles
# ---------------------------------------------------------------------------
def get_profile(user_id):
    res = get_sb().table("profiles").select("*").eq("id", user_id).limit(1).execute()
    return res.data[0] if res.data else None


def get_role(user_id):
    profile = get_profile(user_id)
    return (profile or {}).get("role", "user")


# ---------------------------------------------------------------------------
# Agreements
# ---------------------------------------------------------------------------
def get_active_agreement():
    res = (get_sb().table("agreements")
           .select("*")
           .eq("is_active", True)
           .order("created_at", desc=True)
           .limit(1)
           .execute())
    return res.data[0] if res.data else None


def record_agreement_acceptance(user_id, agreement_id):
    get_sb().table("agreement_acceptances").upsert(
        {"user_id": user_id, "agreement_id": agreement_id},
        on_conflict="user_id,agreement_id",
    ).execute()


# ---------------------------------------------------------------------------
# Prompts (agent system prompts, editable in the Supabase dashboard)
# ---------------------------------------------------------------------------
def get_prompt(key):
    res = (get_sb().table("prompts")
           .select("key, content")
           .eq("key", key)
           .limit(1)
           .execute())
    return res.data[0] if res.data else None


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------
def create_session(user_id, title="New chat", mode="multi"):
    res = (get_sb().table("sessions")
           .insert({"user_id": user_id, "title": title, "mode": mode})
           .execute())
    return _first(res)


def list_sessions(user_id):
    res = (get_sb().table("sessions")
           .select("id, title, created_at")
           .eq("user_id", user_id)
           .order("created_at", desc=True)
           .execute())
    return res.data or []


def get_session(user_id, session_id):
    """Owner-scoped read: returns the session only if it belongs to user_id."""
    try:
        res = (get_sb().table("sessions")
               .select("*")
               .eq("id", session_id)
               .eq("user_id", user_id)
               .limit(1)
               .execute())
    except APIError as e:
        return _none_if_bad_uuid(e)
    return res.data[0] if res.data else None


def rename_session(user_id, session_id, title):
    (get_sb().table("sessions")
     .update({"title": title})
     .eq("id", session_id)
     .eq("user_id", user_id)
     .execute())


def delete_session(user_id, session_id):
    # messages are removed by the ON DELETE CASCADE foreign key.
    (get_sb().table("sessions")
     .delete()
     .eq("id", session_id)
     .eq("user_id", user_id)
     .execute())


# ---------------------------------------------------------------------------
# Messages (one row per conversation turn)
# ---------------------------------------------------------------------------
def add_message(user_id, session_id, question, reply, emotion=None,
                confidence=None, escalated=False, summary=None):
    res = (get_sb().table("messages")
           .insert({
               "user_id": user_id,
               "session_id": session_id,
               "question": question,
               "reply": reply,
               "emotion": emotion,
               "emotion_confidence": confidence,
               "escalated": escalated,
               "summary": summary,
           })
           .execute())
    return _first(res)


def set_message_feedback(message_id, rating=None, feedback=None, feedback_by=None):
    """Attach feedback (rating 1-5 + text + the user who gave it) to a message.

    Not wired into a route in this app yet — provided so a future app/feature can
    record feedback against a response. `feedback_by` is the userID giving it.
    """
    if rating is not None and not (1 <= int(rating) <= 5):
        raise ValueError("rating must be between 1 and 5")
    update = {
        "rating": rating,
        "feedback": feedback,
        "feedback_by": feedback_by,
        "feedback_at": datetime.now(timezone.utc).isoformat(),
    }
    res = (get_sb().table("messages")
           .update(update)
           .eq("id", message_id)
           .execute())
    return res.data[0] if res.data else None


def _session_messages(user_id, session_id):
    res = (get_sb().table("messages")
           .select("*")
           .eq("user_id", user_id)
           .eq("session_id", session_id)
           .order("created_at", desc=False)
           .execute())
    return res.data or []


def get_history(user_id, session_id, limit=10):
    """Past (question, reply) turns for this session, oldest first.

    limit caps the number of recent turns returned; pass limit=None for the
    FULL history (used to build the long-term summary, which must see old turns).
    """
    rows = _session_messages(user_id, session_id)
    # Filter on the (always-present) question, not the reply, so an empty-string
    # reply still counts — keeps history consistent with transcript/analysis.
    turns = [(r["question"], r.get("reply") or "") for r in rows if r.get("question")]
    return turns if limit is None else turns[-limit:]


def get_transcript(user_id, session_id):
    """Ordered turns for rebuilding the chat view."""
    rows = _session_messages(user_id, session_id)
    return [{
        "question": r["question"],
        "reply": ({"reply": r.get("reply"), "escalated": bool(r.get("escalated"))}
                  if r.get("reply") is not None else None),
        "created_at": r.get("created_at"),
    } for r in rows]


def get_analysis(user_id, session_id):
    """Per-message emotion data plus an aggregated summary for one session."""
    rows = _session_messages(user_id, session_id)
    messages = []
    counts = {}
    escalations = 0
    for r in rows:
        emotion = r.get("emotion") or "Unknown"
        escalated = bool(r.get("escalated"))
        if escalated:
            escalations += 1
        counts[emotion] = counts.get(emotion, 0) + 1
        messages.append({
            "question": r["question"],
            "emotion": emotion,
            "confidence": r.get("emotion_confidence"),
            "escalated": escalated,
            "created_at": r.get("created_at"),
        })
    dominant = max(counts, key=counts.get) if counts else None
    return {
        "messages": messages,
        "summary": {
            "total": len(messages),
            "counts": counts,
            "dominant": dominant,
            "escalations": escalations,
        },
    }


# ---------------------------------------------------------------------------
# Resources
# ---------------------------------------------------------------------------
def list_resources():
    res = (get_sb().table("resources")
           .select("id, slug, title, category, summary, image_url, sort_order, "
                   "kind, external_url, source")
           .eq("is_published", True)
           .order("sort_order", desc=False)
           .order("created_at", desc=False)
           .execute())
    return res.data or []


def get_resource(resource_id):
    """Fetch one resource (by id or slug) plus its ordered steps."""
    q = get_sb().table("resources").select("*").eq("is_published", True).limit(1)
    # Accept either a UUID id or a human-friendly slug.
    key = "slug" if not _looks_like_uuid(resource_id) else "id"
    try:
        res = q.eq(key, resource_id).execute()
    except APIError as e:
        return _none_if_bad_uuid(e)
    if not res.data:
        return None
    resource = res.data[0]
    steps = (get_sb().table("resource_steps")
             .select("step_order, title, content")
             .eq("resource_id", resource["id"])
             .order("step_order", desc=False)
             .execute())
    resource["steps"] = steps.data or []
    return resource


def _looks_like_uuid(value):
    parts = str(value).split("-")
    return len(parts) == 5 and len(str(value).replace("-", "")) == 32


# ---------------------------------------------------------------------------
# Self-tests (see app/resources/self_test/)
# ---------------------------------------------------------------------------
def list_tests():
    res = (get_sb().table("test")
           .select("*")
           .eq("is_published", True)
           .order("sort_order", desc=False)
           .execute())
    return res.data or []


def get_test(test_id):
    """Fetch one test by id or slug."""
    q = get_sb().table("test").select("*").eq("is_published", True).limit(1)
    key = "slug" if not _looks_like_uuid(test_id) else "id"
    try:
        res = q.eq(key, test_id).execute()
    except APIError as e:
        return _none_if_bad_uuid(e)
    return res.data[0] if res.data else None


def save_test_result(user_id, test_id, answers, score, band):
    """Record one completed attempt in test_created."""
    get_sb().table("test_created").insert({
        "user_id": user_id,
        "test_id": test_id,
        "answer": answers,
        "score": score,
        "band": band,
    }).execute()
