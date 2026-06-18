"""Tool registry + dispatcher.

This is the backbone of the agentic design. Tools are plain Python functions
registered with a decorator. Each declares:
  * a JSON-schema for its arguments (what the LLM sees),
  * an auth scope (enforced here, NOT left to the model's good behaviour).

Adding a capability later is a one-function change: write the function, decorate
it, done. The agent automatically gains access to it. This is what "extends to a
larger tool set" looks like in practice.

Auth scopes
-----------
PUBLIC   : callable by anyone (FAQs, OTP, lead capture, sharing links).
ACCOUNT  : touches a specific client's private data. The dispatcher refuses
           unless the session is authorised for *that* client_id, returning a
           structured ``authorization_required`` result the agent can react to
           (e.g. by asking for the registered number / triggering OTP).

Doing authorisation at the dispatch layer means a prompt-injection or a confused
model still cannot leak one client's data to another — the guardrail is in code.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Callable

from app.services.sessions import Session


class Scope(str, Enum):
    PUBLIC = "public"
    ACCOUNT = "account"


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict          # JSON schema (object)
    scope: Scope
    handler: Callable[..., dict]


_REGISTRY: dict[str, ToolSpec] = {}


def tool(name: str, description: str, parameters: dict, scope: Scope = Scope.PUBLIC):
    """Decorator that registers a function as an agent tool.

    The wrapped handler is always called as ``handler(session, **args)``.
    """

    def decorator(func: Callable[..., dict]) -> Callable[..., dict]:
        if name in _REGISTRY:
            raise ValueError(f"Duplicate tool name: {name}")
        _REGISTRY[name] = ToolSpec(
            name=name,
            description=description,
            parameters=parameters,
            scope=scope,
            handler=func,
        )
        return func

    return decorator


def get_specs() -> list[ToolSpec]:
    return list(_REGISTRY.values())


def get_schemas() -> list[dict]:
    """Provider-neutral schemas. The LLM adapters reshape these for each API."""
    return [
        {"name": s.name, "description": s.description, "parameters": s.parameters}
        for s in _REGISTRY.values()
    ]


def _client_id_for(session: Session, requested_id: str | None) -> str | None:
    """Resolve which client an ACCOUNT tool may operate on.

    The session's ``authorized_client_id`` is the *sole* source of truth. Any
    ``client_id`` the model supplies is deliberately discarded: the model never
    gets to choose whose record is read. If the session is authorised, the tool
    always acts on that client; if not, the dispatcher refuses. This makes a
    confused model or a prompt-injection physically unable to read another
    client's data — the guardrail is in code, not in the prompt.
    """
    # ``requested_id`` is intentionally ignored.
    return session.authorized_client_id


def dispatch(session: Session, name: str, args: dict) -> dict:
    """Execute a tool by name with authorisation + error handling.

    Always returns a JSON-serialisable dict. Errors are returned (not raised) so
    the agent can read them and recover conversationally.
    """
    spec = _REGISTRY.get(name)
    if spec is None:
        return {"error": "unknown_tool", "tool": name}

    args = dict(args or {})

    if spec.scope is Scope.ACCOUNT:
        resolved = _client_id_for(session, args.get("client_id"))
        if resolved is None:
            return {
                "error": "authorization_required",
                "message": (
                    "This action needs a verified account. Ask the user for the "
                    "mobile number registered with Nestara, look them up, and if "
                    "they are not recognised, verify them with an OTP first."
                ),
            }
        # Inject the authorised id so the handler always acts on the right client.
        args["client_id"] = resolved

    try:
        return spec.handler(session, **args)
    except TypeError as exc:
        # Almost always a bad/missing argument from the model.
        return {"error": "bad_arguments", "detail": str(exc)}
    except Exception as exc:  # pragma: no cover - defensive catch-all
        return {"error": "tool_failed", "detail": str(exc)}
