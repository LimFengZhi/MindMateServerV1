"""Rule-based fallbacks for every model.

Each stub takes the SAME input dict as the chain it backs in chains.py, so
`.with_fallbacks([RunnableLambda(stub)])` can swap them freely. With
AI_MODE=stub the app runs entirely on these and boots instantly.
"""
from app.agents.guards import crisis_keywords_present

# ---------------------------------------------------------------------------
# Diagnostic (emotion + risk)
# ---------------------------------------------------------------------------
# keyword -> emotion. Order matters (first match wins per group).
_STUB_RULES = [
    ("Anxiety", ["anxious", "anxiety", "panic", "nervous", "worry", "worried",
                 "on edge", "racing", "scared", "afraid"]),
    ("Stress", ["stress", "stressed", "overwhelm", "pressure", "deadline",
                "too much", "burnt out", "burned out", "exhausted"]),
    ("Depression", ["depress", "hopeless", "empty", "worthless", "numb",
                    "no point", "can't go on", "sad", "down", "lonely", "tired of"]),
    ("Bipolar", ["manic", "mania", "bipolar", "mood swing"]),
]


def diagnose(text):
    lowered = (text or "").lower()
    if crisis_keywords_present(text):
        return {"emotion": "Suicidal", "confidence": 0.9,
                "risk_flag": True, "risk_confidence": 0.9}
    for emotion, keywords in _STUB_RULES:
        if any(k in lowered for k in keywords):
            return {"emotion": emotion, "confidence": 0.55,
                    "risk_flag": False, "risk_confidence": 0.0}
    return {"emotion": "Normal", "confidence": 0.5,
            "risk_flag": False, "risk_confidence": 0.0}


# ---------------------------------------------------------------------------
# Summarizer (long-term memory)
# ---------------------------------------------------------------------------
def summarize(history):
    """Deterministic paraphrase built from the user's turns."""
    user_turns = [u for u, _ in history if u]
    joined = " ".join(user_turns)
    snippet = joined[:280].rsplit(" ", 1)[0] if len(joined) > 280 else joined
    safety = ("a possible safety signal was mentioned"
              if any(crisis_keywords_present(u) for u in user_turns)
              else "No safety signals detected.")
    return (f"The user has shared the following so far: {snippet}. "
            f"Safety status: {safety}")


# ---------------------------------------------------------------------------
# Chatbot (companion reply)
# ---------------------------------------------------------------------------
_OPENERS = [
    "Thank you for sharing that with me.",
    "I'm really glad you put that into words.",
    "I hear you, and what you said matters.",
    "Thanks for trusting me with this.",
    "I'm here with you on this.",
]

_QUESTIONS = [
    "What's been weighing on you the most about it?",
    "Can you tell me a little more about what that's been like for you?",
    "What feels most important for you to talk through right now?",
    "When did you first start noticing this?",
    "What's been on your mind the most lately?",
]

_CRISIS = (
    "I can hear how much pain you're in right now, and I'm really glad you told "
    "me. You don't have to carry this alone — I'm staying right here with you."
)


def generate(inputs):
    """A warm, reflective responder. `inputs` matches reply_chain's input:
    {message, history, turn_count, emotion, summary}. Variety comes from
    `turn_count` (the FULL conversation length) because `history` is only the
    verbatim window, which is empty in summary-only mode (RECENT_TURNS=0)."""
    if crisis_keywords_present(inputs["message"]):
        return _CRISIS
    turn = inputs.get("turn_count", 0)
    return f"{_OPENERS[turn % len(_OPENERS)]} {_QUESTIONS[turn % len(_QUESTIONS)]}"
