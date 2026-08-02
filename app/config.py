"""Central configuration. ALL config access lives here so the rest of the app
reads typed constants instead of scattering os.getenv / yaml loads everywhere.

Two sources, one reader:
  .env         secrets + machine-specific values (keys, paths, devices).
  config.yaml  non-secret app tuning (generation params, thresholds, crisis
               message) — committed, identical on every machine.
"""
import os
import secrets
from dotenv import load_dotenv

APP_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(APP_DIR)  # project root (one level above app/)

# Load .env from the project root, regardless of the current working directory.
load_dotenv(os.path.join(ROOT_DIR, ".env"))


def _load_yaml():
    """config.yaml at the project root; {} if absent/empty so every read
    below falls back to its hardcoded default and the app still boots."""
    path = os.path.join(ROOT_DIR, "config.yaml")
    try:
        import yaml
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except FileNotFoundError:
        print("[config] config.yaml not found — using built-in defaults.")
        return {}
    except Exception as e:
        print(f"[config] could not parse config.yaml ({e}) — using defaults.")
        return {}


_YAML = _load_yaml()


def _yaml(section, key, default):
    return (_YAML.get(section) or {}).get(key, default)

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

    # Extra comparison models for the staff Test Chat bench ("3 Models" mode).
    # LAZY-loaded on first use — never at boot. Defaults point at the
    # fine-tuning study's merged weights alongside the app-served Gemma.
    BENCH_MODEL_PATHS = {
        "llama32": _abspath(_env("BENCH_LLAMA32_PATH",
                                 "models/chat_models/mentalchat16k/llama32_merged")),
        "qwen3": _abspath(_env("BENCH_QWEN3_PATH",
                               "models/chat_models/mentalchat16k/qwen3_merged")),
    }

    # --- Voice (faster-whisper) ---
    WHISPER_MODEL = _env("WHISPER_MODEL", "small")
    WHISPER_DEVICE = _env("WHISPER_DEVICE", "cpu")
    WHISPER_COMPUTE = _env("WHISPER_COMPUTE", "int8")

    # ------------------------------------------------------------------
    # App tuning from config.yaml (defaults here keep the app bootable
    # without the file). Edit config.yaml, not these fallbacks.
    # ------------------------------------------------------------------
    # --- Chatbot generation (LocalChatModel in app/agents/chains.py) ---
    CHATBOT_MAX_NEW_TOKENS = int(_yaml("chatbot", "max_new_tokens", 100))
    CHATBOT_GEN_KWARGS = dict(
        do_sample=True,
        temperature=float(_yaml("chatbot", "temperature", 0.65)),
        top_p=float(_yaml("chatbot", "top_p", 0.9)),
        repetition_penalty=float(_yaml("chatbot", "repetition_penalty", 1.15)),
        no_repeat_ngram_size=int(_yaml("chatbot", "no_repeat_ngram_size", 6)),
    )

    # --- Summarizer generation ---
    SUMMARIZER_MAX_NEW_TOKENS = int(_yaml("summarizer", "max_new_tokens", 50))

    # --- Memory window (see config.yaml for what 0 means) ---
    RECENT_TURNS = int(_yaml("memory", "recent_turns", 0))

    # --- Diagnostic / routing (emotion classifier) ---
    RISK_CLASS = _yaml("risk", "class", "Suicidal")
    RISK_THRESHOLD = float(_yaml("risk", "escalation_threshold", 0.8))

    # Crisis escalation message (the crisis_reply node).
    CRISIS_MESSAGE = (_YAML.get("crisis_message") or (
        "It sounds like you're carrying something incredibly heavy right now, "
        "and I'm really glad you said it out loud. I'm not able to provide crisis "
        "support myself, but people who can are available right now.\n\n"
        "- If you're in immediate danger, please call your local emergency number.\n"
        "- Malaysia: Befrienders KL 03-7627 2929 (24 hours)\n"
        "- US: call or text 988 (Suicide & Crisis Lifeline)\n"
        "- UK & ROI: Samaritans 116 123\n\n"
        "You don't have to go through this alone — would you be willing to reach "
        "out to one of these right now?"
    )).strip()

    @classmethod
    def validate(cls):
        missing = [k for k in ("SUPABASE_URL", "SUPABASE_SECRET_KEY")
                   if not getattr(cls, k)]
        if missing:
            raise RuntimeError(
                "Missing required env vars: " + ", ".join(missing) +
                ". Set them in .env (see .env.example)."
            )
