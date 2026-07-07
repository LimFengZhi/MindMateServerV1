"""Routing layers.

Layer 1 routes by modality (text vs voice). Layer 2 decides whether a turn must
be escalated to crisis resources. The lexical crisis net runs regardless of
AI_MODE, so safety escalation works even with the stub diagnostic.
"""
import re
from app.agents.base_agent import BaseAgent
from app.config import Config


class RoutingLayer1(BaseAgent):
    name = "routing1"

    def run(self, has_audio):
        return "voice" if has_audio else "text"


routing1 = RoutingLayer1()


# Explicit self-harm / suicide language. ML classifiers trained on long posts
# miss short direct statements, so this lexical net is a safety backstop: if any
# of these appear we escalate no matter what the classifier says.
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


class RoutingLayer2(BaseAgent):
    name = "routing2"

    def run(self, diag, message=None):
        """Escalate if the classifier flags risk OR explicit self-harm keywords
        are present. Returns (escalate: bool, message: str|None)."""
        if diag.get("risk_flag") or crisis_keywords_present(message):
            return True, Config.CRISIS_MESSAGE
        return False, None


routing2 = RoutingLayer2()
