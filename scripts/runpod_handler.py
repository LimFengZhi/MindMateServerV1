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


def handler(event):
    inp = (event or {}).get("input") or {}
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


runpod.serverless.start({"handler": handler})
