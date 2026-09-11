"""OpenAI-backed LLM client (text + vision).

Reads ``OPENAI_API_KEY`` from the environment (no file fallback — the leaked
``api.txt`` is being removed). Models default to the demo's ``gpt-5.4-mini`` and
are overridable via ``LLM_SCRIPT_MODEL`` / ``LLM_VLM_MODEL``.
"""
from __future__ import annotations

import base64
import os
from pathlib import Path

from lecture_auto.llm.base import LLMClient

DEFAULT_TEXT_MODEL = "gpt-5.4-mini"
DEFAULT_VLM_MODEL = "gpt-5.4-mini"


class OpenAILLMClient(LLMClient):
    """LLM client using the OpenAI Chat Completions API."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        text_model: str | None = None,
        vlm_model: str | None = None,
    ) -> None:
        self._api_key = api_key or os.environ.get("OPENAI_API_KEY", "").strip() or None
        self.text_model = text_model or os.environ.get(
            "LLM_SCRIPT_MODEL", DEFAULT_TEXT_MODEL
        )
        self.vlm_model = vlm_model or os.environ.get(
            "LLM_VLM_MODEL", DEFAULT_VLM_MODEL
        )
        self._client = None

    def _ensure_client(self):
        if self._client is None:
            if not self._api_key:
                raise RuntimeError(
                    "OPENAI_API_KEY is not set. Export it before using the LLM client."
                )
            from openai import OpenAI

            self._client = OpenAI(api_key=self._api_key)
        return self._client

    def chat(
        self,
        messages: list[dict],
        *,
        model: str | None = None,
        temperature: float = 0.3,
        max_tokens: int | None = None,
    ) -> str:
        client = self._ensure_client()
        kwargs: dict = {
            "model": model or self.text_model,
            "temperature": temperature,
            "messages": messages,
        }
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        response = client.chat.completions.create(**kwargs)
        return response.choices[0].message.content or ""

    def complete_text(
        self,
        prompt: str,
        *,
        temperature: float = 0.3,
        max_tokens: int | None = None,
    ) -> str:
        return self.chat(
            [{"role": "user", "content": prompt}],
            model=self.text_model,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    def analyze_image(
        self,
        image_path: Path,
        prompt: str,
        *,
        temperature: float = 0.1,
        max_tokens: int = 1024,
    ) -> str:
        image_b64 = base64.b64encode(Path(image_path).read_bytes()).decode("utf-8")
        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{image_b64}",
                            "detail": "low",
                        },
                    },
                    {"type": "text", "text": prompt},
                ],
            }
        ]
        return self.chat(
            messages,
            model=self.vlm_model,
            temperature=temperature,
            max_tokens=max_tokens,
        )
