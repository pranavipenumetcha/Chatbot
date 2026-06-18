"""Provider-neutral LLM interface.

The agent core speaks only this small vocabulary; concrete adapters translate to
Anthropic's or OpenAI's wire formats. Adding a new provider (Gemini, a local
model, Bedrock) means writing one adapter — nothing in the agent changes.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class ToolCall:
    id: str
    name: str
    args: dict


@dataclass
class AssistantTurn:
    """One model response: optional natural-language text plus any tool calls."""

    text: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)

    @property
    def wants_tools(self) -> bool:
        return bool(self.tool_calls)


class LLMClient(ABC):
    """Contract every provider adapter implements."""

    @abstractmethod
    def complete(
        self, system: str, messages: list[dict], tools: list[dict]
    ) -> AssistantTurn:
        """Run one completion.

        ``messages`` is the normalised history (see sessions.Session). ``tools``
        is the provider-neutral schema list from the tool registry.
        """
        raise NotImplementedError
