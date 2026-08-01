"""A LangChain ChatModel over any local HuggingFace model in the registry.

ONE generic class covers every local LLM the app runs (the fine-tuned Gemma
chatbot, the Qwen summarizer): point it at the registry attributes and it
becomes a standard `BaseChatModel` — so it composes into `prompt | llm |
parser` chains, and swapping a model for `ChatOpenAI`/`ChatAnthropic`/another
fine-tune is a one-line change in chains.py; the graph never knows.

Prompt formatting is delegated to the tokenizer's own chat template
(`apply_chat_template`), which is what the fine-tuning study trained with —
no hand-built `<start_of_turn>` strings. `fold_system=True` handles families
like Gemma 2 whose template rejects a system role: the system message is
folded into the first user turn, exactly as the training pipeline did.
"""
from typing import Any, Optional

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field

from app.agents.registry import registry


class ModelUnavailable(RuntimeError):
    """The model's weights aren't loaded (AI_MODE=stub or a failed load) —
    chains catch this via .with_fallbacks and switch to the rule-based stub."""


def _to_chat_dicts(messages, fold_system):
    """LangChain messages -> HF chat-template dicts. With fold_system, the
    system message becomes the head of the first user turn (Gemma 2's template
    raises on a system role; the fine-tune was trained with this folding)."""
    role_map = {"system": "system", "human": "user", "ai": "assistant"}
    chat = [{"role": role_map.get(m.type, "user"), "content": m.content}
            for m in messages]
    if fold_system and chat and chat[0]["role"] == "system":
        system = chat.pop(0)["content"]
        if chat and chat[0]["role"] == "user":
            chat[0]["content"] = f"{system}\n\n{chat[0]['content']}"
        else:
            chat.insert(0, {"role": "user", "content": system})
    return chat


class LocalChatModel(BaseChatModel):
    """Chat interface over a (tokenizer, model) pair held by the registry.

    Attributes are registry *names*, not objects, because the registry loads
    after import time and can fail gracefully — readiness is checked per call.
    """
    model_name: str                       # for logs ("chatbot", "summarize")
    tok_attr: str                         # registry attribute of the tokenizer
    model_attr: str                       # registry attribute of the model
    ready_attr: str                       # registry readiness flag
    fold_system: bool = False             # True for chat templates w/o system role
    extra_stop_tokens: tuple = ()         # e.g. ("<end_of_turn>",)
    max_new_tokens: int = 100
    gen_kwargs: dict = Field(default_factory=dict)  # sampling params

    @property
    def _llm_type(self) -> str:
        return "local-hf-chat"

    @property
    def _identifying_params(self) -> dict:
        return {"model_name": self.model_name, "model_attr": self.model_attr}

    def _stop_ids(self, tok):
        """eos + the template's end-of-turn token, derived from the TOKENIZER so
        the app is immune to what a merge wrote into the model's config (a
        transformers-5.x merge once dropped <end_of_turn> and generation ran
        past the reply into a hallucinated next turn)."""
        ids = [tok.eos_token_id]
        for token in self.extra_stop_tokens:
            tid = tok.convert_tokens_to_ids(token)
            if tid is not None and tid != tok.unk_token_id and tid not in ids:
                ids.append(tid)
        return ids

    def _generate(self, messages: list[BaseMessage], stop: Optional[list[str]] = None,
                  run_manager: Any = None, **kwargs: Any) -> ChatResult:
        if not getattr(registry, self.ready_attr):
            raise ModelUnavailable(self.model_name)
        import torch
        tok = getattr(registry, self.tok_attr)
        model = getattr(registry, self.model_attr)
        try:
            chat = _to_chat_dicts(messages, self.fold_system)
            prompt = tok.apply_chat_template(
                chat, tokenize=False, add_generation_prompt=True)
            # add_special_tokens=False: chat templates already carry BOS where
            # the family needs one — letting the tokenizer add another would
            # double it (matches the fine-tuning study's inference code).
            encoded = tok(prompt, return_tensors="pt",
                          add_special_tokens=False).to(model.device)
            with torch.inference_mode():
                out = model.generate(
                    **encoded,
                    max_new_tokens=kwargs.get("max_new_tokens", self.max_new_tokens),
                    eos_token_id=self._stop_ids(tok),
                    pad_token_id=tok.eos_token_id,
                    **self.gen_kwargs,
                )
            text = tok.decode(out[0][encoded["input_ids"].shape[1]:],
                              skip_special_tokens=True)
        except Exception as e:
            print(f"[{self.model_name}] real inference failed, using stub. "
                  f"({type(e).__name__}: {e})")
            raise
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=text))])
