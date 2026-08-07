"""The staff Test Chat comparison bench (dashboard → Test Chat tab).

Two one-shot comparison modes — neither touches sessions/messages; results
are persisted to the bench_result table by the admin routes:

  models3          the same message answered by the three fine-tuned study
                   models (Gemma 2 = the live app model, Llama 3.2, Qwen3)
                   under the SAME composed system prompt. The two extra
                   models are lazy-loaded by the registry on first use.
  single_vs_multi  the current Gemma 2 chatbot answering ALONE with a minimal
                   prompt (single agent) vs the full multi-agent treatment —
                   which is not re-implemented here: the multi arm RUNS the
                   app's compiled graph with only its DB ends swapped out, so
                   it can never drift from what real users get.

("Normal — chat as a user" testing is NOT here: that is the existing test
bench page, which chats through the real pipeline on real sessions and rates
via the messages feedback columns.)
"""
import time

from langchain_core.messages import HumanMessage, SystemMessage

from app.agents import chains, nodes, stubs
from app.agents.chat_models import LocalChatModel, ModelUnavailable
from app.agents.graph import build_chat_graph
from app.agents.guards import tidy_reply
from app.agents.prompt_loader import build_composed_system, build_single_system
from app.agents.prompts import pairs_to_messages
from app.agents.registry import registry
from app.config import Config

BENCH_MODES = ("models3", "single_vs_multi")

_FIRST_MESSAGE_SUMMARY = ("This is the user's first message — the conversation "
                          "is just beginning.")

# The two extra comparison models. The chat-template details (fold_system /
# stop / system_prefix) come from chains.CHAT_FAMILIES so the bench can never
# drift from the app; only the bench-only display label is defined here.
_BENCH_LABELS = {
    "llama32": "Llama 3.2 1B (fine-tuned)",
    "qwen3": "Qwen3 1.7B (fine-tuned)",
}
_FAMILIES = {key: dict(chains.CHAT_FAMILIES[key], label=label)
             for key, label in _BENCH_LABELS.items()}
_extra_cache = {}

_MAIN_LABELS = {"gemma2": "Gemma 2 2B", "qwen3": "Qwen3 1.7B",
                "llama32": "Llama 3.2 1B"}
MAIN_LABEL = (_MAIN_LABELS.get(Config.CHAT_MODEL_FAMILY,
                               Config.CHAT_MODEL_FAMILY)
              + " (current app model)")


def _extra_model(key):
    if not registry.load_bench_model(key):        # lazy; no-op once loaded
        raise ModelUnavailable(f"{key} (AI_MODE=stub or weights missing)")
    if key not in _extra_cache:
        fam = _FAMILIES[key]
        _extra_cache[key] = LocalChatModel(
            model_name=f"bench-{key}",
            tok_attr=f"bench_{key}_tok", model_attr=f"bench_{key}_llm",
            ready_attr=f"bench_{key}_ready",
            fold_system=fam["fold_system"], extra_stop_tokens=fam["stop"],
            max_new_tokens=Config.CHATBOT_MAX_NEW_TOKENS,
            gen_kwargs=Config.CHATBOT_GEN_KWARGS,
        )
    return _extra_cache[key]


def _chat(model, system_text, message, history=None):
    """One reply with this variant's OWN prior turns as verbatim context.
    Cleanup matches the app (tidy_reply)."""
    reply = model.invoke([SystemMessage(content=system_text),
                          *pairs_to_messages(history or []),
                          HumanMessage(content=message)])
    return tidy_reply(reply.content)


_MULTI_GRAPH = None


def _multi_graph():
    """THE production graph with its two DB ends removed: history is seeded
    into the initial state instead of read from Supabase, and the reply is
    returned instead of persisted (the bench never touches sessions/messages,
    and must not fire the crisis email). Every other node and edge is the real
    one, so a pipeline change in nodes.py/graph.py reaches this page for free.
    Compiled once — seeding via state (not a closure) is what allows caching."""
    global _MULTI_GRAPH
    if _MULTI_GRAPH is None:
        _MULTI_GRAPH = build_chat_graph(
            load_context=lambda s: nodes.with_memory_window(s.get("history") or []),
            persist=lambda s: {"payload": {"reply": s["reply"]}},
        ).compile()
    return _MULTI_GRAPH


