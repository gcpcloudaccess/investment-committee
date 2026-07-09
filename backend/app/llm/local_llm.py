"""Pluggable local LLM client using Ollama.

The LLM is used only to turn structured evidence into natural-language
reasoning/explanations. If Ollama is not running or the server is unreachable, 
chat() degrades gracefully to a deterministic templated summary built from 
the evidence bullets passed in, ensuring the system never crashes.
"""

from _future_ import annotations

import logging
import ollama

from app.config import get_settings

logger = logging.getLogger("local_llm_client")


class LocalLLMClient:
    def _init_(self) -> None:
        self.settings = get_settings()
        # Default to localhost if not specified in your settings
        self.host = getattr(self.settings, "ollama_host", "http://localhost:11434")
        self.model = getattr(self.settings, "ollama_model", "llama3.1:3b")  # or mistral, phi3, etc.
        
        self._client = None
        
        try:
            # Initialize client and ping server to confirm it's up
            client = ollama.Client(host=self.host)
            client.list()  # Quick connection check
            self._client = client
            logger.info("Successfully connected to local Ollama server at %s", self.host)
        except Exception as exc:
            logger.warning(
                "Could not connect to Ollama server at %s. Falling back to deterministic summary. Error: %s", 
                self.host, exc
            )

    @property
    def available(self) -> bool:
        return self._client is not None

    def chat(self, system: str, user: str, max_tokens: int = 500, fallback: str | None = None) -> str:
        if not self.available:
            return fallback or user

        try:
            # Note: num_predict controls the max tokens generated in Ollama
            options = {"num_predict": max_tokens}
            
            resp = self._client.chat(
                model=self.model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                options=options
            )
            return resp["message"]["content"].strip()
            
        except Exception as exc:  # Network or local resource exhaustion shouldn't crash a trading tick
            logger.warning("Local LLM call failed, using fallback: %s: %s", type(exc)._name_, exc)
            return fallback or f"(Local LLM unavailable: {exc}) {user}"


_local_client_singleton: LocalLLMClient | None = None


def get_local_llm_client() -> LocalLLMClient:
    global _local_client_singleton
    if _local_client_singleton is None:
        _local_client_singleton = LocalLLMClient()
    return _local_client_singleton