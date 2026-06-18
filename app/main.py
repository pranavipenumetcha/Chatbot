"""FastAPI web server — one *channel* on top of the shared agent core.

Endpoints:
  GET  /            -> the web chat UI
  POST /api/chat    -> {session_id?, message} -> {session_id, reply}
  POST /api/reset   -> {session_id}           -> fresh session
  GET  /api/health  -> liveness + which LLM provider is configured

The HTTP layer is deliberately thin: it owns sessions and serialisation, and
delegates all intelligence to ``Agent.handle``.
"""
from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.agent.core import get_agent
from app.config import settings
from app.services.sessions import store

app = FastAPI(title="Nestara Assistant", version="1.0.0")

# Open CORS for easy local/demo use across ports.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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


class ResetRequest(BaseModel):
    session_id: str


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
    reply = get_agent().handle(session, req.message)
    return ChatResponse(session_id=session.id, reply=reply)


@app.post("/api/reset")
def reset(req: ResetRequest) -> dict:
    store.reset(req.session_id)
    return {"status": "reset", "session_id": req.session_id}