def _timed(variant, label, fn):
    """Run one variant, timing it; failures become per-variant error cards
    instead of failing the whole run."""
    start = time.monotonic()
    try:
        return {"variant": variant, "label": label, "reply": fn(),
                "latencyMs": int((time.monotonic() - start) * 1000)}
    except ModelUnavailable as e:
        return {"variant": variant, "label": label, "reply": None,
                "latencyMs": None, "error": f"model not available: {e}"}
    except Exception as e:
        return {"variant": variant, "label": label, "reply": None,
                "latencyMs": None, "error": f"{type(e).__name__}: {e}"}


def run_bench(mode, message, histories=None):
    """One comparison turn. `histories` maps variant -> [(user, reply), ...]
    from earlier turns of the same bench session, so each variant continues
    ITS OWN conversation (empty/None = first turn)."""
    histories = histories or {}
    if mode == "models3":
        return _run_three_models(message, histories)
    if mode == "single_vs_multi":
        return _run_single_vs_multi(message, histories)
    raise ValueError(f"unknown bench mode: {mode}")


def _run_three_models(message, histories):
    """Same message, same composed system prompt, three fine-tuned models —
    each continuing its OWN verbatim history from the session's prior turns."""
    diag = chains.diagnose_chain.invoke(message)
    any_history = any(histories.get(v) for v in ("gemma2", *_FAMILIES))
    summary_line = ("The conversation so far is shown in the previous messages."
                    if any_history else _FIRST_MESSAGE_SUMMARY)
    system_text = build_composed_system(diag["emotion"], summary_line)
    results = [_timed("gemma2", MAIN_LABEL,
                      lambda: _chat(chains.chatbot,
                                    chains.CHAT_FAMILY["system_prefix"] + system_text,
                                    message, histories.get("gemma2")))]
    for key, fam in _FAMILIES.items():
        results.append(_timed(key, fam["label"],
                              lambda k=key, f=fam: _chat(
                                  _extra_model(k), f["system_prefix"] + system_text,
                                  message, histories.get(k))))
    return results


def _run_single_vs_multi(message, histories):
    """Architecture comparison on the SAME Gemma 2 weights AND the same
    prompt rules: 'single' is the composed prompt with its summary/memory
    parts removed (the DB prompt with key 'single', admin-editable), so the
    comparison isolates the pipeline, not the wording. Across a session,
    'single' carries the WHOLE history verbatim; 'multi' runs the real graph,
    so it keeps the last `memory.recent_turns` exchanges verbatim and reaches
    the rest through the summarizer — exactly the difference being studied."""
    def single():
        try:
            return _chat(chains.chatbot,
                         chains.CHAT_FAMILY["system_prefix"] + build_single_system(),
                         message, histories.get("single"))
        except ModelUnavailable:
            # Stub mode: mirror the pipeline's stub fallback so the two
            # variants stay comparable.
            return stubs.generate({
                "message": message,
                "turn_count": len(histories.get("single") or []) + 1})

    def multi():
        # Not an imitation of the pipeline — it IS the pipeline (see
        # _multi_graph): load_context/diagnose/route_turn/crisis_reply/
        # summarize/generate all run exactly as they do for a real user.
        return _multi_graph().invoke({
            "message": message,
            "history": histories.get("multi") or [],
            "mode": "bench",
        })["payload"]["reply"]

    return [
        _timed("single", "Single agent — same rules, no pipeline (whole history verbatim, no diagnosis/summary/guardrails)", single),
        _timed("multi", "Multi-agent — the real pipeline: diagnose > crisis route > recent turns + summary > guarded generation", multi),
    ]
