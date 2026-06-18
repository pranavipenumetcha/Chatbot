# Nestara — AI Conversational Assistant for Home Loans

An **agentic** conversational assistant for [Nestara](https://nestara.in/), India's
AI-powered home-loan platform. It recognises existing clients and answers
questions about their application personally; verifies unknown users with an OTP
before guiding them into the loan journey or to a human adviser; and maintains
full conversation context within a session.

The core idea: **the LLM reasons and decides which tools to call** — there is no
scripted decision tree. Routing, personalisation, and recovery from odd inputs
are all the model's job, guided by a system prompt and grounded by a small,
well-designed set of tools whose **authorisation is enforced in code**.

---

## 1. Quick start

```bash
# 1. Add an API key (Anthropic or OpenAI — you only need one)
cp .env.example .env
#   then edit .env and paste your key into ANTHROPIC_API_KEY or OPENAI_API_KEY

# 2. Run (creates a venv, installs deps, starts the server)
./run.sh
#   -> open http://localhost:8000
```

Prefer to do it by hand:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # add your key
uvicorn app.main:app --reload # http://localhost:8000
```

Other entry points (same agent core, different channel):

```bash
./run.sh cli      # terminal chat  (python -m app.channels.cli)
./run.sh test     # test suite     (python -m unittest discover -s tests -v)
```

No API key handy? The whole non-LLM core — tools, auth, OTP, DB, sessions — is
covered by **28 deterministic tests** that run offline (`./run.sh test`). Only the
live conversation needs a key.

---

## 2. What it does (mapped to the brief)

| Brief requirement | How it's met |
|---|---|
| **Known client → look up, respond personally** | `lookup_client` matches the registered mobile/email; once recognised the agent answers using the client's name, product, and adviser. |
| **Application status / outstanding docs / loan Qs** | `get_application_status`, `get_outstanding_documents`, `get_loan_info` (grounded knowledge). |
| **Client mentions/uploads a document** | `log_document` records it **and** notifies the assigned adviser (mock notification). |
| **Unknown user → verify first (OTP)** | `send_otp` / `verify_otp`. Account tools are blocked until the session is authorised. |
| **After verifying, understand intent** | The model reads intent free-form; no rigid menu. |
| **Interested in a home loan → share the journey link** | `share_application_link` returns the real product URL. |
| **Wants a human → collect details + hand off** | `create_lead` then `notify_adviser` routes to the right desk. |
| **Maintain conversation context** | Full message history (incl. tool calls + results) is kept per session and replayed to the model each turn. |
| **Agentic architecture** | A real reason→act→observe loop; the model picks tools. See §4. |
| **Personalisation** | Name, product, stage, adviser, ₹-lakh/crore phrasing; warm tone. See §6. |
| **Clean thinking / grows** | Layered modules, decorator-based tool registry, provider-agnostic LLM layer, channel-agnostic core. See §5. |
| **Edge cases** | Wrong OTP, lockout, ambiguity, cross-client access, mid-conversation drop-off, step-budget runaway. See §7. |

---

## 3. Project layout

```
nestara-assistant/
├── app/
│   ├── config.py              # all env-driven settings in one typed place
│   ├── main.py                # FastAPI app: /api/chat, /api/reset, /api/health
│   ├── agent/
│   │   ├── core.py            # the reason→act→observe loop
│   │   ├── prompts.py         # the system prompt (persona + routing policy)
│   │   └── llm/               # provider-agnostic LLM layer
│   │       ├── base.py        # LLMClient interface + AssistantTurn/ToolCall
│   │       ├── anthropic_client.py
│   │       └── openai_client.py
│   ├── tools/                 # the agent's capabilities
│   │   ├── registry.py        # @tool decorator + dispatcher (AUTH ENFORCED HERE)
│   │   ├── client_tools.py    # lookup, status, documents, log_document
│   │   ├── auth_tools.py      # send_otp, verify_otp
│   │   ├── lead_tools.py      # share_link, create_lead, notify_adviser
│   │   └── knowledge_tools.py # get_loan_info (grounded FAQ)
│   ├── services/              # mock infrastructure
│   │   ├── mock_db.py         # clients, advisers, products (in-memory)
│   │   ├── otp.py             # mock OTP (no real SMS)
│   │   ├── notifications.py   # mock adviser notifications (console + log)
│   │   └── sessions.py        # per-session state + thread-safe store
│   └── channels/
│       └── cli.py             # terminal channel (proves the core is reusable)
├── web/index.html             # branded single-file chat UI
├── tests/                     # 28 offline tests
├── requirements.txt, .env.example, run.sh
```

The dependency direction is strictly one-way: **channels → agent → tools →
services**. Nothing lower ever imports something higher, which is what keeps the
core easy to reason about and grow.

---

## 4. The agentic core (how it actually works)

`app/agent/core.py` is ~50 lines and contains the whole "intelligence" wiring:

```
append user message
loop (max 6 steps):
    turn = llm.complete(system_prompt, history, tool_schemas)
    record the assistant turn (text + any tool calls)
    if the model asked for no tools:
        return its text reply          # done
    for each requested tool call:
        result = dispatch(session, name, args)   # auth enforced here
        append the result to history
    # loop again — the model now sees the results and decides what's next
return graceful fallback if the budget is exhausted
```

Key properties:

- **The model decides routing.** "Am I talking to a known client?" "Do I need an
  OTP first?" "Should I share a link or hand off to a human?" — none of this is
  `if/else` in Python. The model reasons over the system prompt + tool results.
- **Tools ground every factual claim.** The model can't invent an application
  status; it must call `get_application_status`. This is what stops
  hallucination on the facts that matter.
- **Multi-tool turns work.** The model can call `lookup_client` then
  `get_application_status` then `get_outstanding_documents` in one user turn; the
  loop feeds each result back before the model writes its reply.
- **Bounded.** `MAX_AGENT_STEPS` (default 6) caps tool rounds so a confused model
  can never loop forever; it falls back to a human hand-off offer.

### Provider-agnostic LLM layer

`app/agent/llm/base.py` defines a tiny interface — `complete(system, messages,
tools) -> AssistantTurn`. Two adapters implement it (`AnthropicClient`,
`OpenAIClient`), each translating our neutral message/tool shapes into that
vendor's API and parsing tool calls back out. The agent loop never imports a
vendor SDK directly. Switching providers is one env var (`LLM_PROVIDER`); adding
a third (Gemini, a local model) is one new adapter file.

---

## 5. Extensibility — "structured to grow"

The brief explicitly cares about growth into *channel partners, multiple
frontends, and a larger tool set*. Each has a concrete answer here:

**A larger tool set.** Adding a capability is a one-function change:

```python
@tool(
    name="get_emi_estimate",
    description="Estimate the monthly EMI for a loan amount, rate and tenure.",
    parameters={
        "type": "object",
        "properties": {
            "amount": {"type": "number"},
            "rate":   {"type": "number"},
            "years":  {"type": "integer"},
        },
        "required": ["amount", "rate", "years"],
    },
    scope=Scope.PUBLIC,
)
def get_emi_estimate(session, amount, rate, years):
    ...
    return {"emi": ...}
```

Decorate it, and the agent automatically sees it and can call it. No change to
the loop, the prompt wiring, or the channels.

**Multiple frontends.** The agent core takes a `(session, message)` and returns
text. The web API and the CLI are both ~30-line shells around the same
`Agent.handle`. A WhatsApp or Slack webhook would be another thin channel — the
brain doesn't change.

**Channel partners (DSAs/brokers).** Sessions carry a `role`, and
`notify_adviser` already routes a `channel_partner` hand-off to a dedicated
**Partnerships Desk** instead of a retail adviser (see `_DESK_ROUTING` in
`lead_tools.py`). New partner types or routing rules live in that one map.

---

## 6. Personalisation & tone

The system prompt (`app/agent/prompts.py`) instructs the assistant to:

- Address recognised clients by **first name** and reference their **specific
  product, stage, and named adviser**.
- Use Indian money conventions (**₹, lakh, crore**) and Nestara's real product
  names, rates and links.
- Stay **warm and concise**, ask **one question at a time**, and never dump a
  form on the user.
- Be honest about being an AI assistant and hand off to a human when asked.

Because the facts come from tools (not the prompt), personalisation is accurate:
the assistant says "Your home-loan application is *Sanctioned – Awaiting
Disbursal*, Vikram" because the tool returned exactly that.

---

## 7. Edge cases handled

| Situation | Behaviour |
|---|---|
| Unknown number at lookup | Not authorised; agent offers OTP verification or lead capture. |
| Wrong OTP | Attempts decrement; clear feedback; **locks after 3** tries. |
| Expired OTP | Rejected with an `expired` status; agent offers to resend. |
| **Cross-client access** | The dispatcher ignores any `client_id` the model supplies and serves **only** the session's authorised client — a prompt-injection cannot read someone else's data. |
| Ambiguous / off-topic message | The model asks a clarifying question instead of guessing or calling a tool blindly. |
| Mid-conversation drop-off | State lives in the session; the user can resume. If the agent gets stuck it offers a human hand-off rather than stalling. |
| Runaway tool loop | `MAX_AGENT_STEPS` budget → graceful fallback to adviser hand-off. |
| Bad tool arguments | Caught in the dispatcher, returned as a structured error the agent can recover from conversationally. |

---

## 8. Security note (auth is in code, not the prompt)

Tools are tagged `PUBLIC` or `ACCOUNT`. `ACCOUNT` tools (status, documents, log
document) are refused by the **dispatcher** unless the session is authorised for
a client — and the dispatcher, not the model, chooses *which* client's data is
returned. Prompt instructions are persuasion; this is enforcement. Even a
jailbroken or confused model physically cannot leak one client's data to
another.

Two policies ship (`AUTH_POLICY`):

- `recognition` (default) — a client identified by their registered number is
  trusted immediately. This matches the brief.
- `strict` — even recognised clients must pass an OTP before any account data is
  released. This is the production-grade setting; flip the env var to enable it.

---

## 9. Mock data for the demo

All in `app/services/mock_db.py`. Four clients spanning different journey stages:

| Name | Registered mobile | Product | Stage |
|---|---|---|---|
| Aarav Sharma | `+91 98765 43210` | New Home Loan | Documents Pending |
| Priya Iyer | `+91 91234 56780` | Balance Transfer | Under Review – Credit Assessment |
| Vikram Nair | `+91 99876 54321` | New Home Loan | Sanctioned – Awaiting Disbursal |
| Ananya Gupta | `+91 90000 12345` | Loan Against Property | Eligibility Confirmed – Application Started |

Any other number is treated as an unknown prospect (→ OTP path). In demo mode
(`OTP_DEV_ECHO=true`) the mock OTP is echoed back in the UI so you don't need an
SMS gateway. Adviser notifications print to the server console (cyan) and append
to `logs/adviser_notifications.log`.

---

## 10. Suggested demo script (3 conversations)

**A. Known client, personalised.**
> "Hi, this is Aarav, +91 98765 43210." → agent recognises him →
> "What's my application status?" → *Documents Pending* + the specific documents
> still outstanding.

**B. Document upload + adviser notify.**
> (still Aarav) attach a file, or say "I've uploaded my salary slips." → agent
> acknowledges and confirms it has notified his adviser, Sneha Reddy → check the
> server console / `logs/adviser_notifications.log` for the notification.

**C. Unknown prospect → OTP → journey or human.**
> New number → "I'm looking for a home loan." → agent triggers OTP → enter the
> echoed code → verified → agent shares the New Home Loan journey link, or, if
> you ask for a person, collects your details and hands off to an adviser.

---

## 11. Testing

```bash
./run.sh test          # or: PYTHONPATH=. python -m unittest discover -s tests -v
```

28 tests, all offline (no network, no API key):

- `test_services.py` — mock DB lookups (phone formats, email case), OTP
  send/verify/wrong/lockout/expiry, session state.
- `test_tools.py` — every tool schema is well-formed; **authorisation** (blocked
  when unauthorised, cross-client access denied, recognition flow); prospect flow
  (OTP promotion, lead + hand-off, partner routing, link sharing, grounded KB).
- `test_agent_loop.py` — the loop itself with a scripted fake LLM: tool-then-final
  answer, multi-tool single turn, and the step-budget graceful fallback.

---

## 12. Tech stack

Python 3.11+ · FastAPI · Uvicorn · Anthropic / OpenAI SDKs (pluggable) ·
vanilla-JS single-file web UI · stdlib `unittest`. No database or message broker
required — the mock services are in-memory by design so the assignment runs with
a single command.
