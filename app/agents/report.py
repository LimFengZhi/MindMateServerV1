"""Staff session-analysis report (User Sessions tab) — like bench.py, an
admin-facing consumer of the agents layer that never modifies the pipeline.

build_session_report(user_id) collects the user's recent sessions (count from
config.yaml report.recent_sessions) and writes a four-section analysis with
the SAME summarizer weights the pipeline uses — a second LocalChatModel over
the registry's summarizer with a larger token budget, guided by the
'session_analysis' DB prompt (admin-editable, seeded from
prompt/session_analysis.txt). In stub mode / on any model failure the chain
falls back to a deterministic statistics-based analysis, so the report always
generates.
"""
from datetime import datetime, timezone

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableLambda, RunnablePassthrough

from app.agents.chat_models import LocalChatModel
from app.agents.guards import require_nonempty
from app.agents.prompt_loader import build_session_analysis_system
from app.config import Config
from app.db.admin_repo import get_user_report_data

# The pipeline's summarizer weights, with room for a report instead of a
# 50-token memory summary. Deterministic like summarize_chain.
_report_writer = LocalChatModel(
    model_name="session_report",
    tok_attr="summarizer_tok", model_attr="summarizer_llm",
    ready_attr="summarizer_ready",
    max_new_tokens=Config.REPORT_MAX_NEW_TOKENS,
    gen_kwargs=dict(do_sample=False),
)

_ANALYSIS_PROMPT = ChatPromptTemplate.from_messages([
    ("system", "{system_text}"),
    ("human", "RECENT SESSIONS:\n{sessions_text}"),
])


def _sessions_text(data):
    """The model's view of the sessions: per-session date, emotion counts,
    escalations, and the user's own messages (the analysis prompt forbids
    inventing beyond these)."""
    blocks = []
    for i, s in enumerate(data["sessions"], 1):
        msgs = s["messages"]
        emotions = {}
        escalations = 0
        for m in msgs:
            emotions[m.get("emotion") or "Unknown"] = \
                emotions.get(m.get("emotion") or "Unknown", 0) + 1
            if m.get("escalated"):
                escalations += 1
        user_lines = "\n".join(f"- {m['question']}" for m in msgs) or "(no messages)"
        blocks.append(
            f"Session {i}: \"{s['title']}\" ({(s.get('createdAt') or '')[:10]})\n"
            f"Detected emotions: {emotions or 'none'} | crisis escalations: {escalations}\n"
            f"User's messages:\n{user_lines}"
        )
    return "\n\n".join(blocks) or "(the user has no chat sessions yet)"


def _stub_analysis(x):
    """Deterministic fallback built from the same statistics the model sees."""
    data = x["data"]
    sessions = data["sessions"]
    emotions, escalations, n_msgs = {}, 0, 0
    for s in sessions:
        for m in s["messages"]:
            n_msgs += 1
            emotions[m.get("emotion") or "Unknown"] = \
                emotions.get(m.get("emotion") or "Unknown", 0) + 1
            if m.get("escalated"):
                escalations += 1
    dominant = max(emotions, key=emotions.get) if emotions else "Unknown"
    risk = (f"{escalations} crisis escalation(s) occurred in these sessions."
            if escalations else "None observed.")
    return (
        f"Presenting concerns: the user sent {n_msgs} message(s) across "
        f"{len(sessions)} recent session(s).\n"
        f"Emotional pattern: the dominant detected emotion was {dominant} "
        f"(distribution: {emotions or 'n/a'}).\n"
        f"Risk indicators: {risk}\n"
        "Suggested focus: review the transcripts above for context; this "
        "summary was generated without the language model."
    )


analysis_chain = (
    RunnablePassthrough.assign(
        system_text=lambda x: build_session_analysis_system(),
        sessions_text=lambda x: _sessions_text(x["data"]),
    )
    | _ANALYSIS_PROMPT
    | _report_writer
    | StrOutputParser()
    | RunnableLambda(lambda t: require_nonempty(t, "analysis"))
).with_fallbacks([RunnableLambda(_stub_analysis)])


def generate_analysis(data):
    """The LLM (or stub-fallback) analysis for one report-data dict — the
    compute piece that runs on the RunPod worker when INFERENCING_CLIENT=runpod
    (the 'report' action in scripts/runpod_handler.py)."""
    return analysis_chain.invoke({"data": data})


def build_session_report(user_id, analysis_fn=None):
    """The full report dict the dashboard shows and the PDF renders, or None
    for an unknown user. `analysis_fn` (data -> text) overrides where the
    analysis is generated; default is the local chain."""
    data = get_user_report_data(user_id,
                                recent_sessions=Config.REPORT_RECENT_SESSIONS)
    if data is None:
        return None

    session_stats = []
    for s in data["sessions"]:
        emotions, escalations = {}, 0
        for m in s["messages"]:
            emotions[m.get("emotion") or "Unknown"] = \
                emotions.get(m.get("emotion") or "Unknown", 0) + 1
            if m.get("escalated"):
                escalations += 1
        session_stats.append({
            "sessionID": s["sessionID"],
            "title": s["title"],
            "mode": s["mode"],
            "createdAt": s.get("createdAt"),
            "messageCount": len(s["messages"]),
            "escalations": escalations,
            "emotions": emotions,
        })

    return {
        "user": data["user"],
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "sessionCount": len(session_stats),
        "sessions": session_stats,
        "analysis": (analysis_fn or generate_analysis)(data),
    }
