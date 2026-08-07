"""RunPod serverless inference client.

With INFERENCING_CLIENT=runpod (.env) the chat routes send each turn to a
RunPod serverless endpoint instead of running answer() in-process. The worker
(scripts/runpod_handler.py) runs the SAME pipeline against the SAME Supabase
project, so persistence, crisis handling, and the response shape are identical
to local mode — the Flask app just doesn't need the model weights.

Job contract (both sides of it live in this repo):
    input  = {"user_id", "session_id", "message", "mode"}
    output = answer()'s payload dict, or {"error": "session_deleted"}
"""
import time

import requests

from app.config import Config
from app.db.repo import SessionDeleted

_API = "https://api.runpod.ai/v2"
_POLL_INTERVAL_S = 2
_TERMINAL = {"COMPLETED", "FAILED", "CANCELLED", "TIMED_OUT"}


class RunpodError(Exception):
    """Endpoint unreachable, misconfigured, or the job didn't complete.
    Routes map this to a 503 (and log the detail server-side)."""


def _headers():
    return {"Authorization": f"Bearer {Config.RUNPOD_API_KEY}"}


def runpod_answer(user_id, session_id, message, mode="multi"):
    """One chat turn via the serverless endpoint. Same signature and return
    value as answer(); raises SessionDeleted / RunpodError."""
    if not (Config.RUNPOD_ENDPOINT_ID and Config.RUNPOD_API_KEY):
        raise RunpodError("RUNPOD_ENDPOINT_ID / RUNPOD_API_KEY not set in .env")

    base = f"{_API}/{Config.RUNPOD_ENDPOINT_ID}"
    body = {"input": {"user_id": user_id, "session_id": session_id,
                      "message": message, "mode": mode}}
    deadline = time.monotonic() + Config.RUNPOD_TIMEOUT_S
    try:
        # /runsync returns early (~90 s server-side cap) on a cold start, so
        # keep polling /status until the job finishes or our deadline passes.
        r = requests.post(f"{base}/runsync", json=body, headers=_headers(),
                          timeout=120)
        r.raise_for_status()
        job = r.json()
        while job.get("status") not in _TERMINAL:
            if not job.get("id"):
                raise RunpodError(f"malformed RunPod response: {job!r}")
            if time.monotonic() > deadline:
                raise RunpodError(
                    f"job {job['id']} still {job.get('status')} after "
                    f"{Config.RUNPOD_TIMEOUT_S}s")
            time.sleep(_POLL_INTERVAL_S)
            r = requests.get(f"{base}/status/{job['id']}", headers=_headers(),
                             timeout=30)
            r.raise_for_status()
            job = r.json()
    except requests.RequestException as e:
        raise RunpodError(f"RunPod request failed: {e}") from e

    if job.get("status") != "COMPLETED":
        raise RunpodError(
            f"job ended {job.get('status')}: {job.get('error') or 'no detail'}")

    output = job.get("output")
    if isinstance(output, dict) and output.get("error") == "session_deleted":
        raise SessionDeleted(session_id)
    if not isinstance(output, dict):
        raise RunpodError(f"unexpected job output: {output!r}")
    return output
