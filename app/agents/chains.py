"""The runnable chains the graph nodes invoke — LangChain composition with
explicit policies instead of hand-rolled control flow:

    reply_chain      prompt | chatbot | TidyReplyParser
                       .with_retry(case-note reply -> resample once)
                       .with_fallbacks(case notes twice -> fixed warm fallback)
                       .with_fallbacks(model missing/failed -> rule stub)
    summarize_chain  prompt | summarizer | guard-nonempty  -> stub fallback
    diagnose_chain   classifier fn                          -> stub fallback

Chain inputs are plain dicts (documented per chain below), so evaluation
notebooks can reuse them directly — e.g. `reply_chain.batch([...])` over a
test set instead of duplicating generation code. Swapping a model = editing
its LocalChatModel(...) constructor here; nothing else changes.
"""
from langchain_core.exceptions import OutputParserException
from langchain_core.output_parsers import BaseOutputParser, StrOutputParser
from langchain_core.runnables import RunnableLambda, RunnablePassthrough

from app.agents import stubs
from app.agents.chat_models import LocalChatModel
from app.agents.guards import CASE_NOTES_FALLBACK, is_bad_generation, tidy_reply
from app.agents.prompts import (
    REPLY_PROMPT, SUMMARISE_PROMPT, format_history, pairs_to_messages,
)
from app.config import Config
from app.agents.registry import registry
from app.agents.prompt_loader import build_composed_system, build_summarise_system

# ---------------------------------------------------------------------------
# The local models as LangChain chat models
# ---------------------------------------------------------------------------
# Generation parameters live in config.yaml (Config.CHATBOT_*), not here.
chatbot = LocalChatModel(
    model_name="chatbot",
    tok_attr="chatbot_tok", model_attr="chatbot_llm", ready_attr="chatbot_ready",
    fold_system=True,                     # Gemma 2's template has no system role
    extra_stop_tokens=("<end_of_turn>",),
    max_new_tokens=Config.CHATBOT_MAX_NEW_TOKENS,
    gen_kwargs=Config.CHATBOT_GEN_KWARGS,
)

summarizer = LocalChatModel(
    model_name="summarize",
    tok_attr="summarizer_tok", model_attr="summarizer_llm",
    ready_attr="summarizer_ready",
    max_new_tokens=Config.SUMMARIZER_MAX_NEW_TOKENS,
    gen_kwargs=dict(do_sample=False),     # summaries stay deterministic
)


# ---------------------------------------------------------------------------
# Companion reply
#   input: {message, history: [(user, reply)], turn_count, emotion, summary}
# ---------------------------------------------------------------------------
class TidyReplyParser(BaseOutputParser[str]):
    """Clean the raw generation; REJECT case-note style so the chain's retry
    policy resamples (see guards.py for why the fine-tune produces both)."""

    def parse(self, text: str) -> str:
        reply = tidy_reply(text)
        if is_bad_generation(reply):
            raise OutputParserException(f"case-note style reply: {reply[:80]!r}")
        return reply

    @property
    def _type(self) -> str:
        return "tidy_reply"


_reply_generation = (
    # The system prompt text comes from the DB template (admin-editable) and
    # enters the prompt as a value, composed with this turn's tone + summary.
    RunnablePassthrough.assign(
        system_text=lambda x: build_composed_system(x["emotion"], x["summary"]),
        history_msgs=lambda x: pairs_to_messages(x.get("history") or []),
    )
    | REPLY_PROMPT
    | chatbot
    | TidyReplyParser()
).with_retry(
    # Sampled decoding: one resample usually yields a direct reply.
    retry_if_exception_type=(OutputParserException,),
    stop_after_attempt=2,
    wait_exponential_jitter=False,
).with_fallbacks(
    # Still case notes after the retry -> the fixed warm fallback.
    [RunnableLambda(lambda x: CASE_NOTES_FALLBACK)],
    exceptions_to_handle=(OutputParserException,),
)

# Outermost: the model isn't loaded (stub mode) or raised at inference time.
reply_chain = _reply_generation.with_fallbacks([RunnableLambda(stubs.generate)])


# ---------------------------------------------------------------------------
# Long-term-memory summary
#   input: {history: [(user, reply)]}  (the turns OUTSIDE the verbatim window)
# ---------------------------------------------------------------------------
def _require_text(text):
    """An empty generation isn't an exception — make it one, so the stub
    fallback fires and the summary is never blank (a blank summary would make
    build_composed_system mislabel an ongoing chat as 'No prior conversation')."""
    if not text.strip():
        raise ValueError("empty summary")
    return text.strip()


summarize_chain = (
    RunnablePassthrough.assign(
        system_text=lambda x: build_summarise_system(),
        conversation=lambda x: format_history(x["history"]),
    )
    | SUMMARISE_PROMPT
    | summarizer
    | StrOutputParser()
    | RunnableLambda(_require_text)
).with_fallbacks([RunnableLambda(lambda x: stubs.summarize(x["history"]))])


# ---------------------------------------------------------------------------
# Diagnostic — RoBERTa classifier (not an LLM, so a plain runnable)
#   input: str (the user message) -> Diagnostic dict
# ---------------------------------------------------------------------------
def _diagnose_real(text):
    from app.agents.chat_models import ModelUnavailable
    if not registry.classifier_ready:
        raise ModelUnavailable("diagnostic")
    import torch
    tok = registry.clf_tok
    model = registry.clf_model
    try:
        inputs = tok(text, return_tensors="pt", truncation=True, max_length=512)
        with torch.inference_mode():
            logits = model(**inputs).logits
        probs = torch.softmax(logits, dim=-1)[0]
        idx = int(probs.argmax())
        # .get() so a checkpoint whose labels don't include the risk class
        # (different taxonomy / LABEL_n names) degrades instead of KeyError-ing.
        risk_id = model.config.label2id.get(Config.RISK_CLASS)
        risk_conf = float(probs[risk_id]) if risk_id is not None else 0.0
    except Exception as e:
        print(f"[diagnostic] real inference failed, using stub. "
              f"({type(e).__name__}: {e})")
        raise
    return {
        "emotion": model.config.id2label[idx],
        "confidence": round(float(probs[idx]), 4),
        "risk_flag": risk_conf >= Config.RISK_THRESHOLD,
        "risk_confidence": round(risk_conf, 4),
    }


diagnose_chain = RunnableLambda(_diagnose_real).with_fallbacks(
    [RunnableLambda(stubs.diagnose)])
