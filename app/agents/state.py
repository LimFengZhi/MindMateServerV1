"""The state that flows through the chat graph.

Every node receives the whole state and returns only the keys it produces;
LangGraph merges the partial updates. `total=False` because the state fills in
as the graph runs (e.g. `summary` never exists on a crisis turn).
"""
from typing import Optional, TypedDict


class Diagnostic(TypedDict):
    emotion: str
    confidence: float
    risk_flag: bool
    risk_confidence: float


class ChatState(TypedDict, total=False):
    # ---- request (set by answer(), never mutated) ----
    user_id: str
    session_id: str
    message: str
    mode: str                          # 'multi' | 'experiment'

    # ---- context (load_context) ----
    history: list                      # FULL history: [(user, reply), ...]
    recent: list                       # verbatim window shown to the chatbot

    # ---- diagnostics (diagnose) ----
    diag: Diagnostic

    # ---- generation context (summarize) ----
    summary: Optional[str]

    # ---- outcome (crisis / welcome / generate, then persist) ----
    reply: str
    escalated: bool
    payload: dict                      # the API response body
