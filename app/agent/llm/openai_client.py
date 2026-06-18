"""OpenAI adapter for the Chat Completions API with function/tool calling.

Wire-format notes:
  * tools are wrapped as ``{"type": "function", "function": {...}}``,
  * the model returns ``message.tool_calls`` with ``function.arguments`` as a
    JSON *string*,
  * results go back as ``{"role": "tool", "tool_call_id": ..., "content": ...}``.
"""
from __future__ import annotations

import json
import re
import uuid

from app.agent.llm.base import AssistantTurn, LLMClient, ToolCall


class OpenAIClient(LLMClient):
    def __init__(
        self,
        api_key: str,
        model: str,
        max_tokens: int,
        base_url: str | None = None,
    ) -> None:
        from openai import OpenAI  # lazy import

        # ``base_url`` lets this same adapter drive any OpenAI-compatible host
        # (Groq, Together, a local server). Left as None it talks to OpenAI.
        kwargs: dict = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        self._client = OpenAI(**kwargs)
        self._model = model
        self._max_tokens = max_tokens

    @staticmethod
    def _to_openai_messages(system: str, messages: list[dict]) -> list[dict]:
        out: list[dict] = [{"role": "system", "content": system}]
        for m in messages:
            role = m["role"]
            if role == "user":
                out.append({"role": "user", "content": m["content"]})
            elif role == "assistant":
                msg: dict = {"role": "assistant", "content": m.get("content") or None}
                if m.get("tool_calls"):
                    msg["tool_calls"] = [
                        {
                            "id": tc["id"],
                            "type": "function",
                            "function": {
                                "name": tc["name"],
                                "arguments": json.dumps(tc["args"]),
                            },
                        }
                        for tc in m["tool_calls"]
                    ]
                out.append(msg)
            elif role == "tool":
                out.append(
                    {
                        "role": "tool",
                        "tool_call_id": m["tool_call_id"],
                        "content": m["content"],
                    }
                )
        return out

    @staticmethod
    def _to_openai_tools(tools: list[dict]) -> list[dict]:
        return [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t["description"],
                    "parameters": t["parameters"],
                },
            }
            for t in tools
        ]

    # Some open models (notably Llama on Groq) sometimes express a tool call as
    # plain text in the reply instead of using the structured tool-call channel,
    # e.g.  <function=verify_otp>{"code": "123456"}</function>
    # If we don't catch these, the raw markup leaks to the user and the call
    # never runs. This pattern recovers them. Supported shapes:
    #   <function=name>{...}</function>
    #   <function=name>{...}            (unterminated)
    #   <tool_call>{"name": "...", "arguments": {...}}</tool_call>
    _TEXT_CALL_RE = re.compile(
        r"<function\s*=\s*(?P<name>[A-Za-z0-9_]+)\s*>\s*(?P<args>\{.*?\})\s*(?:</function>)?",
        re.DOTALL,
    )

    @classmethod
    def _recover_text_tool_calls(cls, text: str) -> tuple[str, list[ToolCall]]:
        """Extract any text-encoded tool calls; return (cleaned_text, calls)."""
        calls: list[ToolCall] = []
        for m in cls._TEXT_CALL_RE.finditer(text):
            try:
                args = json.loads(m.group("args"))
            except json.JSONDecodeError:
                args = {}
            calls.append(
                ToolCall(id=f"call_{uuid.uuid4().hex[:24]}", name=m.group("name"), args=args)
            )
        cleaned = cls._TEXT_CALL_RE.sub("", text).strip()
        return cleaned, calls

    def complete(
        self, system: str, messages: list[dict], tools: list[dict]
    ) -> AssistantTurn:
        resp = self._client.chat.completions.create(
            model=self._model,
            max_tokens=self._max_tokens,
            messages=self._to_openai_messages(system, messages),
            tools=self._to_openai_tools(tools),
        )
        msg = resp.choices[0].message

        tool_calls: list[ToolCall] = []
        for tc in msg.tool_calls or []:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            tool_calls.append(ToolCall(id=tc.id, name=tc.function.name, args=args))

        text = msg.content or None

        # Fallback: if the model put tool calls in the text instead of the
        # structured channel, recover them so they execute (and don't leak).
        if text and not tool_calls and "<function" in text:
            cleaned, recovered = self._recover_text_tool_calls(text)
            if recovered:
                tool_calls = recovered
                text = cleaned or None

        return AssistantTurn(text=text, tool_calls=tool_calls)
