"""RunPod serverless worker entrypoint (the other half of
app/agents/runpod_client.py's job contract).

The worker runs the SAME multi-agent pipeline as the Flask app, against the
SAME Supabase project — answer() persists the turn, sends crisis emails, and
stores experiment-mode drafts exactly as local inference would. The Flask app
(INFERENCING_CLIENT=runpod) only relays the payload back to the browser.

Deploy: a serverless endpoint whose image contains this repo + model weights
(see Dockerfile / scripts/download_models.py), the same .env values as a GPU
host (Supabase keys, AI_MODE=real, model paths), `pip install runpod`, and
`python scripts/runpod_handler.py` as the start command.
"""
import os
import sys

# Make `app` importable when launched as `python scripts/runpod_handler.py`.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import runpod  # noqa: E402

from app.agents import answer  # noqa: E402
from app.agents.registry import registry  # noqa: E402
from app.db.repo import SessionDeleted  # noqa: E402

# Load weights once at worker boot (AI_MODE decides real vs stub), so the
# first job doesn't pay the model-load cost inside its own timeout.
registry.load_all()


def _bench(inp):
    """One Test Chat comparison turn. Pure compute: histories come in from the
    Flask side (bench_session tables) and the results go back for it to
    persist — the worker itself never touches the bench tables."""
    from app.agents.bench import BENCH_MODES, run_bench
    missing = [k for k in ("mode", "message") if not inp.get(k)]
    if missing:
        return {"error": "missing input fields: " + ", ".join(missing)}
    if inp["mode"] not in BENCH_MODES:
        return {"error": f"unknown bench mode: {inp['mode']}"}
    return {"results": run_bench(inp["mode"], inp["message"],
                                 inp.get("histories") or {})}


def _report(inp):
    """The session-analysis report's LLM step. Pure compute: the Flask side
    reads the report data from the DB and keeps the cache; only the analysis
    text is generated here."""
    from app.agents.report import generate_analysis
    if not inp.get("data"):
        return {"error": "missing input fields: data"}
    return {"analysis": generate_analysis(inp["data"])}


def _chat(inp):
    missing = [k for k in ("user_id", "session_id", "message")
               if not inp.get(k)]
    if missing:
        return {"error": "missing input fields: " + ", ".join(missing)}
    try:
        return answer(inp["user_id"], inp["session_id"], inp["message"],
                      mode=inp.get("mode") or "multi")
    except SessionDeleted:
        # The client maps this back to the same 404 as local mode.
        return {"error": "session_deleted"}


def handler(event):
    inp = (event or {}).get("input") or {}
    action = inp.get("action") or "chat"
    if action == "bench":
        return _bench(inp)
    if action == "report":
        return _report(inp)
    return _chat(inp)


runpod.serverless.start({"handler": handler})
