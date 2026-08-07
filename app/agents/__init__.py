"""LangGraph multi-agent pipeline.

Public surface (import from here, not the submodules, so the internals can
move without touching callers):

    answer(user_id, session_id, message, mode)   one full chat turn
    build_chat_graph()                           the uncompiled StateGraph
                                                 (extend/re-wire in notebooks)

Layout (LangChain provides the components, LangGraph the control flow):
    state.py        ChatState — the typed state flowing through the graph
    guards.py       pure safety/risk helpers (no ML imports; reusable anywhere)
    stubs.py        rule-based fallbacks for every model
    chat_models.py  LocalChatModel(BaseChatModel) — any local HF model as a
                    standard LangChain chat model (swap for ChatOpenAI freely)
    prompts.py      ChatPromptTemplates + message helpers (text stays in the DB)
    chains.py       prompt | llm | parser chains with retry + stub-fallback
                    policies; reusable stand-alone (batch them in notebooks)
    nodes.py        graph node functions (state -> partial state)
    graph.py        graph wiring + the compiled singleton + answer()
    voice.py        speech-to-text (independent of AI_MODE)
"""
from app.agents.graph import answer, build_chat_graph
