"""Mocked notification channel.

"A log or email is fine" per the brief. We write structured lines to both the
console and ``logs/adviser_notifications.log``. Swapping in real email/SMS/Slack
later means changing only ``_emit`` — callers stay the same.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

from app.config import settings

_LOG_PATH = os.path.join(settings.log_dir, "adviser_notifications.log")


def _emit(line: str) -> None:
    os.makedirs(settings.log_dir, exist_ok=True)
    stamped = f"[{datetime.now(timezone.utc).isoformat()}] {line}"
    # Console — visible while the server runs.
    print(f"\033[96m🔔 {stamped}\033[0m", flush=True)
    # Durable log — survives the process, easy to show in a demo.
    with open(_LOG_PATH, "a", encoding="utf-8") as fh:
        fh.write(stamped + "\n")


def log_event(kind: str, message: str) -> None:
    """Generic structured event (used for OTP delivery, system notices, etc.)."""
    _emit(f"{kind}: {message}")


def notify_adviser(adviser: dict, subject: str, body: str) -> dict:
    """'Send' a notification to a specific adviser."""
    _emit(
        f"ADVISER_NOTIFICATION -> {adviser['name']} <{adviser['email']}> "
        f"| {subject} | {body}"
    )
    return {
        "status": "notified",
        "adviser_name": adviser["name"],
        "adviser_email": adviser["email"],
        "subject": subject,
    }
