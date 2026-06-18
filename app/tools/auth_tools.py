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
        "them to an adviser. Tell the user a code has been sent to their number."
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
        "Verify the code the user provides. On success the session becomes "
        "verified. If the number happens to belong to an existing customer, they "
        "are also authorised for their account. Handles wrong/expired codes — "
        "read the returned status and respond accordingly."
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
        return {"status": "no_otp", "reason": "No number on file — send an OTP first."}

    result = otp.verify_otp(phone, code)
    if result.get("status") == "verified":
        session.verified_phone = phone
        if session.role == "unknown":
            session.role = "prospect"
        # If this verified number is a known customer, authorise their account
        # (this is the path that matters under the strict policy).
        client = mock_db.find_client(phone)
        if client is not None:
            session.recognized_client_id = client["id"]
            session.authorized_client_id = client["id"]
            session.role = "client"
            result["recognised_client_first_name"] = client["name"].split()[0]
    return result
