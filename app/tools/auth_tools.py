"""OTP tools — the verification path for users we don't recognise (and, under
the strict auth policy, for recognised users too)."""
from __future__ import annotations

from app.config import settings
from app.services import mock_db, otp
from app.services.sessions import Session
from app.tools.registry import Scope, tool


@tool(
    name="send_otp",
    description=(
        "Send a one-time verification code to a mobile number. Use this to verify "
        "a user we don't recognise before collecting personal details or handing "
        "them to an adviser. Tell the user a code has been sent to their number and "
        "ask them to enter it. Returns: {status: 'sent', phone_masked, "
        "expires_in_seconds} or {status: 'error', reason: 'invalid_phone'}."
    ),
    parameters={
        "type": "object",
        "properties": {
            "phone": {
                "type": "string",
                "description": "The mobile number to send the code to.",
            }
        },
        "required": ["phone"],
    },
    scope=Scope.PUBLIC,
)
def send_otp(session: Session, phone: str) -> dict:
    result = otp.send_otp(phone)
    if result.get("status") == "sent":
        # Remember which number we're verifying so the user need not retype it.
        session.scratch["otp_phone"] = phone
    return result


@tool(
    name="verify_otp",
    description=(
        "Verify the OTP code the user provides. Check the 'status' field and "
        "respond accordingly — do NOT guess or invent outcomes:\n"
        "  verified → OTP matched; session is now verified. If the number belongs "
        "to a known customer, 'recognised_client_first_name' is also returned — "
        "greet them by name.\n"
        "  mismatch → Wrong code. Tell the user and show how many attempts remain "
        "('attempts_left'). Offer to re-enter.\n"
        "  expired  → Code has expired. Offer to send a fresh OTP via send_otp.\n"
        "  locked   → Too many wrong attempts; the code is now void. Apologise and "
        "offer to escalate to a human adviser or send a new OTP.\n"
        "  no_otp   → No active code exists for this number. Offer to send one "
        "first via send_otp.\n"
        "  error    → Something went wrong (e.g. invalid phone). Report the "
        "'reason' and ask the user to check their number."
    ),
    parameters={
        "type": "object",
        "properties": {
            "code": {"type": "string", "description": "The code the user entered."},
            "phone": {
                "type": "string",
                "description": "Number being verified. Optional if one was just sent.",
            },
        },
        "required": ["code"],
    },
    scope=Scope.PUBLIC,
)
def verify_otp(session: Session, code: str, phone: str | None = None) -> dict:
    phone = phone or session.scratch.get("otp_phone")
    if not phone:
        return {
            "status": "no_otp",
            "reason": "No number on file — send an OTP first.",
        }

    result = otp.verify_otp(phone, code)
    if result.get("status") == "verified":
        session.verified_phone = phone
        if session.role == "unknown":
            session.role = "prospect"
        # If this verified number is a known customer, authorise their account.
        client = mock_db.find_client(phone)
        if client is not None:
            session.recognized_client_id = client["id"]
            session.authorized_client_id = client["id"]
            session.role = "client"
            result["recognised_client_first_name"] = client["name"].split()[0]
    return result