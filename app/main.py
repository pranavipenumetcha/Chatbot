"""FastAPI web server — one *channel* on top of the shared agent core.

Endpoints:
  GET  /            -> the web chat UI
  POST /api/chat    -> {session_id?, message} -> {session_id, reply, client_name, is_authenticated}
  POST /api/reset   -> {session_id}           -> fresh session
  GET  /api/health  -> liveness + which LLM provider is configured

The HTTP layer is deliberately thin: it owns sessions and serialisation, and
delegates all intelligence to ``Agent.handle``.
"""
from __future__ import annotations

import logging
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.agent.core import get_agent
from app.config import settings
from app.services import mock_db
from app.services.sessions import store

# ---------------------------------------------------------------------------
# Logging — configure once here so every logger in the app is visible.
# Without this, logger.info(...) calls in core.py go nowhere.
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(name)-25s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("nestara.main")

app = FastAPI(title="Nestara Assistant", version="1.0.0")

# Open CORS for easy local/demo use across ports.
# Tighten CORS_ORIGINS in production via the env var.
_cors_origins = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",")]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

_WEB_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "web")


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None


class ChatResponse(BaseModel):
    session_id: str
    reply: str
    # These let the frontend update the header chip without parsing reply text.
    # client_name: first name if a known client is recognised/verified, else None.
    # is_authenticated: True once OTP-verified or recognised (covers new prospects too).
    client_name: str | None = None
    is_authenticated: bool = False


class ResetRequest(BaseModel):
    session_id: str


@app.on_event("startup")
def _startup() -> None:
    logger.info("Nestara Assistant starting up")
    logger.info(
        "LLM provider=%s  auth_policy=%s  otp_dev_echo=%s",
        settings.llm_provider,
        settings.auth_policy,
        settings.otp_dev_echo,
    )


@app.get("/")
def index() -> FileResponse:
    return FileResponse(os.path.join(_WEB_DIR, "index.html"))


@app.get("/api/health")
def health() -> dict:
    provider = settings.llm_provider
    if provider == "auto":
        provider = (
            "anthropic"
            if settings.anthropic_api_key
            else "openai"
            if settings.openai_api_key
            else "none"
        )
    return {"status": "ok", "provider": provider, "auth_policy": settings.auth_policy}


@app.post("/api/chat", response_model=ChatResponse)
def chat(req: ChatRequest) -> ChatResponse:
    session = store.get_or_create(req.session_id)
    logger.info("chat session=%s message_len=%d", session.id, len(req.message))
    reply = get_agent().handle(session, req.message)

    # Resolve client name — look up the DB rather than parsing reply text.
    client_name: str | None = None
    if session.authorized_client_id:
        client = mock_db.get_client(session.authorized_client_id)
        if client:
            client_name = client["name"].split()[0]  # first name only

    return ChatResponse(
        session_id=session.id,
        reply=reply,
        client_name=client_name,
        is_authenticated=session.is_authenticated,
    )


@app.post("/api/reset")
def reset(req: ResetRequest) -> dict:
    store.reset(req.session_id)
    logger.info("session reset session=%s", req.session_id)
    return {"status": "reset", "session_id": req.session_id}