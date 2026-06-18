"""Conversation session: the unit that holds context for "remember what was
said earlier in the same session".

A ``Session`` carries:
  * the full message history (so the agent never starts from scratch),
  * who the user is and whether they are authorised,
  * any in-flight OTP / lead state.

The store is in-memory (a dict) which is perfect for a demo and a single
process. The accessor functions are the seam where you would later drop in
Redis / a database without touching the agent.
"""
from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class Session:
    id: str
    # Normalised message log shared across every channel. Each item is one of:
    #   {"role": "user", "content": str}
    #   {"role": "assistant", "content": str, "tool_calls": [...]}
    #   {"role": "tool", "tool_call_id": str, "name": str, "content": str}
    messages: list[dict] = field(default_factory=list)

    # Identity / authorisation -------------------------------------------------
    recognized_client_id: Optional[str] = None   # matched in the DB
    authorized_client_id: Optional[str] = None   # cleared to see account data
    verified_phone: Optional[str] = None         # OTP-verified (for prospects)
    role: str = "unknown"                         # unknown | client | prospect | partner

    # Bookkeeping --------------------------------------------------------------
    lead_id: Optional[str] = None
    scratch: dict[str, Any] = field(default_factory=dict)

    @property
    def is_authenticated(self) -> bool:
        return self.authorized_client_id is not None or self.verified_phone is not None


class SessionStore:
    """Thread-safe in-memory session registry."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sessions: dict[str, Session] = {}

    def get_or_create(self, session_id: Optional[str]) -> Session:
        with self._lock:
            if session_id and session_id in self._sessions:
                return self._sessions[session_id]
            new_id = session_id or uuid.uuid4().hex
            session = Session(id=new_id)
            self._sessions[new_id] = session
            return session

    def get(self, session_id: str) -> Optional[Session]:
        with self._lock:
            return self._sessions.get(session_id)

    def reset(self, session_id: str) -> Session:
        """Drop a session and return a fresh one with the same id."""
        with self._lock:
            session = Session(id=session_id)
            self._sessions[session_id] = session
            return session


# Process-wide singleton.
store = SessionStore()
