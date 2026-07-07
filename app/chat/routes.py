"""Chat endpoints: text and voice. Both feed the same multi-agent pipeline."""
import os
import tempfile

from flask import Blueprint, request, jsonify, g

from app.auth.decorators import login_required, get_owned_session
from app.chat.orchestrator import answer
from app.agents.voice_agent import voice_agent
from app.agents.routing import routing1
from app.extensions import limiter
from app.http_utils import json_error

ALLOWED_AUDIO = {"audio/wav", "audio/x-wav", "audio/webm", "audio/mpeg", "audio/ogg"}
MAX_AUDIO_BYTES = 10 * 1024 * 1024  # 10 MB
MAX_MESSAGE_LEN = 2000

chat_bp = Blueprint("chat", __name__, url_prefix="/chat")


def user_or_ip():
    """Rate-limit key: per user when logged in, per IP otherwise."""
    user = getattr(g, "user", None)
    return user["id"] if user else request.remote_addr


# ---------------- Text chat ----------------
@chat_bp.post("")
@login_required
@limiter.limit("20 per minute", key_func=user_or_ip)
def chat():
    data = request.get_json(silent=True) or {}
    session_id = (data.get("sessionID") or "").strip()
    message = (data.get("message") or "").strip()

    if not session_id or not message:
        return json_error("sessionID and message required", 400)
    if len(message) > MAX_MESSAGE_LEN:
        return json_error("message too long", 400)
    if not get_owned_session(session_id):
        return json_error("invalid session", 403)

    return jsonify(answer(g.user["id"], session_id, message))


# ---------------- Voice chat ----------------
def _validate_audio(f):
    """Return an error response for a bad upload, or None if it's acceptable."""
    if f.mimetype not in ALLOWED_AUDIO:
        return json_error(f"unsupported audio type: {f.mimetype}", 415)
    f.seek(0, os.SEEK_END)
    too_large = f.tell() > MAX_AUDIO_BYTES
    f.seek(0)
    if too_large:
        return json_error("audio too large (max 10 MB)", 413)
    return None


def _transcribe_upload(f):
    """Save the upload to a temp file, transcribe it, and clean up."""
    suffix = os.path.splitext(f.filename or "")[1] or ".wav"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        f.save(tmp.name)
        tmp_path = tmp.name
    try:
        routing1.run(has_audio=True)   # modality route -> "voice"
        return voice_agent.run(tmp_path)
    finally:
        os.unlink(tmp_path)


@chat_bp.post("/voice")
@login_required
@limiter.limit("10 per minute", key_func=user_or_ip)
def chat_voice():
    session_id = (request.form.get("sessionID") or "").strip()
    if not session_id:
        return json_error("sessionID required", 400)
    if not get_owned_session(session_id):
        return json_error("invalid session", 403)

    if not voice_agent.available:
        return json_error("Voice isn't available on the server yet "
                          "(faster-whisper not installed).", 503)

    if "audio" not in request.files:
        return json_error("audio file required", 400)
    f = request.files["audio"]

    error = _validate_audio(f)
    if error:
        return error

    message = _transcribe_upload(f)
    if not message:
        return json_error("could not transcribe audio", 422)

    payload = answer(g.user["id"], session_id, message)
    payload["transcript"] = message
    return jsonify(payload)
