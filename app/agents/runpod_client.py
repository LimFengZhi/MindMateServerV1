"""RunPod serverless inference client.

With INFERENCING_CLIENT=runpod (.env) the app sends model work to a RunPod
serverless endpoint instead of running it in-process. The worker
(scripts/runpod_handler.py) runs the SAME code against the SAME Supabase
project, so behavior and response shapes are identical to local mode — the
Flask machine just doesn't need the model weights.

Job contract (both sides of it live in this repo):
    chat  input  = {"action": "chat", "user_id", "session_id", "message", "mode"}
          output = answer()'s payload dict, or {"error": "session_deleted"}
    bench input  = {"action": "bench", "mode", "message", "histories"}
          output = {"results": run_bench()'s list}
    report input = {"action": "report", "data": <report-data dict>}
          output = {"analysis": "<text>"}
    Any output may instead be {"error": "<detail>"}.
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


def _run_job(job_input):
    """Submit one job and return its output dict (raises RunpodError)."""
    if not (Config.RUNPOD_ENDPOINT_ID and Config.RUNPOD_API_KEY):
        raise RunpodError("RUNPOD_ENDPOINT_ID / RUNPOD_API_KEY not set in .env")

    base = f"{_API}/{Config.RUNPOD_ENDPOINT_ID}"
    deadline = time.monotonic() + Config.RUNPOD_TIMEOUT_S
    try:
        # /runsync returns early (~90 s server-side cap) on a cold start, so
        # keep polling /status until the job finishes or our deadline passes.
        r = requests.post(f"{base}/runsync", json={"input": job_input},
                          headers=_headers(), timeout=120)
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
    if not isinstance(output, dict):
        raise RunpodError(f"unexpected job output: {output!r}")
    return output


def runpod_answer(user_id, session_id, message, mode="multi"):
    """One chat turn via the serverless endpoint. Same signature and return
    value as answer(); raises SessionDeleted / RunpodError."""
    output = _run_job({"action": "chat", "user_id": user_id,
                       "session_id": session_id, "message": message,
                       "mode": mode})
    if output.get("error") == "session_deleted":
        raise SessionDeleted(session_id)
    if output.get("error"):
        raise RunpodError(f"worker error: {output['error']}")
    return output


def runpod_bench(mode, message, histories=None):
    """One Test Chat comparison turn ('models3' / 'single_vs_multi') via the
    serverless endpoint. Same return value as bench.run_bench()."""
    output = _run_job({"action": "bench", "mode": mode, "message": message,
                       "histories": histories or {}})
    if output.get("error"):
        raise RunpodError(f"worker error: {output['error']}")
    results = output.get("results")
    if not isinstance(results, list):
        raise RunpodError(f"unexpected bench output: {output!r}")
    return results


def runpod_report_analysis(data):
    """The session-analysis report's LLM step via the serverless endpoint.
    Same return value as report.generate_analysis()."""
    output = _run_job({"action": "report", "data": data})
    if output.get("error"):
        raise RunpodError(f"worker error: {output['error']}")
    analysis = output.get("analysis")
    if not isinstance(analysis, str) or not analysis.strip():
        raise RunpodError(f"unexpected report output: {output!r}")
    return analysis
