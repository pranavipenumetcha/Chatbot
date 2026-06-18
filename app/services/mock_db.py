"""Mock data layer.

This stands in for what would be a real CRM / loan-origination system. It is
deliberately isolated behind small accessor functions so that swapping it for a
Postgres repository or an internal API later touches *only this file* — the
tools and the agent never import the raw dicts directly.

Contents:
  * CLIENTS   - a handful of borrowers at different stages of the journey
  * ADVISERS  - the humans the assistant can hand off to
  * PRODUCTS  - Nestara's product catalogue with live application links
  * runtime stores for leads, logged documents and adviser notifications
"""
from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Optional

# --------------------------------------------------------------------------- #
# Static reference data
# --------------------------------------------------------------------------- #

ADVISERS: dict[str, dict] = {
    "ADV-SNEHA": {
        "id": "ADV-SNEHA",
        "name": "Sneha Reddy",
        "email": "sneha.reddy@nestara.in",
        "phone": "+91 80000 11111",
        "desk": "New Home Loans",
    },
    "ADV-ROHAN": {
        "id": "ADV-ROHAN",
        "name": "Rohan Mehta",
        "email": "rohan.mehta@nestara.in",
        "phone": "+91 80000 22222",
        "desk": "Balance Transfer & Top-up",
    },
    "ADV-KARAN": {
        "id": "ADV-KARAN",
        "name": "Karan Shah",
        "email": "karan.shah@nestara.in",
        "phone": "+91 80000 33333",
        "desk": "Loan Against Property",
    },
    "ADV-PARTNERS": {
        "id": "ADV-PARTNERS",
        "name": "Partnerships Desk",
        "email": "partners@nestara.in",
        "phone": "+91 80000 99999",
        "desk": "Channel Partners / DSAs",
    },
}

# Nestara's real product catalogue (rates/links sourced from nestara.in).
PRODUCTS: dict[str, dict] = {
    "new_home_loan": {
        "key": "new_home_loan",
        "name": "New Home Loan",
        "rate_from": "7.10% p.a.",
        "blurb": "Finance your home with the right lender matched to your profile.",
        "link": "https://nestara.in/products/new-home-loan",
    },
    "balance_transfer": {
        "key": "balance_transfer",
        "name": "Balance Transfer",
        "rate_from": "save up to 40% on interest",
        "blurb": "Switch your existing loan to a lender with a lower rate.",
        "link": "https://nestara.in/products/home-loan-balance-transfer",
    },
    "top_up": {
        "key": "top_up",
        "name": "Top-up Loan",
        "rate_from": "up to ₹2 Cr extra funds",
        "blurb": "Access extra funds on top of your existing home loan.",
        "link": "https://nestara.in/products/home-loan-top-up",
    },
    "loan_against_property": {
        "key": "loan_against_property",
        "name": "Loan Against Property",
        "rate_from": "8% p.a.",
        "blurb": "Unlock capital from your residential or commercial property.",
        "link": "https://nestara.in/products/loan-against-property",
    },
}

