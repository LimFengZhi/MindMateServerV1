"""The chat turn as a LangGraph state machine.

        START
          │
     load_context ── diagnose ──(route_turn)──┬── crisis_reply ──┐
                                              └── summarize      │
                                                    │            │
                                                 generate ───────┤
                                                                 │
                                                              persist ── END

`answer()` is the only entry point the rest of the app uses (chat routes for
both text and voice). `build_chat_graph()` returns the UNCOMPILED graph so
notebooks/tests can extend or re-wire it before compiling.
"""
from langgraph.graph import END, START, StateGraph

from app.agents import nodes
from app.agents.state import ChatState


def build_chat_graph():
    g = StateGraph(ChatState)

    g.add_node("load_context", nodes.load_context)
    g.add_node("diagnose", nodes.diagnose)
    g.add_node("crisis_reply", nodes.crisis_reply)
    g.add_node("summarize", nodes.summarize)
    g.add_node("generate", nodes.generate)
    g.add_node("persist", nodes.persist)

    g.add_edge(START, "load_context")
    g.add_edge("load_context", "diagnose")
    g.add_conditional_edges("diagnose", nodes.route_turn, {
        "crisis": "crisis_reply",
        "chat": "summarize",
    })
    g.add_edge("summarize", "generate")
    g.add_edge("generate", "persist")
    g.add_edge("crisis_reply", "persist")
    g.add_edge("persist", END)
    return g


_compiled = None


def get_chat_graph():
    """The compiled graph singleton (compilation is cheap but not free)."""
    global _compiled
    if _compiled is None:
        _compiled = build_chat_graph().compile()
    return _compiled


def answer(user_id, session_id, message, mode="multi"):
    """Run one chat turn through the graph and return the API payload.

    Raises repo.SessionDeleted (from the persist node) when the chat was
    deleted while the reply was generating — routes map it to a clean 404.
    """
    final = get_chat_graph().invoke({
        "user_id": user_id,
        "session_id": session_id,
        "message": message,
        "mode": mode or "multi",
    })
    return final["payload"]
