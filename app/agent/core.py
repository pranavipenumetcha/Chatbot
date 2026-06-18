"""The agent loop.

This is the "agentic" core: a reason -> act -> observe loop. We hand the model
the tool schemas and the conversation; it decides what to call. We execute the
calls (with authorisation enforced in the dispatcher), feed results back, and
repeat until the model produces a natural-language reply or we hit the step
budget. There is no scripted decision tree — routing is the model's job, guided
by the system prompt and grounded by tools.

The loop is channel-agnostic: the web API, the CLI, or a future WhatsApp webhook
all call ``Agent.handle`` with a session and a user message.
"""
from __future__ import annotations

import json
import logging

from app import tools
from app.agent.llm import get_llm
from app.agent.prompts import build_system_prompt
from app.config import settings
from app.services.sessions import Session

logger = logging.getLogger("nestara.agent")


class Agent:
    def __init__(self) -> None:
        self._system = build_system_prompt()
        self._schemas = tools.get_schemas()

    def handle(self, session: Session, user_message: str) -> str:
        """Process one user turn and return the assistant's reply text."""
        session.messages.append({"role": "user", "content": user_message})
        llm = get_llm()

        for step in range(settings.max_agent_steps):
            turn = llm.complete(self._system, session.messages, self._schemas)

            # Record the assistant turn (text + any tool calls) in history.
            assistant_entry: dict = {"role": "assistant", "content": turn.text or ""}
            if turn.tool_calls:
                assistant_entry["tool_calls"] = [
                    {"id": tc.id, "name": tc.name, "args": tc.args}
                    for tc in turn.tool_calls
                ]
            session.messages.append(assistant_entry)

            if not turn.wants_tools:
                # Model is done reasoning — return its reply.
                return turn.text or ""

            # Execute each requested tool and append the results.
            for tc in turn.tool_calls:
                logger.info("tool_call name=%s args=%s", tc.name, tc.args)
                result = tools.dispatch(session, tc.name, tc.args)
                session.messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "name": tc.name,
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )
            # Loop: the model now sees the tool results and decides what's next.

        # Step budget exhausted — fail gracefully rather than looping forever.
        fallback = (
            "I'm having trouble completing that right now. Let me connect you with "
            "a Nestara adviser who can help — could you share your name and mobile "
            "number?"
        )
        session.messages.append({"role": "assistant", "content": fallback})
        return fallback


# Module-level singleton so the system prompt and schemas are built once.
_agent: Agent | None = None


def get_agent() -> Agent:
    global _agent
    if _agent is None:
        _agent = Agent()
    return _agent
