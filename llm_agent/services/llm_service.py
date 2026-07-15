from __future__ import annotations

import logging
from typing import Any

from llm_agent.config import LLMConfig

logger = logging.getLogger(__name__)


class LLMService:
    """Thin wrapper around an OpenAI-compatible chat completions client."""

    def __init__(self, client: Any | None = None, model: str | None = None, config: LLMConfig | None = None) -> None:
        self.config = config or LLMConfig.from_env()
        self.model = model or self.config.model
        self.client = client
        self.fallback_mode = False
        self.last_error: str | None = None

        if self.client is None:
            if not self.config.api_key:
                self.fallback_mode = True
                self.last_error = "OPENAI_API_KEY is not configured."
                return

            try:
                from openai import OpenAI  # type: ignore
            except ImportError:
                self.fallback_mode = True
                self.last_error = "The 'openai' Python package is not installed."
                return

            self.client = OpenAI(
                api_key=self.config.api_key,
                base_url=self.config.base_url,
                timeout=self.config.timeout,
            )

    def generate_text(self, prompt: str) -> str:
        if self.fallback_mode or self.client is None:
            reason = self.last_error or "LLM service is not configured for live calls."
            return f"{reason} Prompt preview: {prompt[:120]}"

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=self.config.temperature,
            )
            return response.choices[0].message.content or ""
        except Exception as exc:  # pragma: no cover - exercised at runtime
            self.last_error = str(exc)
            logger.exception("OpenAI chat completion failed")
            return f"LLM request failed: {exc}"
