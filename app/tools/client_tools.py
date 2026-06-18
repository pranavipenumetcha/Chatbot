"""Tools that deal with an identified borrower's account."""
from __future__ import annotations

from app.config import settings
from app.services import mock_db, notifications
from app.services.sessions import Session
from app.tools.registry import Scope, tool


@tool(
    name="lookup_client",
    description=(
        "Identify a returning customer by the mobile number or email registered "
        "with Nestara. Call this as soon as the user gives a number/email or says "
        "they are an existing customer. Returns whether they are recognised and, "
        "if so, their first name so you can greet them personally. Does NOT return "
        "account details — use the dedicated tools for those."
    ),
    parameters={
        "type": "object",
        "properties": {
            "identifier": {
                "type": "string",
                "description": "The user's registered mobile number or email address.",
            }
        },
        "required": ["identifier"],
    },
    scope=Scope.PUBLIC,
)
def lookup_client(session: Session, identifier: str) -> dict:
    client = mock_db.find_client(identifier)
    if client is None:
        return {
            "found": False,
            "message": (
                "No Nestara account matches that detail. Treat the user as a new "
                "prospect: verify them with an OTP before collecting personal "
                "details or handing off."
            ),
        }

    session.recognized_client_id = client["id"]
    # Under the default "recognition" policy a customer identified by their
    # registered number is trusted immediately (matches the brief). Under
    # "strict" policy we hold authorisation back until OTP succeeds.
    if settings.auth_policy == "recognition":
        session.authorized_client_id = client["id"]
        session.role = "client"
        authorised = True
    else:
        authorised = False

    return {
        "found": True,
        "first_name": client["name"].split()[0],
        "authorised": authorised,
        "note": (
            "Recognised and authorised — you may share their account details."
            if authorised
            else "Recognised but not yet authorised — send an OTP to their "
            "registered number and verify before sharing account details."
        ),
    }


@tool(
    name="get_application_status",
    description=(
        "Get the authorised customer's current loan application status: product, "
        "stage, amount, proposed lender, the next step, and when it was last "
        "updated. Use this whenever they ask 'where is my application / loan'."
    ),
    parameters={"type": "object", "properties": {}},
    scope=Scope.ACCOUNT,
)
def get_application_status(session: Session, client_id: str) -> dict:
    client = mock_db.get_client(client_id)
    if client is None:  # pragma: no cover - guarded by dispatcher
        return {"error": "client_not_found"}
    product = mock_db.get_product(client["product"]) or {}
    adviser = mock_db.get_adviser(client["adviser_id"]) or {}
    outstanding = client["outstanding_documents"]
    next_step = (
        "Submit the outstanding documents so underwriting can proceed."
        if outstanding
        else "All documents are in. Your adviser will share the next update shortly."
    )
    return {
        "name": client["name"],
        "product": product.get("name", client["product"]),
        "stage": client["stage"],
        "loan_amount": client["loan_amount"],
        "lender": client["lender"],
        "outstanding_document_count": len(outstanding),
        "last_update": client["last_update"],
        "adviser_name": adviser.get("name"),
        "next_step": next_step,
    }


@tool(
    name="get_outstanding_documents",
    description=(
        "List the documents the authorised customer still needs to submit. Use "
        "when they ask what's pending / what they need to provide."
    ),
    parameters={"type": "object", "properties": {}},
    scope=Scope.ACCOUNT,
)
def get_outstanding_documents(session: Session, client_id: str) -> dict:
    client = mock_db.get_client(client_id)
    if client is None:  # pragma: no cover
        return {"error": "client_not_found"}
    return {
        "outstanding_documents": client["outstanding_documents"],
        "submitted_documents": client["submitted_documents"],
        "all_submitted": len(client["outstanding_documents"]) == 0,
    }


@tool(
    name="log_document",
    description=(
        "Record a document the customer says they have uploaded or is sending, "
        "and automatically notify their assigned adviser to review it. Call this "
        "whenever the customer mentions or attaches a document (e.g. 'I've "
        "uploaded my salary slips')."
    ),
    parameters={
        "type": "object",
        "properties": {
            "document_name": {
                "type": "string",
                "description": "Name/description of the document, e.g. 'salary slips'.",
            },
            "note": {
                "type": "string",
                "description": "Optional extra context the customer gave.",
            },
        },
        "required": ["document_name"],
    },
    scope=Scope.ACCOUNT,
)
def log_document(session: Session, client_id: str, document_name: str, note: str = "") -> dict:
    client = mock_db.get_client(client_id)
    if client is None:  # pragma: no cover
        return {"error": "client_not_found"}
    adviser = mock_db.get_adviser(client["adviser_id"]) or {}

    entry = mock_db.record_document(
        {
            "client_id": client_id,
            "client_name": client["name"],
            "document_name": document_name,
            "note": note,
            "adviser_id": client["adviser_id"],
        }
    )
    notifications.notify_adviser(
        adviser,
        subject=f"New document from {client['name']} ({client_id})",
        body=f"Document: {document_name}." + (f" Note: {note}" if note else ""),
    )
    mock_db.record_notification(
        {"type": "document", "client_id": client_id, "adviser_id": client["adviser_id"]}
    )
    return {
        "status": "logged",
        "document_id": entry["id"],
        "document_name": document_name,
        "adviser_notified": adviser.get("name"),
    }
