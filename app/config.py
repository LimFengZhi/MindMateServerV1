"""Central configuration. All env access lives here so the rest of the app
reads typed constants instead of scattering os.getenv calls everywhere."""
import os
import secrets
from dotenv import load_dotenv

APP_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(APP_DIR)  # project root (one level above app/)

# Load .env from the project root, regardless of the current working directory.
load_dotenv(os.path.join(ROOT_DIR, ".env"))

# Placeholders that must NOT be used as a real Flask secret.
_WEAK_SECRETS = {"", "dev", "change-this-to-a-long-random-string"}


def _env(name, default=""):
    # Values in .env occasionally carry stray spaces; strip them defensively.
    return (os.getenv(name) or default).strip()


def _abspath(path):
    """Resolve a possibly-relative model path against the repo root."""
    if not path:
        return path
    return path if os.path.isabs(path) else os.path.join(ROOT_DIR, path)


def _resolve_secret_key():
    key = _env("SECRET_KEY")
    if key in _WEAK_SECRETS:
        # Generate a strong ephemeral key so the app is never signing with a
        # predictable secret. (Ephemeral = signed cookies reset on restart; set
        # a fixed SECRET_KEY in .env for persistence.)
        print("[config] SECRET_KEY is unset/placeholder — generating a random "
              "ephemeral key. Set a fixed SECRET_KEY in .env for production.")
        return secrets.token_hex(32)
    return key


class Config:
    # --- Flask ---
    SECRET_KEY = _resolve_secret_key()
    MAX_CONTENT_LENGTH = 12 * 1024 * 1024  # 12 MB hard cap (covers audio uploads)

    # --- Supabase ---
    SUPABASE_URL = _env("SUPABASE_URL")
    SUPABASE_SECRET_KEY = _env("SUPABASE_SECRET_KEY")
    # Optional publishable/anon key. Used for the end-user auth flow so the
    # privileged secret key is reserved for server-side data access. Falls back
    # to the secret key if unset (works, but less least-privilege).
    SUPABASE_ANON_KEY = _env("SUPABASE_ANON_KEY")
    SITE_URL = _env("SITE_URL", "http://localhost:5000")

    # --- AI pipeline ---
    # "stub" (default) = rule-based agents, instant boot.
    # "real" = load local ML models, falling back to stub per component on error.
    AI_MODE = _env("AI_MODE", "stub").lower()

    CHAT_MODEL_PATH = _abspath(_env("CHAT_MODEL_PATH", "models/chat_models/merged/gemma2"))
    CLASSIFIER_PATH = _abspath(_env("CLASSIFIER_PATH", "models/classifier_models/roberta"))
    SUMMARIZER_PATH = _env("SUMMARIZER_PATH", "Qwen/Qwen2.5-0.5B-Instruct")

    CHATBOT_DEVICE = _env("CHATBOT_DEVICE", "auto")
    CHATBOT_DTYPE = _env("CHATBOT_DTYPE", "auto")
    SUMMARIZER_DEVICE = _env("SUMMARIZER_DEVICE", "cpu")

    # --- Voice (faster-whisper) ---
    WHISPER_MODEL = _env("WHISPER_MODEL", "small")
    WHISPER_DEVICE = _env("WHISPER_DEVICE", "cpu")
    WHISPER_COMPUTE = _env("WHISPER_COMPUTE", "int8")

    # --- Diagnostic / routing (emotion classifier) ---
    RISK_CLASS = "Suicidal"
    RISK_THRESHOLD = 0.8
    # Softer threshold: a 'Suicidal' label at/above this confidence (but below
    # RISK_THRESHOLD) doesn't escalate, yet the reply carries a link to the
    # in-app Suicide Risk Check self-test.
    RISK_QUIZ_THRESHOLD = float(_env("RISK_QUIZ_THRESHOLD", "0.5"))

    # Crisis escalation message (Routing Layer 2).
    CRISIS_MESSAGE = (
        "It sounds like you're carrying something incredibly heavy right now, "
        "and I'm really glad you said it out loud. I'm not able to provide crisis "
        "support myself, but people who can are available right now.\n\n"
        "- If you're in immediate danger, please call your local emergency number.\n"
        "- Malaysia: Befrienders KL 03-7627 2929 (24 hours)\n"
        "- US: call or text 988 (Suicide & Crisis Lifeline)\n"
        "- UK & ROI: Samaritans 116 123\n\n"
        "You don't have to go through this alone — would you be willing to reach "
        "out to one of these right now?"
    )

    @classmethod
    def validate(cls):
        missing = [k for k in ("SUPABASE_URL", "SUPABASE_SECRET_KEY")
                   if not getattr(cls, k)]
        if missing:
            raise RuntimeError(
                "Missing required env vars: " + ", ".join(missing) +
                ". Set them in .env (see .env.example)."
            )
