"""Voice agent — speech-to-text via faster-whisper.

Independent of AI_MODE: works whenever faster-whisper is installed. Returns None
when voice is unavailable so the route can report it cleanly.
"""
from app.agents.base_agent import BaseAgent


class VoiceAgent(BaseAgent):
    name = "voice"

    @property
    def available(self):
        return self.registry.load_voice()

    def run(self, audio_path):
        if not self.registry.load_voice():
            return None
        try:
            model = self.registry.voice_model
            # faster-whisper decodes the file itself (PyAV / ffmpeg), so it
            # handles the browser's .webm recording directly.
            segments, _info = model.transcribe(
                audio_path, language="en", beam_size=1, vad_filter=True,
            )
            transcript = " ".join(seg.text for seg in segments)
            return transcript.strip()
        except Exception as e:
            # Corrupt/undecodable upload -> None so the route returns a clean 422.
            print(f"[voice] transcription failed. ({type(e).__name__}: {e})")
            return None


voice_agent = VoiceAgent()
