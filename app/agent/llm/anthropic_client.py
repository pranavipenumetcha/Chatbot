"""Anthropic (Claude) adapter for the Messages API with tool use.

Wire-format notes (verified against current Anthropic docs):
  * tools use ``input_schema`` (not ``parameters``),
  * the model returns ``tool_use`` content blocks with ``id``/``name``/``input``,
  * results go back in a ``user`` message as ``tool_result`` blocks keyed by
    ``tool_use_id``.
"""
from __future__ import annotations

from app.agent.llm.base import AssistantTurn, LLMClient, ToolCall


class AnthropicClient(LLMClient):
    def __init__(self, api_key: str, model: str, max_tokens: int) -> None:
        import anthropic  # lazy import so the SDK is only needed when used

        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = model
        self._max_tokens = max_tokens

    # -- history translation --------------------------------------------------
    @staticmethod
    def _to_anthropic_messages(messages: list[dict]) -> list[dict]:
        out: list[dict] = []
        pending_tool_results: list[dict] = []

        def flush_tool_results() -> None:
            nonlocal pending_tool_results
            if pending_tool_results:
                out.append({"role": "user", "content": pending_tool_results})
                pending_tool_results = []

        for m in messages:
            role = m["role"]
            if role == "tool":
                # Accumulate consecutive tool results into one user message.
                pending_tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": m["tool_call_id"],
                        "content": m["content"],
                    }
                )
                continue

            flush_tool_results()

            if role == "user":
                out.append({"role": "user", "content": m["content"]})
            elif role == "assistant":
                blocks: list[dict] = []
                if m.get("content"):
                    blocks.append({"type": "text", "text": m["content"]})
                for tc in m.get("tool_calls", []):
                    blocks.append(
                        {
                            "type": "tool_use",
                            "id": tc["id"],
                            "name": tc["name"],
                            "input": tc["args"],
                        }
                    )
                out.append({"role": "assistant", "content": blocks})

        flush_tool_results()
        return out

    @staticmethod
    def _to_anthropic_tools(tools: list[dict]) -> list[dict]:
        return [
            {
                "name": t["name"],
                "description": t["description"],
                "input_schema": t["parameters"],
            }
            for t in tools
        ]

    # -- completion -----------------------------------------------------------
    def complete(
        self, system: str, messages: list[dict], tools: list[dict]
    ) -> AssistantTurn:
        resp = self._client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            system=system,
            messages=self._to_anthropic_messages(messages),
            tools=self._to_anthropic_tools(tools),
        )

        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        for block in resp.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append(
                    ToolCall(id=block.id, name=block.name, args=dict(block.input or {}))
                )

        return AssistantTurn(
            text="".join(text_parts) or None,
            tool_calls=tool_calls,
        )
