"""Graph nodes: each takes the ChatState and returns only the keys it adds.

Wiring lives in graph.py; the safety rules live in guards.py; model access
goes through the chains in chains.py (which carry their own retry + stub
fallback policies). Keeping nodes this thin makes them independently testable
and lets the graph be re-wired without touching behavior.
"""
from app.agents import chains
from app.agents.guards import crisis_keywords_present, reply_extras
from app.config import Config
from app.db.repo import add_message, get_history

# How many recent (user, bot) turns the chatbot sees VERBATIM — configured in
# config.yaml (memory.recent_turns, hybrid memory: 2). Older turns reach it
# only through the compressed summary; 0 would mean summary-only memory.
RECENT_TURNS = Config.RECENT_TURNS


# ---------------------------------------------------------------------------
# Context + diagnostics
# ---------------------------------------------------------------------------
def with_memory_window(history):
    """A history -> the context keys the rest of the pipeline runs on: the
    verbatim window the chatbot sees, and the full list the summary is built
    from. Separate from the DB read so a caller that already HAS the history
    (the staff bench) reuses this rule instead of restating it. (list[-0:] is
    the WHOLE list in Python, so RECENT_TURNS == 0 is handled explicitly.)"""
    recent = history[-RECENT_TURNS:] if RECENT_TURNS > 0 else []
    return {"history": history, "recent": recent}


def load_context(state):
    """Full session history, split into the verbatim window the chatbot sees
    and the remainder that only reaches it through the summary."""
    return with_memory_window(
        get_history(state["user_id"], state["session_id"], limit=None))


def diagnose(state):
    """Emotion + suicide-risk classification of the incoming message."""
    return {"diag": chains.diagnose_chain.invoke(state["message"])}


def route_turn(state):
    """Conditional edge: crisis escalation short-circuits generation;
    everything else (greetings included — the welcome words are a frontend
    empty-state, not a pipeline branch) goes through the full pipeline."""
    if state["diag"].get("risk_flag") or crisis_keywords_present(state["message"]):
        return "crisis"
    return "chat"


# ---------------------------------------------------------------------------
# Short-circuit reply
# ---------------------------------------------------------------------------
def crisis_reply(state):
    """Fixed crisis message with helplines — generation is skipped entirely."""
    return {"reply": Config.CRISIS_MESSAGE, "escalated": True, "summary": None}


# ---------------------------------------------------------------------------
# Full pipeline: summarize -> generate
# ---------------------------------------------------------------------------
def summarize(state):
    """Compress the turns OUTSIDE the verbatim window into long-term memory,
    so the summary never duplicates what the chatbot already sees in full."""
    full = state["history"]
    older = full[:-RECENT_TURNS] if RECENT_TURNS > 0 else list(full)
    if older:
        summary = chains.summarize_chain.invoke({"history": older})
    elif not full:
        summary = ("This is the user's first message — the conversation is "
                   "just beginning.")
    else:
        summary = "The conversation has only just begun (a few messages so far)."
    return {"summary": summary}


def generate(state):
    """One companion reply. Prompt composition (DB template + tone + summary)
    happens inside reply_chain, so the same chain is reusable stand-alone
    (e.g. batched over a test set in the evaluation notebooks)."""
    reply = chains.reply_chain.invoke({
        "message": state["message"],
        "history": state["recent"],
        "turn_count": len(state["history"]),
        "emotion": state["diag"]["emotion"],
        "summary": state["summary"],
    })
    return {"reply": reply, "escalated": False}


# ---------------------------------------------------------------------------
# Persistence + API payload (all paths converge here)
# ---------------------------------------------------------------------------
def persist(state):
    """Store the turn and shape the API response.

    mode='multi' (normal): the reply is stored and returned immediately.
    mode='experiment' (supervised): the pipeline output is held as a PENDING
    draft that a staff psychologist must approve/edit before the user sees a
    reply — including crisis escalations (held by design; the review queue
    pins them first). The payload deliberately leaks nothing about the draft.
    """
    diag = state["diag"]
    common = dict(
        emotion=diag["emotion"], confidence=diag["confidence"],
        escalated=state["escalated"], summary=state.get("summary"),
    )

    # Crisis escalation: email the counselling info to the user (fire-and-
    # forget, .env-toggled, cooldown inside). Sent in experiment mode too —
    # the crisis is real even while the reply waits for counsellor review.
    if state["escalated"]:
        from app.email_utils import notify_crisis
        notify_crisis(state["user_id"])

    if state["mode"] == "experiment":
        row = add_message(state["user_id"], state["session_id"],
                          state["message"], None,
                          status="pending", draft_reply=state["reply"], **common)
        return {"payload": {"messageID": row["id"], "status": "pending"}}

    row = add_message(state["user_id"], state["session_id"],
                      state["message"], state["reply"], **common)
    payload = {
        "messageID": row["id"],
        "reply": state["reply"],
        "emotion": diag["emotion"],
        "confidence": diag["confidence"],
        "escalated": state["escalated"],
    }
    # Crisis turns point the user at the in-app Suicide Risk Check quiz.
    # The frontend renders this as a link on the reply.
    payload.update(reply_extras(state["escalated"]))
    return {"payload": payload}
