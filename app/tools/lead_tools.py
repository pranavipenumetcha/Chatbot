"""Lead capture, application-link sharing and human hand-off tools.

These cover the prospect and channel-partner journeys: someone who isn't an
existing customer but wants to start a loan or talk to a person.
"""
from __future__ import annotations

from app.services import mock_db, notifications
from app.services.sessions import Session
from app.tools.registry import Scope, tool

# Maps a free-text desk hint to an adviser. Easy to extend as desks grow.
_DESK_ROUTING = {
    "new_home_loan": "ADV-SNEHA",
    "balance_transfer": "ADV-ROHAN",
    "top_up": "ADV-ROHAN",
    "loan_against_property": "ADV-KARAN",
    "partner": "ADV-PARTNERS",
    "channel_partner": "ADV-PARTNERS",
}


def _route_adviser(hint: str | None) -> dict:
    if hint:
        adviser_id = _DESK_ROUTING.get(hint.strip().lower())
        if adviser_id:
            return mock_db.get_adviser(adviser_id)
    # Default queue: the new-home-loan desk handles general enquiries.
    return mock_db.get_adviser("ADV-SNEHA")


@tool(
    name="share_application_link",
    description=(
        "Share the link to start Nestara's online application for a product. Use "
        "when a prospect wants to begin their loan journey themselves. If no "
        "product is given, returns the new home loan link plus the full catalogue."
    ),
    parameters={
        "type": "object",
        "properties": {
            "product": {
                "type": "string",
                "enum": [
                    "new_home_loan",
                    "balance_transfer",
                    "top_up",
                    "loan_against_property",
                ],
                "description": "Which product the user is interested in.",
            }
        },
    },
    scope=Scope.PUBLIC,
)
def share_application_link(session: Session, product: str | None = None) -> dict:
    if product:
        p = mock_db.get_product(product)
        if p:
            return {"product": p["name"], "link": p["link"], "rate_from": p["rate_from"]}
    return {
        "default": mock_db.get_product("new_home_loan"),
        "all_products": [
            {"name": p["name"], "link": p["link"], "rate_from": p["rate_from"]}
            for p in mock_db.all_products()
        ],
    }


@tool(
    name="create_lead",
    description=(
        "Capture a prospect's or channel partner's details for follow-up. Use "
        "after the user is verified and wants a human to help, or identifies as a "
        "DSA/channel partner. Collect at least a name and phone before calling."
    ),
    parameters={
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "phone": {"type": "string"},
            "email": {"type": "string"},
            "interest": {
                "type": "string",
                "description": "What they want, e.g. 'new home loan ₹50L', 'balance transfer'.",
            },
            "role": {
                "type": "string",
                "enum": ["prospect", "channel_partner"],
                "description": "Defaults to prospect. Use channel_partner for DSAs/partners.",
            },
            "notes": {"type": "string", "description": "Any useful context."},
        },
        "required": ["name", "phone"],
    },
    scope=Scope.PUBLIC,
)
def create_lead(
    session: Session,
    name: str,
    phone: str,
    email: str = "",
    interest: str = "",
    role: str = "prospect",
    notes: str = "",
) -> dict:
    lead = mock_db.record_lead(
        {
            "name": name,
            "phone": phone,
            "email": email,
            "interest": interest,
            "role": role,
            "notes": notes,
        }
    )
    session.lead_id = lead["id"]
    session.role = "partner" if role == "channel_partner" else "prospect"
    return {"status": "captured", "lead_id": lead["id"], "role": role}


@tool(
    name="notify_adviser",
    description=(
        "Hand the conversation to a human adviser by sending them a summary. Use "
        "after capturing a lead (for prospects/partners) when the user wants to "
        "talk to someone. Route with 'desk' so the right adviser is paged."
    ),
    parameters={
        "type": "object",
        "properties": {
            "summary": {
                "type": "string",
                "description": "Concise summary of who the user is and what they need.",
            },
            "desk": {
                "type": "string",
                "description": (
                    "Routing hint: a product key (new_home_loan, balance_transfer, "
                    "top_up, loan_against_property) or 'channel_partner'."
                ),
            },
        },
        "required": ["summary"],
    },
    scope=Scope.PUBLIC,
)
def notify_adviser(session: Session, summary: str, desk: str | None = None) -> dict:
    adviser = _route_adviser(desk)
    ref = session.lead_id or session.id
    result = notifications.notify_adviser(
        adviser,
        subject=f"Hand-off / callback request ({ref})",
        body=summary,
    )
    mock_db.record_notification(
        {"type": "handoff", "ref": ref, "adviser_id": adviser["id"]}
    )
    return {
        "status": "handed_off",
        "adviser_name": result["adviser_name"],
        "desk": adviser["desk"],
        "reference": ref,
    }
