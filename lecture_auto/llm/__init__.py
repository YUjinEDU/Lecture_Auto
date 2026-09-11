"""Pluggable LLM clients (text + vision).

Select the provider with the ``LLM_PROVIDER`` env var (default ``"openai"``)::

    from lecture_auto.llm import get_llm_client
    client = get_llm_client()
    note_json = client.analyze_image(png_path, vlm_prompt)
    script_json = client.complete_text(script_prompt)

Add a provider by implementing :class:`LLMClient` and registering it::

    from lecture_auto.llm import register
    register("anthropic", AnthropicLLMClient)
"""
from __future__ import annotations

import os
from typing import Callable

from lecture_auto.llm.base import LLMClient
from lecture_auto.llm.openai_client import OpenAILLMClient

# name -> zero-arg factory returning an LLMClient
_REGISTRY: dict[str, Callable[[], LLMClient]] = {
    "openai": OpenAILLMClient,
}


def register(name: str, factory: Callable[[], LLMClient]) -> None:
    """Register an LLMClient factory under ``name`` (case-insensitive)."""
    _REGISTRY[name.lower()] = factory


def available_providers() -> list[str]:
    """Return the sorted list of registered provider names."""
    return sorted(_REGISTRY)


def get_llm_client(name: str | None = None) -> LLMClient:
    """Return an LLMClient for ``name`` (falls back to ``LLM_PROVIDER`` env var).

    Raises:
        ValueError: if ``name`` is not a registered provider.
    """
    name = (name or os.environ.get("LLM_PROVIDER", "openai")).lower()
    try:
        factory = _REGISTRY[name]
    except KeyError:
        raise ValueError(
            f"Unknown LLM provider {name!r}. Available: {available_providers()}"
        )
    return factory()


__all__ = [
    "LLMClient",
    "OpenAILLMClient",
    "get_llm_client",
    "register",
    "available_providers",
]
