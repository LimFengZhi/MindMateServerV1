"""Summarize agent — compresses the conversation for the chatbot's context.

Real path: the local Qwen instruct model.
Stub path: a deterministic paraphrase built from the user's turns. The chatbot
already sees recent history directly, so a light summary is enough.
"""
from app.agents.base_agent import BaseAgent
from app.prompt_builder.loader import build_summarise_system


class SummarizeAgent(BaseAgent):
    name = "summarize"

    def run(self, history, max_new_tokens=50):
        if not history:
            return "No prior conversation."
        return self._with_fallback(
            self.registry.summarizer_ready,
            lambda: self._run_real(history, max_new_tokens),
            lambda: self._run_stub(history),
        )

    def _format_history(self, history):
        lines = []
        for past_user, past_reply in history:
            lines.append(f"User: {past_user}")
            lines.append(f"Companion: {past_reply}")
        return "\n".join(lines)

    # --------------------------------------------------------------- real path
    def _run_real(self, history, max_new_tokens):
        import torch
        tok = self.registry.summarizer_tok
        model = self.registry.summarizer_llm
        messages = [
            {"role": "system", "content": build_summarise_system()},
            {"role": "user", "content": f"CONVERSATION:\n{self._format_history(history)}"},
        ]
        prompt = tok.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True)
        inputs = tok(prompt, return_tensors="pt").to(model.device)
        with torch.inference_mode():
            out = model.generate(
                **inputs, max_new_tokens=max_new_tokens,
                do_sample=False, pad_token_id=tok.eos_token_id,
            )
        text = tok.decode(out[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True)
        # An empty generation isn't an exception, so guard it here: fall back to
        # the deterministic stub so the summary is never blank (which would make
        # build_composed_system mislabel an ongoing chat as "No prior conversation").
        return text.strip() or self._run_stub(history)

    # --------------------------------------------------------------- stub path
    def _run_stub(self, history):
        from app.agents.routing import crisis_keywords_present
        user_turns = [u for u, _ in history if u]
        joined = " ".join(user_turns)
        snippet = joined[:280].rsplit(" ", 1)[0] if len(joined) > 280 else joined
        safety = ("a possible safety signal was mentioned"
                  if any(crisis_keywords_present(u) for u in user_turns)
                  else "No safety signals detected.")
        return (f"The user has shared the following so far: {snippet}. "
                f"Safety status: {safety}")


summarize_agent = SummarizeAgent()
