"""Central configuration, driven entirely by environment variables.

Keeping config in one typed place (instead of scattering ``os.getenv`` calls)
is part of the "clean thinking" goal: every knob the system exposes is visible
here, documented, and easy to override per-environment.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

try:
    # Optional: load a local .env if python-dotenv is installed.
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover - dotenv is a convenience, not a requirement
    pass


def _get_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _get_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class Settings:
    # --- LLM provider selection -------------------------------------------------
    # "auto" picks whichever provider has an API key configured.
    llm_provider: str = os.getenv("LLM_PROVIDER", "auto").strip().lower()
    anthropic_api_key: str | None = os.getenv("ANTHROPIC_API_KEY")
    openai_api_key: str | None = os.getenv("OPENAI_API_KEY")
    anthropic_model: str = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")
    openai_model: str = os.getenv("OPENAI_MODEL", "gpt-4o")
    # Optional override for the OpenAI-compatible endpoint. Leave blank for real
    # OpenAI; set to use a compatible host such as Groq, Together, Cerebras, etc.
    openai_base_url: str | None = os.getenv("OPENAI_BASE_URL") or None

    # --- Agent loop -------------------------------------------------------------
    # Upper bound on tool-call rounds per user turn. Prevents runaway loops while
    # leaving comfortable headroom for multi-tool reasoning (lookup -> status ->
    # documents in a single turn, for example).
    max_agent_steps: int = _get_int("MAX_AGENT_STEPS", 6)
    # 4096 gives comfortable headroom for multi-tool turns.
    # 1024 was too low and risked truncating replies mid-sentence.
    max_tokens: int = _get_int("MAX_TOKENS", 4096)

    # --- Authentication policy --------------------------------------------------
    # "recognition" : a client identified by their registered number is trusted
    #                 immediately (matches the assignment brief).
    # "strict"      : even recognised clients must pass OTP before account data is
    #                 released (production-grade; flip this on for a real deploy).
    auth_policy: str = os.getenv("AUTH_POLICY", "recognition").strip().lower()

    # --- OTP (mocked) -----------------------------------------------------------
    otp_ttl_seconds: int = _get_int("OTP_TTL_SECONDS", 300)
    otp_max_attempts: int = _get_int("OTP_MAX_ATTEMPTS", 3)
    # SECURITY: In production the OTP code only ever reaches the user via SMS.
    # This flag is OFF by default. Set OTP_DEV_ECHO=true in .env only for demos
    # where you want the presenter to read the code off the server console.
    otp_dev_echo: bool = _get_bool("OTP_DEV_ECHO", False)

    # --- Misc -------------------------------------------------------------------
    log_dir: str = os.getenv("LOG_DIR", "logs")


settings = Settings()