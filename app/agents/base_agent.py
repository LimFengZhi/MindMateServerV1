"""Base class for all agents: shared model registry access plus the
try-the-real-model-else-stub fallback used by every ML-backed agent."""
from abc import ABC, abstractmethod

from app.ml.registry import registry


class BaseAgent(ABC):
    name = "base"

    def __init__(self):
        self.registry = registry

    @abstractmethod
    def run(self, *args, **kwargs):
        raise NotImplementedError

    def _with_fallback(self, ready, real, stub):
        """Run `real()` when the model is loaded, falling back to `stub()` if
        it isn't ready or raises at inference time — a runtime model failure
        must never break a chat turn."""
        if ready:
            try:
                return real()
            except Exception as e:
                print(f"[{self.name}] real inference failed, using stub. "
                      f"({type(e).__name__}: {e})")
        return stub()
