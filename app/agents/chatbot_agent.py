"""Chatbot agent — generates the companion's reply.

Real path: the local Gemma2 LLM.
Stub path: a warm, rule-based reflective responder so the chat is fully usable
without loading a multi-GB model. It follows the same spirit as the prompt:
reflect briefly, stay warm, ask at most one gentle open question.
"""
import re

from app.agents.base_agent import BaseAgent

# First-message welcome, shared by the stub and the orchestrator's greeting
# shortcut (the fine-tuned model hallucinates a backstory for a bare "Hi").
WELCOME_MESSAGE = (
    "Hi, I'm really glad you're here. This is a space to talk through "
    "whatever's on your mind, at your own pace. What brought you here today?"
)

# The MentalChat16K training data contains literal template tokens like
# "[Name]" / "[Age]" (372 in the raw dump), and the fine-tune emits them.
_PLACEHOLDER_RE = re.compile(r"\[[A-Za-z][A-Za-z '/]{0,24}\]")

_STUB_OPENERS = [
    "Thank you for sharing that with me.",
    "I'm really glad you put that into words.",
    "I hear you, and what you said matters.",
    "Thanks for trusting me with this.",
    "I'm here with you on this.",
]

_STUB_QUESTIONS = [
    "What's been weighing on you the most about it?",
    "Can you tell me a little more about what that's been like for you?",
    "What feels most important for you to talk through right now?",
    "When did you first start noticing this?",
    "What's been on your mind the most lately?",
]

_STUB_CRISIS = (
    "I can hear how much pain you're in right now, and I'm really glad you told "
    "me. You don't have to carry this alone — I'm staying right here with you."
)


def _tidy_reply(text):
    """Clean the raw generation: drop leaked template tokens, then cut any
    half-finished sentence left behind by the max_new_tokens cap."""
    t = _PLACEHOLDER_RE.sub("", text)
    t = re.sub(r"\s+([,.!?;:])", r"\1", t)      # "sharing , ." -> "sharing,."
    t = re.sub(r"[,;:]\s*([.!?])", r"\1", t)    # "sharing,."   -> "sharing."
    t = re.sub(r"[ \t]{2,}", " ", t).strip()
    if t and t[-1] not in ".!?…\"'”’)":
        cut = max(t.rfind("."), t.rfind("!"), t.rfind("?"), t.rfind("…"))
        if cut >= 20:                            # keep short replies intact
            t = t[:cut + 1]
    return t


class ChatbotAgent(BaseAgent):
    name = "chatbot"

    def run(self, system_prompt, history, user_text, max_new_tokens=120):
        return self._with_fallback(
            self.registry.chatbot_ready,
            lambda: self._run_real(system_prompt, history, user_text, max_new_tokens),
            lambda: self._run_stub(history, user_text),
        )

    # --------------------------------------------------------------- real path
    def _build_prompt(self, system_prompt, history, user_text):
        """Build a Gemma chat prompt that preserves conversation memory.

        Gemma has no system role, so the instructions (+ running summary) frame
        the FIRST user turn. The real conversation history then follows, and the
        current user message comes LAST and CLEAN.

        Previously the entire system prompt was prepended to the *current*
        message every turn, burying what the user just said under a wall of
        instructions — so the model lost the thread and ignored the history.
        Keeping the latest turn clean lets the prior turns work as memory.

        Note: no literal <bos> here — the tokenizer prepends exactly one BOS
        (add_special_tokens defaults to True). Adding our own would double it.
        """
        parts = []
        if history:
            first_user, first_reply = history[0]
            parts.append(
                f"<start_of_turn>user\n{system_prompt}\n\n{first_user}<end_of_turn>\n"
                f"<start_of_turn>model\n{first_reply}<end_of_turn>\n"
            )
            for past_user, past_reply in history[1:]:
                parts.append(
                    f"<start_of_turn>user\n{past_user}<end_of_turn>\n"
                    f"<start_of_turn>model\n{past_reply}<end_of_turn>\n"
                )
            parts.append(f"<start_of_turn>user\n{user_text}<end_of_turn>\n")
        else:
            # No verbatim history: either the first message, or summary-only mode
            # (RECENT_TURNS=0). The system prompt + summary frame the current
            # message directly, so the rules sit right next to where the model
            # generates and it never sees its own prior (long) replies.
            parts.append(
                f"<start_of_turn>user\n{system_prompt}\n\n{user_text}<end_of_turn>\n"
            )
        parts.append("<start_of_turn>model\n")
        return "".join(parts)

    def _run_real(self, system_prompt, history, user_text, max_new_tokens):
        import torch
        tok = self.registry.chatbot_tok
        model = self.registry.chatbot_llm
        prompt = self._build_prompt(system_prompt, history, user_text)
        inputs = tok(prompt, return_tensors="pt").to(model.device)
        with torch.inference_mode():
            out = model.generate(
                **inputs,
                max_new_tokens=max_new_tokens,
                do_sample=True, temperature=0.65, top_p=0.9,
                repetition_penalty=1.15, no_repeat_ngram_size=6,
                pad_token_id=tok.eos_token_id,
            )
        text = tok.decode(out[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True)
        return _tidy_reply(text)

    # --------------------------------------------------------------- stub path
    def _run_stub(self, history, user_text):
        from app.agents.routing import crisis_keywords_present
        if crisis_keywords_present(user_text):
            return _STUB_CRISIS
        if not history:
            return WELCOME_MESSAGE
        turn = len(history)
        opener = _STUB_OPENERS[turn % len(_STUB_OPENERS)]
        question = _STUB_QUESTIONS[turn % len(_STUB_QUESTIONS)]
        return f"{opener} {question}"


chatbot_agent = ChatbotAgent()
