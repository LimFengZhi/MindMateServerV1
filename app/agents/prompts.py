"""Prompt templates + message helpers.

The TEXT of the system prompts stays admin-editable in the DB (via
app/prompt_builder/loader.py, ~15 s cache) — it flows into these templates as
a VALUE (`{system_text}`), never as a template, so literal braces in
admin-edited text can't break formatting. The templates define the message
STRUCTURE; the loader owns the words.
"""
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

# Companion reply: rules+summary as system, verbatim window (empty in
# summary-only mode), then the current message LAST and CLEAN — prepending the
# instructions to every turn buried what the user just said and the model
# lost the thread.
REPLY_PROMPT = ChatPromptTemplate.from_messages([
    ("system", "{system_text}"),
    MessagesPlaceholder("history_msgs"),
    ("human", "{message}"),
])

# Long-term-memory compression of the older turns.
SUMMARISE_PROMPT = ChatPromptTemplate.from_messages([
    ("system", "{system_text}"),
    ("human", "CONVERSATION:\n{conversation}"),
])


def pairs_to_messages(history):
    """[(user, reply)] -> alternating LangChain messages for MessagesPlaceholder."""
    msgs = []
    for past_user, past_reply in history:
        msgs.append(HumanMessage(content=past_user))
        msgs.append(AIMessage(content=past_reply))
    return msgs


def format_history(history):
    """[(user, reply)] -> the plain-text transcript the summarizer reads."""
    lines = []
    for past_user, past_reply in history:
        lines.append(f"User: {past_user}")
        lines.append(f"Companion: {past_reply}")
    return "\n".join(lines)
