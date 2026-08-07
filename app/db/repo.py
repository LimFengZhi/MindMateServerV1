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


class SessionDeleted(Exception):
    """The turn's session vanished mid-write (the user deleted the chat while
    its reply was still generating). Routes map this to a clean 404 instead of
    letting the foreign-key APIError bubble up as a 500."""


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


def _execute_or_none(query):
    """Run one lookup whose id comes from the URL: returns the response, or
    None when the id was a malformed UUID. Any other APIError still raises
    (see _none_if_bad_uuid). Shared by every by-id read below."""
    try:
        return query.execute()
    except APIError as e:
        return _none_if_bad_uuid(e)


# ---------------------------------------------------------------------------
# Profiles / roles
# ---------------------------------------------------------------------------
def get_profile(user_id):
    res = get_sb().table("profiles").select("*").eq("id", user_id).limit(1).execute()
    return res.data[0] if res.data else None


# Columns a user may change about themselves. `role` and `email` are absent on
# purpose: role must never be self-assignable, and email belongs to Supabase
# Auth. The route validates the VALUES; this set is the hard boundary on WHICH
# columns can be touched, so a crafted request can't reach anything else.
EDITABLE_PROFILE_FIELDS = frozenset(
    {"display_name", "phone", "gender", "date_of_birth"})


def update_profile(user_id, updates):
    """Owner-scoped profile edit. Returns the updated row, or None if nothing
    was writable or the id was malformed."""
    safe = {k: v for k, v in updates.items() if k in EDITABLE_PROFILE_FIELDS}
    if not safe:
        return None
    res = _execute_or_none(get_sb().table("profiles")
                           .update(safe)
                           .eq("id", user_id))
    if res is None:
        return None
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
           .select("id, title, mode, created_at")
           .eq("user_id", user_id)
           .order("created_at", desc=True)
           .execute())
    return res.data or []


def get_session(user_id, session_id):
    """Owner-scoped read: returns the session only if it belongs to user_id."""
    res = _execute_or_none(get_sb().table("sessions")
                           .select("*")
                           .eq("id", session_id)
                           .eq("user_id", user_id)
                           .limit(1))
    if res is None:
        return None
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
                confidence=None, escalated=False, summary=None,
                status="delivered", draft_reply=None):
    """Insert one turn. Normal chats: status='delivered' and draft_reply falls
    back to the reply itself. Experiment chats: reply=None + status='pending'
    with the pipeline output held in draft_reply until staff resolve it.

    Raises SessionDeleted if the session row is gone by the time the reply is
    ready (the user deleted the chat while the model was still generating)."""
    try:
        res = (get_sb().table("messages")
               .insert({
                   "user_id": user_id,
                   "session_id": session_id,
                   "question": question,
                   "reply": reply,
                   "draft_reply": draft_reply if draft_reply is not None else reply,
                   "status": status,
                   "emotion": emotion,
                   "emotion_confidence": confidence,
                   "escalated": escalated,
                   "summary": summary,
               })
               .execute())
    except APIError as e:
        # 23503 = foreign-key violation: the session (or user) row disappeared
        # between the ownership check at request start and this insert.
        if getattr(e, "code", None) == "23503":
            raise SessionDeleted(session_id) from e
        raise
    return _first(res)


def set_message_feedback(message_id, rating=None, feedback=None, feedback_by=None):
    """Attach feedback (rating 1-5 + text + the user who gave it) to a message.

    Used by the staff review tools (/api/admin). Only the provided fields are
    written, so a rating-only save never wipes existing feedback text (and
    vice versa). `feedback_by` is the userID giving it.
    """
    if rating is not None and not (1 <= int(rating) <= 5):
        raise ValueError("rating must be between 1 and 5")
    update = {
        "feedback_by": feedback_by,
        "feedback_at": datetime.now(timezone.utc).isoformat(),
    }
    if rating is not None:
        update["rating"] = rating
    if feedback is not None:
        update["feedback"] = feedback
    res = _execute_or_none(get_sb().table("messages")   # bad id -> not found
                           .update(update)
                           .eq("id", message_id))
    if res is None:
        return None
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


def _public_status(db_status):
    """The user-facing status. approved/rejected are staff-side detail — the
    user only ever learns 'pending' vs 'delivered', never that a counsellor
    replaced the draft."""
    return "pending" if db_status == "pending" else "delivered"


def _reply_extras(row):
    """Turn metadata shared by transcript + pending payloads: the suggested
    Suicide Risk Check link is derived from the persisted escalated column,
    so it survives reloads identically to the live reply — same guards helper
    the live payload uses. The import stays function-local: app.agents pulls
    in repo.py during its own init, so hoisting it would tie this module to
    that import order."""
    from app.agents.guards import reply_extras
    return reply_extras(bool(row.get("escalated")))


def get_transcript(user_id, session_id):
    """Ordered turns for rebuilding the chat view."""
    rows = _session_messages(user_id, session_id)
    return [{
        "messageID": r["id"],
        "question": r["question"],
        "status": _public_status(r.get("status")),
        "reply": (dict({"reply": r.get("reply"),
                        "escalated": bool(r.get("escalated"))}, **_reply_extras(r))
                  if r.get("reply") is not None else None),
        "created_at": r.get("created_at"),
    } for r in rows]


def get_pending_status(user_id, session_id):
    """Poll payload for an experiment chat: the state of every reviewed turn.

    Turns still pending come back minimal; resolved turns carry everything the
    chat page needs to swap the waiting bubble for the real reply. Never
    exposes draft_reply or the approved/rejected distinction.
    """
    res = (get_sb().table("messages")
           .select("id, status, reply, emotion, emotion_confidence, escalated")
           .eq("user_id", user_id)
           .eq("session_id", session_id)
           .in_("status", ["pending", "approved", "rejected"])
           .order("created_at", desc=False)
           .execute())
    out = []
    for r in (res.data or []):
        if r["status"] == "pending":
            out.append({"messageID": r["id"], "status": "pending"})
        else:
            out.append(dict({
                "messageID": r["id"],
                "status": "delivered",
                "reply": r.get("reply"),
                "emotion": r.get("emotion"),
                "confidence": r.get("emotion_confidence"),
                "escalated": bool(r.get("escalated")),
            }, **_reply_extras(r)))
    return out


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


def _looks_like_uuid(value):
    parts = str(value).split("-")
    return len(parts) == 5 and len(str(value).replace("-", "")) == 32


def _get_published_by_id_or_slug(table, ident):
    """One published row, addressed by either a UUID id or a human-friendly
    slug — the shared shape behind get_resource/get_test. None if not found
    or the id was malformed."""
    q = get_sb().table(table).select("*").eq("is_published", True).limit(1)
    key = "id" if _looks_like_uuid(ident) else "slug"
    res = _execute_or_none(q.eq(key, ident))
    if res is None or not res.data:
        return None
    return res.data[0]


def get_resource(resource_id):
    """Fetch one resource (by id or slug) plus its ordered steps."""
    resource = _get_published_by_id_or_slug("resources", resource_id)
    if resource is None:
        return None
    steps = (get_sb().table("resource_steps")
             .select("step_order, title, content")
             .eq("resource_id", resource["id"])
             .order("step_order", desc=False)
             .execute())
    resource["steps"] = steps.data or []
    return resource


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
    return _get_published_by_id_or_slug("test", test_id)


def save_test_result(user_id, test_id, answers, score, band):
    """Record one completed attempt in test_created."""
    get_sb().table("test_created").insert({
        "user_id": user_id,
        "test_id": test_id,
        "answer": answers,
        "score": score,
        "band": band,
    }).execute()
