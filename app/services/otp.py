"""Mocked OTP service.

No SMS provider is wired up (per the brief). Instead we:
  * generate a 6-digit code,
  * "send" it by logging to the console and the notifications log,
  * enforce expiry + a maximum number of verification attempts.

The code never leaves this module via a tool result unless ``OTP_DEV_ECHO`` is
on (a demo convenience). That keeps the security story honest: in production
the code reaches the user only through the SMS channel.
"""
from __future__ import annotations

import random
import threading
import time
from dataclasses import dataclass, field

from app.config import settings
from app.services import notifications

_lock = threading.Lock()


@dataclass
class _OtpRecord:
    code: str
    expires_at: float
    attempts_left: int
    verified: bool = field(default=False)


# Keyed by the last-10-digits of the phone number.
_store: dict[str, _OtpRecord] = {}


def _key(phone: str) -> str:
    digits = "".join(ch for ch in phone if ch.isdigit())
    return digits[-10:] if len(digits) >= 10 else digits


def send_otp(phone: str) -> dict:
    """Generate and 'send' a one-time code. Returns metadata (never the raw code
    unless dev echo is enabled)."""
    key = _key(phone)
    if len(key) < 10:
        return {"status": "error", "reason": "invalid_phone"}

    code = f"{random.randint(0, 999999):06d}"
    with _lock:
        _store[key] = _OtpRecord(
            code=code,
            expires_at=time.time() + settings.otp_ttl_seconds,
            attempts_left=settings.otp_max_attempts,
        )

    # "Delivery" — in demo mode we print the real code to the server console (the
    # cyan log line) so a presenter can read it like an SMS. The code is NEVER put
    # into the tool result, so the model never sees it and cannot reveal it in
    # chat. In production (dev echo off) we log only that a code was sent.
    if settings.otp_dev_echo:
        notifications.log_event(
            "OTP_SENT",
            f"OTP for +91 ******{key[-4:]} is {code} (valid {settings.otp_ttl_seconds}s)",
        )
    else:
        notifications.log_event(
            "OTP_SENT",
            f"OTP sent to +91 ******{key[-4:]} (valid {settings.otp_ttl_seconds}s)",
        )

    return {
        "status": "sent",
        "phone_masked": f"+91 ******{key[-4:]}",
        "expires_in_seconds": settings.otp_ttl_seconds,
    }


def verify_otp(phone: str, code: str) -> dict:
    """Check a submitted code. Handles expiry, wrong codes and attempt limits."""
    key = _key(phone)
    with _lock:
        record = _store.get(key)
        if record is None:
            return {"status": "no_otp", "reason": "No active code. Request a new OTP."}
        if time.time() > record.expires_at:
            del _store[key]
            return {"status": "expired", "reason": "Code expired. Request a new OTP."}
        if record.attempts_left <= 0:
            del _store[key]
            return {"status": "locked", "reason": "Too many attempts. Request a new OTP."}

        submitted = "".join(ch for ch in (code or "") if ch.isdigit())
        if submitted == record.code:
            record.verified = True
            del _store[key]
            return {"status": "verified", "phone_masked": f"+91 ******{key[-4:]}"}

        record.attempts_left -= 1
        return {
            "status": "mismatch",
            "attempts_left": record.attempts_left,
            "reason": "Incorrect code.",
        }


def reset() -> None:
    """Test helper — clears all pending codes."""
    with _lock:
        _store.clear()


def _peek_code(phone: str) -> str | None:
    """Test helper — return the pending code for a number. Not used in app flow;
    the real code only ever reaches a user via the (mocked) delivery channel."""
    with _lock:
        record = _store.get(_key(phone))
        return record.code if record else None
