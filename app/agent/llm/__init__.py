"""Factory that picks the right LLM adapter based on configuration.

Adapter modules are imported lazily so that simply importing this package never
requires the Anthropic or OpenAI SDK — only constructing the chosen client does.
"""
from __future__ import annotations

from functools import lru_cache

from app.agent.llm.base import AssistantTurn, LLMClient, ToolCall
from app.config import settings

__all__ = ["AssistantTurn", "LLMClient", "ToolCall", "get_llm"]


class LLMConfigError(RuntimeError):
    pass


def _build() -> LLMClient:
    provider = settings.llm_provider

    if provider == "auto":
        if settings.anthropic_api_key:
            provider = "anthropic"
        elif settings.openai_api_key:
            provider = "openai"
        else:
            raise LLMConfigError(
                "No LLM key found. Set ANTHROPIC_API_KEY or OPENAI_API_KEY "
                "(see .env.example)."
            )

    if provider == "anthropic":
        if not settings.anthropic_api_key:
            raise LLMConfigError("LLM_PROVIDER=anthropic but ANTHROPIC_API_KEY is unset.")
        from app.agent.llm.anthropic_client import AnthropicClient

        return AnthropicClient(
            api_key=settings.anthropic_api_key,
            model=settings.anthropic_model,
            max_tokens=settings.max_tokens,
        )

    if provider == "openai":
        if not settings.openai_api_key:
            raise LLMConfigError("LLM_PROVIDER=openai but OPENAI_API_KEY is unset.")
        from app.agent.llm.openai_client import OpenAIClient

        return OpenAIClient(
            api_key=settings.openai_api_key,
            model=settings.openai_model,
            max_tokens=settings.max_tokens,
            base_url=settings.openai_base_url,
        )

    raise LLMConfigError(f"Unknown LLM_PROVIDER: {provider!r}")


@lru_cache(maxsize=1)
def get_llm() -> LLMClient:
    """Return a process-wide singleton LLM client."""
    return _build()
