"""Mocked OTP service.

No SMS provider is wired up (per the brief). Instead we:
  * generate a 6-digit code,
  * "send" it by logging to the console and the notifications log,
  * enforce expiry + a maximum number of verification attempts.

The code never leaves this module via a tool result unless ``OTP_DEV_ECHO`` is
on (a demo convenience, default OFF). That keeps the security story honest: in
production the code reaches the user only through the SMS channel.

Every function returns a dict with a 'status' string that the agent reads
directly from the tool result — no hardcoding of outcomes in the prompt.
"""
from __future__ import annotations

import random
import re
import threading
import time
from dataclasses import dataclass, field

from app.config import settings
from app.services import notifications

_lock = threading.Lock()

# Valid Indian mobile: optional country code (+91 / 91 / 0), then exactly
# 10 digits starting with 6, 7, 8, or 9.
# Examples accepted:  9876543210  |  +91 98765 43210  |  091-9876-543210
# Examples rejected:  13241243414 (wrong prefix/length)  |  1234567890 (starts with 1)
_MOBILE_RE = re.compile(r'^(?:\+?91|0)?([6-9]\d{9})$')


@dataclass
class _OtpRecord:
    code: str
    expires_at: float
    attempts_left: int
    verified: bool = field(default=False)


# Keyed by the validated 10-digit mobile number.
_store: dict[str, _OtpRecord] = {}


def _extract_mobile(phone: str) -> str | None:
    """Return the canonical 10-digit number, or None if invalid.

    Strips spaces, dashes, parentheses then checks the regex. Returns only
    the 10-digit subscriber number (no country code).
    """
    digits = "".join(ch for ch in (phone or "") if ch.isdigit())
    m = _MOBILE_RE.match(digits)
    return m.group(1) if m else None


def _key(phone: str) -> str:
    """Return the canonical key (10-digit number) or empty string if invalid."""
    return _extract_mobile(phone) or ""


def send_otp(phone: str) -> dict:
    """Generate and 'send' a one-time code.

    Returns a dict with 'status' == 'sent' on success, or 'error' on failure.
    The raw code is never included in the return value — it only appears in the
    server console log (when otp_dev_echo is on) so the presenter can read it
    like an SMS.
    """
    key = _key(phone)
    if not key:
        return {
            "status": "error",
            "reason": "invalid_phone",
            "message": (
                "That doesn't look like a valid Indian mobile number. "
                "Please share a 10-digit number starting with 6, 7, 8, or 9 "
                "(with or without the +91 country code)."
            ),
        }

    code = f"{random.randint(0, 999999):06d}"
    with _lock:
        _store[key] = _OtpRecord(
            code=code,
            expires_at=time.time() + settings.otp_ttl_seconds,
            attempts_left=settings.otp_max_attempts,
        )

    # "Delivery" — in demo mode we print the real code to the server console so
    # a presenter can read it like an SMS. The code is NEVER put into the tool
    # result, so the model never sees it and cannot reveal it in chat.
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
        "message": f"A verification code has been sent to +91 ******{key[-4:]}. Please ask the user to enter it.",
    }


def verify_otp(phone: str, code: str) -> dict:
    """Check a submitted code. Handles expiry, wrong codes and attempt limits.

    Always returns a dict whose 'status' field is one of:
      verified  — code matched, session can be authorised
      mismatch  — wrong code, attempts_left shows remaining tries
      expired   — code too old, a new one should be sent
      locked    — too many failed attempts, code invalidated
      no_otp    — no active code for this number
      error     — invalid phone number supplied
    """
    key = _key(phone)
    if not key:
        return {
            "status": "error",
            "reason": "invalid_phone",
            "message": "That doesn't look like a valid Indian mobile number.",
        }

    with _lock:
        record = _store.get(key)
        if record is None:
            return {
                "status": "no_otp",
                "reason": "No active code for this number.",
                "message": "There is no active OTP for this number. Please send a new one first.",
            }
        if time.time() > record.expires_at:
            del _store[key]
            return {
                "status": "expired",
                "reason": "Code has expired.",
                "message": "The verification code has expired. Please request a new one.",
            }
        if record.attempts_left <= 0:
            del _store[key]
            return {
                "status": "locked",
                "reason": "Too many failed attempts.",
                "message": "This code has been invalidated after too many wrong attempts. Please request a new OTP.",
            }

        submitted = "".join(ch for ch in (code or "") if ch.isdigit())
        if submitted == record.code:
            record.verified = True
            del _store[key]
            return {
                "status": "verified",
                "phone_masked": f"+91 ******{key[-4:]}",
                "message": "Verification successful.",
            }

        record.attempts_left -= 1
        remaining = record.attempts_left
        return {
            "status": "mismatch",
            "attempts_left": remaining,
            "reason": "Incorrect code.",
            "message": (
                f"That code doesn't match. {remaining} attempt{'s' if remaining != 1 else ''} remaining."
                if remaining > 0
                else "That code doesn't match and no attempts remain. Please request a new OTP."
            ),
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