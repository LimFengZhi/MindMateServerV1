"""Multi-agent pipeline: diagnostic -> routing(escalation) -> summarize ->
prompt build -> chatbot, then persist the turn."""
import re

from app.agents.chatbot_agent import chatbot_agent, WELCOME_MESSAGE
from app.agents.diagnostic_agent import diagnostic_agent
from app.agents.summarize_agent import summarize_agent
from app.agents.routing import routing2
from app.prompt_builder.loader import build_composed_system
from app.db.repo import get_history, add_message

# A bare greeting with no content to reflect on ("Hi", "hello!", "good morning").
_GREETING_RE = re.compile(
    r"^(hi+|hey+|hello+|hiya|yo|howdy|sup|what'?s\s+up|"
    r"good\s+(morning|afternoon|evening))(\s+there)?[\s!.,:;~-]*$",
    re.IGNORECASE,
)

# How many recent (user, bot) turns the chatbot sees VERBATIM. Everything else
# is carried only via the compressed summary.
#   RECENT_TURNS = 0  -> SUMMARY-ONLY memory (no verbatim turns; the model never
#                        sees its own prior replies, so it can't imitate their
#                        length, and the rules stay next to the current message).
#   RECENT_TURNS > 0  -> summary + that many recent pairs kept word-for-word.
RECENT_TURNS = 0


def run_multi(user_id, session_id, message, diag=None):
    # Split the session history into a verbatim recent window + the older turns
    # that get compressed into the summary. (list[-0:] is the WHOLE list in
    # Python, so RECENT_TURNS == 0 is handled explicitly as "no verbatim turns".)
    full_history = get_history(user_id, session_id, limit=None)
    if RECENT_TURNS > 0:
        history = full_history[-RECENT_TURNS:]
        older = full_history[:-RECENT_TURNS]
    else:
        history = []                 # summary-only: nothing verbatim
        older = list(full_history)   # the summary covers ALL prior turns

    # 1. Diagnostic agent -> emotion + risk
    if diag is None:
        diag = diagnostic_agent.run(message)

    # 2. Routing layer 2 -> escalate before generating anything
    escalate, crisis_msg = routing2.run(diag, message)
    if escalate:
        return {
            "reply": crisis_msg,
            "emotion": diag["emotion"],
            "confidence": diag["confidence"],
            "risk_flag": True,
            "escalated": True,
            "summary": None,
        }

    # 2b. First-turn bare greeting -> the fixed welcome, skipping generation.
    #     Nearly all fine-tuning examples are long emotional disclosures, so a
    #     small tuned model met with just "Hi" invents a backstory to counsel.
    if not full_history and _GREETING_RE.match(message.strip()):
        return {
            "reply": WELCOME_MESSAGE,
            "emotion": diag["emotion"],
            "confidence": diag["confidence"],
            "risk_flag": diag["risk_flag"],
            "escalated": False,
            "summary": None,
        }

    # 3. Summarize only the OLDER turns (those beyond the verbatim window), so
    #    the summary is the long-term memory and doesn't duplicate the recent
    #    turns the chatbot already sees in full.
    if older:
        summary = summarize_agent.run(older)
    elif not full_history:
        summary = "This is the user's first message — the conversation is just beginning."
    else:
        summary = "The conversation has only just begun (a few messages so far)."

    # 4. Build the system prompt (loader converts the raw label to a tone hint).
    system_prompt = build_composed_system(diag["emotion"], summary)

    # 5. Chatbot agent
    reply = chatbot_agent.run(system_prompt, history, message)

    return {
        "reply": reply,
        "emotion": diag["emotion"],
        "confidence": diag["confidence"],
        "risk_flag": diag["risk_flag"],
        "escalated": False,
        "summary": summary,
    }


def answer(user_id, session_id, message, mode="multi"):
    """Run the pipeline, persist the turn, and return the API payload.

    mode='multi' (normal): the reply is stored and returned immediately.
    mode='experiment' (supervised): the pipeline output is held as a PENDING
    draft that a staff psychologist must approve/edit before the user sees a
    reply — including crisis escalations (held by design; the review queue
    pins them first). The payload deliberately leaks nothing about the draft.
    """
    result = run_multi(user_id, session_id, message)

    if mode == "experiment":
        row = add_message(
            user_id, session_id, message, None,
            emotion=result["emotion"], confidence=result["confidence"],
            escalated=result["escalated"], summary=result.get("summary"),
            status="pending", draft_reply=result["reply"],
        )
        return {"messageID": row["id"], "status": "pending"}

    row = add_message(
        user_id, session_id, message, result["reply"],
        emotion=result["emotion"], confidence=result["confidence"],
        escalated=result["escalated"], summary=result.get("summary"),
    )

    return {
        "messageID": row["id"],
        "reply": result["reply"],
        "emotion": result["emotion"],
        "confidence": result["confidence"],
        "escalated": result["escalated"],
    }
