"""Diagnostic agent — emotion classification + risk flag.

Real path: the local RoBERTa sequence classifier.
Stub path: a lightweight keyword heuristic over the same label set, plus the
lexical crisis net for the risk flag, so the analysis page still works.
"""
from app.agents.base_agent import BaseAgent
from app.agents.routing import crisis_keywords_present
from app.config import Config

LABELS = ["Normal", "Depression", "Suicidal", "Anxiety", "Bipolar", "Stress",
          "Personality disorder"]

# keyword -> emotion, for the stub. Order matters (first match wins per group).
_STUB_RULES = [
    ("Anxiety", ["anxious", "anxiety", "panic", "nervous", "worry", "worried",
                 "on edge", "racing", "scared", "afraid"]),
    ("Stress", ["stress", "stressed", "overwhelm", "pressure", "deadline",
                "too much", "burnt out", "burned out", "exhausted"]),
    ("Depression", ["depress", "hopeless", "empty", "worthless", "numb",
                    "no point", "can't go on", "sad", "down", "lonely", "tired of"]),
    ("Bipolar", ["manic", "mania", "bipolar", "mood swing"]),
]


class DiagnosticAgent(BaseAgent):
    name = "diagnostic"

    def run(self, text):
        return self._with_fallback(
            self.registry.classifier_ready,
            lambda: self._run_real(text),
            lambda: self._run_stub(text),
        )

    # --------------------------------------------------------------- real path
    def _run_real(self, text):
        import torch
        tok = self.registry.clf_tok
        model = self.registry.clf_model
        inputs = tok(text, return_tensors="pt", truncation=True, max_length=512)
        with torch.inference_mode():
            logits = model(**inputs).logits
        probs = torch.softmax(logits, dim=-1)[0]
        idx = int(probs.argmax())
        emotion = model.config.id2label[idx]
        confidence = float(probs[idx])

        # .get() so a checkpoint whose labels don't include the risk class
        # (different taxonomy / LABEL_n names) degrades instead of KeyError-ing.
        risk_id = model.config.label2id.get(Config.RISK_CLASS)
        if risk_id is None:
            risk_conf, risk_flag = 0.0, False
        else:
            risk_conf = float(probs[risk_id])
            risk_flag = risk_conf >= Config.RISK_THRESHOLD

        return {
            "emotion": emotion,
            "confidence": round(confidence, 4),
            "risk_flag": risk_flag,
            "risk_confidence": round(risk_conf, 4),
        }

    # --------------------------------------------------------------- stub path
    def _run_stub(self, text):
        lowered = (text or "").lower()
        risk = crisis_keywords_present(text)
        if risk:
            return {"emotion": "Suicidal", "confidence": 0.9,
                    "risk_flag": True, "risk_confidence": 0.9}
        for emotion, keywords in _STUB_RULES:
            if any(k in lowered for k in keywords):
                return {"emotion": emotion, "confidence": 0.55,
                        "risk_flag": False, "risk_confidence": 0.0}
        return {"emotion": "Normal", "confidence": 0.5,
                "risk_flag": False, "risk_confidence": 0.0}


diagnostic_agent = DiagnosticAgent()
