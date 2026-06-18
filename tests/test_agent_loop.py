"""End-to-end agent-loop test with a *fake* LLM (no network, no API key).

We inject a scripted LLM that returns tool calls then a final answer, and assert
that the agent: executes tools, threads results back into history, and terminates
with text. This validates the orchestration independently of any provider.
"""
import unittest

from app.agent import core
from app.agent.llm.base import AssistantTurn, ToolCall
from app.services.sessions import Session


class ScriptedLLM:
    """Returns a queued sequence of AssistantTurns, one per `complete` call."""

    def __init__(self, script):
        self._script = list(script)
        self.calls = []

    def complete(self, system, messages, tools):
        self.calls.append(list(messages))
        return self._script.pop(0)


class AgentLoopTests(unittest.TestCase):
    def _run_with(self, script):
        fake = ScriptedLLM(script)
        core._agent = None  # reset cached agent
        orig = core.get_llm
        core.get_llm = lambda: fake
        try:
            agent = core.get_agent()
            session = Session(id="t-loop")
            reply = agent.handle(session, "Hi, my number is +91 98765 43210")
            return reply, session, fake
        finally:
            core.get_llm = orig
            core._agent = None

    def test_tool_then_final_answer(self):
        script = [
            AssistantTurn(
                text=None,
                tool_calls=[ToolCall(id="c1", name="lookup_client",
                                     args={"identifier": "+91 98765 43210"})],
            ),
            AssistantTurn(text="Welcome back, Aarav! How can I help today?"),
        ]
        reply, session, fake = self._run_with(script)
        self.assertIn("Aarav", reply)
        # History must contain: user, assistant(tool_call), tool result, assistant(final)
        roles = [m["role"] for m in session.messages]
        self.assertEqual(roles, ["user", "assistant", "tool", "assistant"])
        # The recognised client became authorised as a side effect of the tool.
        self.assertEqual(session.authorized_client_id, "CL-1001")

    def test_multi_tool_single_turn(self):
        script = [
            AssistantTurn(
                text=None,
                tool_calls=[
                    ToolCall(id="c1", name="lookup_client",
                             args={"identifier": "+91 98765 43210"}),
                    ToolCall(id="c2", name="get_application_status", args={}),
                ],
            ),
            AssistantTurn(text="You're at the Documents Pending stage."),
        ]
        reply, session, fake = self._run_with(script)
        self.assertIn("Documents Pending", reply)
        tool_msgs = [m for m in session.messages if m["role"] == "tool"]
        self.assertEqual(len(tool_msgs), 2)

    def test_step_budget_graceful_fallback(self):
        # An LLM that never stops asking for tools should hit the budget and
        # fall back gracefully instead of looping forever.
        loop_turn = AssistantTurn(
            text=None,
            tool_calls=[ToolCall(id="c", name="get_loan_info", args={"topic": "about"})],
        )
        reply, session, fake = self._run_with([loop_turn] * 50)
        self.assertIn("adviser", reply.lower())


if __name__ == "__main__":
    unittest.main()


class TextToolCallRecoveryTests(unittest.TestCase):
    """Some Llama models emit tool calls as text; the OpenAI adapter recovers
    them so they execute instead of leaking raw markup to the user."""

    def test_recovers_function_markup(self):
        from app.agent.llm.openai_client import OpenAIClient
        text = 'Verifying. <function=verify_otp>{"code": "123456"}</function>'
        cleaned, calls = OpenAIClient._recover_text_tool_calls(text)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].name, "verify_otp")
        self.assertEqual(calls[0].args["code"], "123456")
        self.assertNotIn("<function", cleaned)

    def test_plain_text_untouched(self):
        from app.agent.llm.openai_client import OpenAIClient
        cleaned, calls = OpenAIClient._recover_text_tool_calls("Hello there.")
        self.assertEqual(calls, [])
        self.assertEqual(cleaned, "Hello there.")
