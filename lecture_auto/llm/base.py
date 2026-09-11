"""Abstract LLM client interface.

Unifies every model call in the project (slide vision analysis + lecture-script
text generation) behind one interface so the provider is a config choice
(``LLM_PROVIDER`` env var) rather than scattered SDK calls. See
:func:`lecture_auto.llm.get_llm_client`.

Three entry points cover all call sites:
- ``complete_text(prompt)``      — single text completion (pipeline script gen)
- ``analyze_image(image, prompt)`` — vision analysis of one slide (VLM notes)
- ``chat(messages)``             — raw chat passthrough (demo batch script gen)
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path


class LLMClient(ABC):
    """Provider-agnostic LLM client for text + vision."""

    @abstractmethod
    def chat(
        self,
        messages: list[dict],
        *,
        model: str | None = None,
        temperature: float = 0.3,
        max_tokens: int | None = None,
    ) -> str:
        """Run a chat completion and return the assistant's text content."""
        raise NotImplementedError

    @abstractmethod
    def complete_text(
        self,
        prompt: str,
        *,
        temperature: float = 0.3,
        max_tokens: int | None = None,
    ) -> str:
        """Single-turn text completion from a plain prompt string."""
        raise NotImplementedError

    @abstractmethod
    def analyze_image(
        self,
        image_path: Path,
        prompt: str,
        *,
        temperature: float = 0.1,
        max_tokens: int = 1024,
    ) -> str:
        """Vision analysis: send ``image_path`` + ``prompt``, return text content."""
        raise NotImplementedError
