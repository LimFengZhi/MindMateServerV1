"""Speech-to-text via faster-whisper.

Independent of AI_MODE and of the chat graph: works whenever faster-whisper
is installed. Preloaded at boot by registry.load_all(); the load_voice() calls
below are then no-ops, and remain the fallback for a process built with
load_models=False. Returns None when transcription fails so the route can
report it cleanly.
"""
from app.agents.registry import registry


def voice_available():
    return registry.load_voice()


def transcribe(audio_path):
    if not registry.load_voice():
        return None
    try:
        # faster-whisper decodes the file itself (PyAV / ffmpeg), so it
        # handles the browser's .webm recording directly.
        segments, _info = registry.voice_model.transcribe(
            audio_path, language="en", beam_size=1, vad_filter=True,
        )
        return " ".join(seg.text for seg in segments).strip()
    except Exception as e:
        # Corrupt/undecodable upload -> None so the route returns a clean 422.
        print(f"[voice] transcription failed. ({type(e).__name__}: {e})")
        return None
