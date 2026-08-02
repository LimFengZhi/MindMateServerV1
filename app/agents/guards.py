"""Pure safety / risk / cleanup helpers.

No ML or LangChain imports here — everything is a regex or a rule, importable
from anywhere (repo.py, routes, notebooks) without pulling in torch. These run
REGARDLESS of AI_MODE, which is what makes them safety layers rather than
model features.
"""
import re

# ---------------------------------------------------------------------------
# Crisis detection (safety layer 1 — lexical net)
# ---------------------------------------------------------------------------
# Explicit self-harm / suicide language. ML classifiers trained on long posts
# miss short direct statements, so this lexical net is a safety backstop: if
# any of these appear the turn escalates no matter what the classifier says.
CRISIS_PATTERNS = re.compile(
    r"\b("
    r"kill(ing)?\s+my\s*self|kill\s+myself|"
    r"end(ing)?\s+my\s+life|take\s+my\s+(own\s+)?life|"
    r"want(ing)?\s+to\s+die|wanna\s+die|don'?t\s+want\s+to\s+(live|be\s+alive)|"
    r"better\s+off\s+dead|"
    r"suicid(e|al)|kms|"
    r"hurt(ing)?\s+my\s*self|harm(ing)?\s+my\s*self|cut(ting)?\s+my\s*self|"
    r"no\s+reason\s+to\s+live|don'?t\s+want\s+to\s+go\s+on|end\s+it\s+all"
    r")\b",
    re.IGNORECASE,
)


def crisis_keywords_present(text):
    """True if the raw message contains explicit self-harm / suicide language."""
    return bool(text and CRISIS_PATTERNS.search(text))


# ---------------------------------------------------------------------------
# Suicide Risk Check suggestion (safety layer 3 — soft nudge)
# ---------------------------------------------------------------------------
# Slug of the in-app self-test suggested when suicide risk looks elevated.
RISK_CHECK_SLUG = "suicide-risk-check"


def needs_risk_check(escalated):
    """True when a turn should carry a link to the Suicide Risk Check quiz:
    every escalated (crisis) turn. Used for the live reply payload AND when
    rebuilding transcripts, so the link survives a reload (both read the same
    persisted escalated flag)."""
    return bool(escalated)


# ---------------------------------------------------------------------------
# Generation cleanup + case-note detection (fine-tune habits)
# ---------------------------------------------------------------------------
# The MentalChat16K training data contains literal template tokens like
# "[Name]" / "[Age]" (372 in the raw dump), and the fine-tune emits them.
_PLACEHOLDER_RE = re.compile(r"\[[A-Za-z][A-Za-z '/]{0,24}\]")

# Another MentalChat16K habit: given a content-poor message the fine-tune
# sometimes answers in third-person case-note style ("User has experienced
# grief...", "The patient describes...") — imitating the dataset's
# clinical-summary input fields — and invents a backstory the user never gave.
# A companion must address the user directly, so any reply that narrates the
# user in third person is treated as a failed generation.
# (Requires "the patient/client", so "be patient with yourself" stays fine.)
CASE_NOTES_RE = re.compile(
    r"^(?:the\s+)?(?:user|patient|client)\b"     # opens by narrating the user
    r"|\bthe\s+(?:patient|client)\b",            # or refers to them mid-reply
    re.IGNORECASE,
)

# Shown when even the retry generation comes back as case notes.
CASE_NOTES_FALLBACK = (
    "Thank you for telling me — I'm here with you. Would you share a little "
    "more about what's been going on for you today?"
)


def tidy_reply(text):
    """Clean a raw generation: drop leaked template tokens, then cut any
    half-finished sentence left behind by the max_new_tokens cap."""
    # "rawDesc" is another literal artifact the fine-tune emits; everything
    # after it is derailed continuation (URLs, unrelated stories), so cut there.
    t = text.split("rawDesc", 1)[0]
    t = _PLACEHOLDER_RE.sub("", t)
    t = re.sub(r"\s+([,.!?;:])", r"\1", t)      # "sharing , ." -> "sharing,."
    t = re.sub(r"[,;:]\s*([.!?])", r"\1", t)    # "sharing,."   -> "sharing."
    t = re.sub(r"[ \t]{2,}", " ", t).strip()
    if t and t[-1] not in ".!?…\"'”’)":
        cut = max(t.rfind("."), t.rfind("!"), t.rfind("?"), t.rfind("…"))
        if cut >= 20:                            # keep short replies intact
            t = t[:cut + 1]
    return t


def is_bad_generation(reply):
    """Empty (all junk stripped) or narrating the user in third person."""
    return not reply or bool(CASE_NOTES_RE.search(reply))


# ---------------------------------------------------------------------------
# Modality routing (layer 1)
# ---------------------------------------------------------------------------
def route_modality(has_audio):
    return "voice" if has_audio else "text"
