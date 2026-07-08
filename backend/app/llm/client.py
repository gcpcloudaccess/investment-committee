"""Pluggable LLM client (Anthropic default, OpenAI alternative).

The LLM is used only to turn structured evidence into natural-language
reasoning/explanations - all directional math (indicators, consensus weights,
position sizing) happens in plain Python and works without any LLM call. If no
API key is configured, `chat()` degrades to a deterministic templated summary
built from the evidence bullets passed in, so the rest of the system stays
testable/runnable without a key.
"""

from __future__ import annotations

import logging

from app.config import get_settings

logger = logging.getLogger("llm_client")


class LLMClient:
    def __init__(self) -> None:
        self.settings = get_settings()
        self._client = None
        self._provider = self.settings.llm_provider

        if not self.settings.llm_key_configured:
            return

        if self._provider == "anthropic":
            import anthropic

            self._client = anthropic.Anthropic(api_key=self.settings.anthropic_api_key)
        elif self._provider == "openai":
            import openai

            self._client = openai.OpenAI(api_key=self.settings.openai_api_key)

    @property
    def available(self) -> bool:
        return self._client is not None

    def chat(self, system: str, user: str, max_tokens: int = 500, fallback: str | None = None) -> str:
        if not self.available:
            return fallback or user

        try:
            if self._provider == "anthropic":
                resp = self._client.messages.create(
                    model=self.settings.anthropic_model,
                    max_tokens=max_tokens,
                    system=system,
                    messages=[{"role": "user", "content": user}],
                )
                # Response content can include non-text blocks first (e.g. a
                # ThinkingBlock when extended thinking triggers) - content[0]
                # is not reliably the text response, so find the text block.
                text_blocks = [block.text for block in resp.content if getattr(block, "type", None) == "text"]
                if not text_blocks:
                    raise ValueError(f"No text block in response content: {[type(b).__name__ for b in resp.content]}")
                return "".join(text_blocks).strip()
            else:
                resp = self._client.chat.completions.create(
                    model=self.settings.openai_model,
                    max_tokens=max_tokens,
                    messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                )
                return resp.choices[0].message.content.strip()
        except Exception as exc:  # network/quota errors shouldn't crash a trading tick
            logger.warning("LLM call failed, using fallback: %s: %s", type(exc).__name__, exc)
            return fallback or f"(LLM unavailable: {exc}) {user}"


_client_singleton: LLMClient | None = None


def get_llm_client() -> LLMClient:
    global _client_singleton
    if _client_singleton is None:
        _client_singleton = LLMClient()
    return _client_singleton