# Clients deliberately span the full journey: docs-pending, under-review,
# sanctioned-awaiting-disbursal, and a fresh application.
CLIENTS: dict[str, dict] = {
    "CL-1001": {
        "id": "CL-1001",
        "name": "Aarav Sharma",
        "phone": "+91 98765 43210",
        "email": "aarav.sharma@example.com",
        "product": "new_home_loan",
        "stage": "Documents Pending",
        "loan_amount": "₹65,00,000",
        "lender": "Matching in progress across 30+ lenders",
        "adviser_id": "ADV-SNEHA",
        "application_link": "https://nestara.in/products/new-home-loan",
        "outstanding_documents": [
            "Latest 3 months' salary slips",
            "6 months' bank statements (salary account)",
            "PAN card copy",
        ],
        "submitted_documents": ["Aadhaar", "Property allotment letter"],
        "last_update": "2026-06-15",
    },
    "CL-1002": {
        "id": "CL-1002",
        "name": "Priya Iyer",
        "phone": "+91 91234 56780",
        "email": "priya.iyer@example.com",
        "product": "balance_transfer",
        "stage": "Under Review – Credit Assessment",
        "loan_amount": "₹48,00,000 (transfer) + ₹6,00,000 (top-up)",
        "lender": "HDFC Bank (proposed)",
        "adviser_id": "ADV-ROHAN",
        "application_link": "https://nestara.in/products/home-loan-balance-transfer",
        "outstanding_documents": [],
        "submitted_documents": [
            "Existing loan statement",
            "Salary slips",
            "Bank statements",
            "Property papers",
        ],
        "last_update": "2026-06-17",
    },
    "CL-1003": {
        "id": "CL-1003",
        "name": "Vikram Nair",
        "phone": "+91 99876 54321",
        "email": "vikram.nair@example.com",
        "product": "new_home_loan",
        "stage": "Sanctioned – Awaiting Disbursal",
        "loan_amount": "₹82,00,000",
        "lender": "ICICI Bank",
        "adviser_id": "ADV-SNEHA",
        "application_link": "https://nestara.in/products/new-home-loan",
        "outstanding_documents": ["Signed loan agreement", "Post-dated cheques (NACH mandate)"],
        "submitted_documents": [
            "Salary slips",
            "Bank statements",
            "Property papers",
            "Sale agreement",
        ],
        "last_update": "2026-06-18",
    },
    "CL-1004": {
        "id": "CL-1004",
        "name": "Ananya Gupta",
        "phone": "+91 90000 12345",
        "email": "ananya.gupta@example.com",
        "product": "loan_against_property",
        "stage": "Eligibility Confirmed – Application Started",
        "loan_amount": "₹1,10,00,000",
        "lender": "Matching in progress",
        "adviser_id": "ADV-KARAN",
        "application_link": "https://nestara.in/products/loan-against-property",
        "outstanding_documents": [
            "Property title documents",
            "Latest property tax receipt",
            "2 years' ITR",
        ],
        "submitted_documents": ["PAN", "Aadhaar"],
        "last_update": "2026-06-12",
    },
}


def _normalise_phone(phone: str) -> str:
    """Reduce a phone string to its trailing 10 digits for resilient matching.

    Users type numbers many ways (+91 98765 43210, 098765-43210, 9876543210).
    Comparing only the last 10 digits makes lookup forgiving without being loose
    enough to collide across distinct numbers.
    """
    digits = "".join(ch for ch in phone if ch.isdigit())
    return digits[-10:] if len(digits) >= 10 else digits


# Pre-built indexes for O(1) lookup by phone/email.
_PHONE_INDEX = {_normalise_phone(c["phone"]): c["id"] for c in CLIENTS.values()}
_EMAIL_INDEX = {c["email"].lower(): c["id"] for c in CLIENTS.values()}


# --------------------------------------------------------------------------- #
# Runtime stores (would be DB tables in production)
# --------------------------------------------------------------------------- #

_lock = threading.Lock()
LEADS: list[dict] = []
DOCUMENT_LOG: list[dict] = []
NOTIFICATIONS: list[dict] = []


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# --------------------------------------------------------------------------- #
# Accessors — the only surface the rest of the app should use
# --------------------------------------------------------------------------- #

def find_client(identifier: str) -> Optional[dict]:
    """Look up a client by phone number or email. Returns the record or None."""
    if not identifier:
        return None
    ident = identifier.strip().lower()
    if "@" in ident:
        client_id = _EMAIL_INDEX.get(ident)
    else:
        client_id = _PHONE_INDEX.get(_normalise_phone(identifier))
    return CLIENTS.get(client_id) if client_id else None


def get_client(client_id: str) -> Optional[dict]:
    return CLIENTS.get(client_id)


def get_adviser(adviser_id: str) -> Optional[dict]:
    return ADVISERS.get(adviser_id)


def get_product(key: str) -> Optional[dict]:
    return PRODUCTS.get(key)


def all_products() -> list[dict]:
    return list(PRODUCTS.values())


def record_lead(lead: dict) -> dict:
    with _lock:
        lead = {"id": f"LEAD-{len(LEADS) + 1:04d}", "created_at": _now(), **lead}
        LEADS.append(lead)
    return lead


def record_document(entry: dict) -> dict:
    with _lock:
        entry = {"id": f"DOC-{len(DOCUMENT_LOG) + 1:04d}", "logged_at": _now(), **entry}
        DOCUMENT_LOG.append(entry)
    return entry


def record_notification(entry: dict) -> dict:
    with _lock:
        entry = {"id": f"NTF-{len(NOTIFICATIONS) + 1:04d}", "sent_at": _now(), **entry}
        NOTIFICATIONS.append(entry)
    return entry
