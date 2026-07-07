"""Loads the agents' system prompts and fills in per-turn context.

Prompts live in the Supabase `prompts` table so they can be edited in the
dashboard without a code change. The bundled .txt files are the defaults: they
seed the table on first boot and are the fallback if the DB is unreachable or
the table is empty. A short in-memory cache means dashboard edits take effect
within a few seconds without hitting the DB on every turn.
"""
import os
import time

PROMPT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prompt")

# logical key -> bundled default file
PROMPT_FILES = {
    "composed": "composed_prompt.txt",
    "summarise": "summarise_prompt.txt",
}

_CACHE_TTL = 15  # seconds
_cache = {}  # key -> (content, expires_at)


def bundled_prompt(key):
    """The default prompt text shipped with the repo (used for seeding + fallback)."""
    with open(os.path.join(PROMPT_DIR, PROMPT_FILES[key]), encoding="utf-8") as f:
        return f.read().strip()


def _resolve(key):
    """Current prompt text: DB first (cached), else the bundled file."""
    now = time.monotonic()
    cached = _cache.get(key)
    if cached and cached[1] > now:
        return cached[0]

    content = None
    try:
        from app.db.repo import get_prompt
        row = get_prompt(key)
        if row and row.get("content"):
            content = row["content"]
    except Exception:
        content = None  # DB unavailable / table missing -> fall back to file

    if not content:
        content = bundled_prompt(key)

    _cache[key] = (content, now + _CACHE_TTL)
    return content


def build_composed_system(diagnostic_label, summarised_history):
    """System prompt for the chatbot, with the diagnostic label + conversation
    summary substituted in. Plain str.replace (not .format) so literal braces in
    the prompt can never raise."""
    return (
        _resolve("composed")
        .replace("{diagnostic_label}", diagnostic_label or "Unknown")
        .replace("{summarised_history}", summarised_history or "No prior conversation.")
    )


def build_summarise_system():
    return _resolve("summarise")
