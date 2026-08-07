"""Model registry with env-toggle + graceful fallback.

When AI_MODE=real the registry loads the local ML models. If any model fails to
load (missing files, no GPU, OOM), that component stays unavailable and its
agent falls back to a lightweight rule-based stub — the app keeps running.

Heavy imports (torch, transformers, faster_whisper) happen INSIDE the loaders,
so importing this module is always cheap. In stub mode boot only pays for the
voice model — the text models are skipped entirely.
"""
import os

from app.config import Config


def _resolve_device(name):
    import torch
    name = (name or "auto").lower()
    if name == "auto":
        return "cuda" if torch.cuda.is_available() else "cpu"
    if name == "cuda" and not torch.cuda.is_available():
        print("[ml] CHATBOT_DEVICE=cuda requested but no GPU found — using CPU.")
        return "cpu"
    return name


def _resolve_dtype(name, device):
    import torch
    name = (name or "auto").lower()
    if name == "auto":
        return torch.bfloat16 if device == "cuda" else torch.float32
    return {
        "bfloat16": torch.bfloat16, "bf16": torch.bfloat16,
        "float16": torch.float16, "fp16": torch.float16,
        "float32": torch.float32, "fp32": torch.float32,
    }.get(name, torch.float32)


class ModelRegistry:
    def __init__(self):
        self.chatbot_tok = self.chatbot_llm = None
        self.clf_tok = self.clf_model = None
        self.summarizer_tok = self.summarizer_llm = None
        self.voice_model = None

        self.chatbot_ready = False
        self.classifier_ready = False
        self.summarizer_ready = False
        self.voice_ready = False
        self.voice_attempted = False  # so a failed voice load isn't retried every request

    @property
    def real_mode(self):
        return Config.AI_MODE == "real"

    # ------------------------------------------------------------------ loaders
    def load_all(self):
        """Preload at boot. Voice loads in EITHER AI_MODE — it has no stub to
        fall back on (a missing model just disables the mic), and paying for it
        at startup keeps the first voice message from stalling on a cold load.
        The text models load only when AI_MODE=real."""
        self.load_voice()
        if not self.real_mode:
            print("[ml] AI_MODE=stub — using rule-based agents "
                  "(no text models loaded).")
            return
        self.load_classifier()
        self.load_summarizer()
        self.load_chatbot()

    def _try_load(self, label, loader):
        """Run one model loader, converting any failure (missing files, no GPU,
        OOM) into a console note + False so a bad model never blocks startup."""
        try:
            loader()
            return True
        except Exception as e:
            print(f"[ml] {label} unavailable, using stub. ({type(e).__name__}: {e})")
            return False

    def load_chatbot(self):
        if not self.chatbot_ready:
            self.chatbot_ready = self._try_load("chatbot", self._load_chatbot)

    def load_classifier(self):
        if not self.classifier_ready:
            self.classifier_ready = self._try_load("classifier", self._load_classifier)

    def load_summarizer(self):
        if not self.summarizer_ready:
            self.summarizer_ready = self._try_load("summarizer", self._load_summarizer)

    def _load_chatbot(self):
        from transformers import AutoModelForCausalLM, AutoTokenizer
        device = _resolve_device(Config.CHATBOT_DEVICE)
        dtype = _resolve_dtype(Config.CHATBOT_DTYPE, device)
        attn = "sdpa" if device == "cuda" else "eager"
        print(f"[ml] loading chatbot LLM on {device} ({dtype}, attn={attn})...")
        self.chatbot_tok = AutoTokenizer.from_pretrained(Config.CHAT_MODEL_PATH)
        self.chatbot_llm = AutoModelForCausalLM.from_pretrained(
            Config.CHAT_MODEL_PATH, torch_dtype=dtype, attn_implementation=attn,
        ).to(device)
        self.chatbot_llm.eval()
        print("[ml] chatbot ready on", self.chatbot_llm.device)

    def _load_classifier(self):
        from transformers import AutoModelForSequenceClassification, AutoTokenizer
        print("[ml] loading emotion classifier...")
        self.clf_tok = AutoTokenizer.from_pretrained(Config.CLASSIFIER_PATH)
        self.clf_model = AutoModelForSequenceClassification.from_pretrained(
            Config.CLASSIFIER_PATH
        )
        self.clf_model.eval()
        print("[ml] classifier ready.")

    def _load_summarizer(self):
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer
        print(f"[ml] loading summarizer ({Config.SUMMARIZER_PATH})...")
        self.summarizer_tok = AutoTokenizer.from_pretrained(Config.SUMMARIZER_PATH)
        self.summarizer_llm = AutoModelForCausalLM.from_pretrained(
            Config.SUMMARIZER_PATH, torch_dtype=torch.float32,
        ).to(Config.SUMMARIZER_DEVICE)
        self.summarizer_llm.eval()
        print("[ml] summarizer ready.")

    def bench_shares_app_weights(self, key):
        """True when this comparison model IS the app's chatbot (same weights
        on disk). The bench reuses the loaded chatbot for it instead of putting
        a second copy of the same file in VRAM."""
        path = Config.BENCH_MODEL_PATHS.get(key)
        return bool(path) and (os.path.normcase(path)
                               == os.path.normcase(Config.CHAT_MODEL_PATH))

    def load_bench_model(self, key):
        """LAZY loader for one Test Chat comparison LLM. Nothing loads at boot,
        and the bench frees each model after using it — the study's three chat
        models do not fit in VRAM together alongside the app's own chatbot.
        Returns True when ready; a failed load (missing weights, OOM, stub
        mode) returns False and the bench shows a per-variant error."""
        if getattr(self, f"bench_{key}_ready", False):
            return True
        if not self.real_mode:
            return False  # stub mode: comparison models are never loaded
        path = Config.BENCH_MODEL_PATHS.get(key)
        if not path:
            return False
        try:
            from transformers import AutoModelForCausalLM, AutoTokenizer
            device = _resolve_device(Config.CHATBOT_DEVICE)
            dtype = _resolve_dtype(Config.CHATBOT_DTYPE, device)
            print(f"[ml] lazy-loading bench model '{key}' on {device} ({dtype})...")
            tok = AutoTokenizer.from_pretrained(path)
            llm = AutoModelForCausalLM.from_pretrained(
                path, torch_dtype=dtype,
                attn_implementation="sdpa" if device == "cuda" else "eager",
            ).to(device)
            llm.eval()
            setattr(self, f"bench_{key}_tok", tok)
            setattr(self, f"bench_{key}_llm", llm)
            setattr(self, f"bench_{key}_ready", True)
            print(f"[ml] bench model '{key}' ready.")
            return True
        except Exception as e:
            # Out of VRAM is the expected failure on a small card (the chatbot
            # is already resident) — say so plainly instead of a raw CUDA dump.
            note = ("not enough GPU memory alongside the app's chatbot"
                    if "out of memory" in str(e).lower()
                    else f"{type(e).__name__}: {e}")
            print(f"[ml] bench model '{key}' unavailable. ({note})")
            self.free_bench_model(key)      # drop any partial allocation
            return False

    def load_voice(self):
        """Voice is independent of AI_MODE — it works whenever faster-whisper is
        installed. Called at boot by load_all(); still called per request by
        voice.py, which is then a no-op (and the safety net when the app was
        built with load_models=False). Returns True if the model is ready. A
        failed load is only attempted once per process, so a machine without
        faster-whisper doesn't retry on every request."""
        if self.voice_ready:
            return True
        if self.voice_attempted:
            return False
        self.voice_attempted = True
        try:
            from faster_whisper import WhisperModel
            print(f"[ml] loading faster-whisper ({Config.WHISPER_MODEL}, "
                  f"{Config.WHISPER_DEVICE}/{Config.WHISPER_COMPUTE})...")
            self.voice_model = WhisperModel(
                Config.WHISPER_MODEL,
                device=Config.WHISPER_DEVICE,
                compute_type=Config.WHISPER_COMPUTE,
            )
            self.voice_ready = True
            print("[ml] voice model ready.")
        except Exception as e:
            print(f"[ml] voice unavailable. ({type(e).__name__}: {e})")
            self.voice_ready = False
        return self.voice_ready

    # ------------------------------------------------------------------ cleanup
    def _reclaim(self):
        """Return freed weights to the allocator (and the GPU)."""
        try:
            import gc
            import torch
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass

    def free_bench_model(self, key):
        """Drop ONE comparison model. Called between variants of a '3 Models'
        run so peak VRAM is chatbot + one extra, not chatbot + all extras."""
        setattr(self, f"bench_{key}_tok", None)
        setattr(self, f"bench_{key}_llm", None)
        setattr(self, f"bench_{key}_ready", False)
        self._reclaim()

    def free_bench_models(self):
        """Drop every comparison model. They're needed only for the seconds a
        bench run takes; holding them starves the chat service."""
        for key in Config.BENCH_MODEL_PATHS:
            setattr(self, f"bench_{key}_tok", None)
            setattr(self, f"bench_{key}_llm", None)
            setattr(self, f"bench_{key}_ready", False)
        self._reclaim()

    def free_all(self):
        print("[ml] freeing models...")
        self.free_bench_models()
        self.chatbot_tok = self.chatbot_llm = None
        self.clf_tok = self.clf_model = None
        self.summarizer_tok = self.summarizer_llm = None
        self.voice_model = None
        self.chatbot_ready = self.classifier_ready = False
        self.summarizer_ready = self.voice_ready = False
        self.voice_attempted = False
        self._reclaim()


registry = ModelRegistry()
