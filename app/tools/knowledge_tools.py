"""Grounded knowledge tool.

Keeps the assistant factual about Nestara. Rather than letting the model invent
rates or process steps, it pulls answers from this curated knowledge base. As
the real FAQ grows, this becomes a retrieval call against a docs index — the
tool signature stays identical.
"""
from __future__ import annotations

from app.services import mock_db
from app.services.sessions import Session
from app.tools.registry import Scope, tool

_KB: dict[str, str] = {
    "about": (
        "Nestara (formerly Loan Network) is an AI-powered home-loan platform — not "
        "a lender. It compares offers across 30+ banks and NBFCs, matches options "
        "to the customer's real profile, and charges 0% commission to the customer."
    ),
    "process": (
        "The digital journey has three steps: (1) check eligibility and find "
        "lender-fit offers in seconds, (2) submit documents online in minutes, and "
        "(3) get sanctioned — for eligible cases, within hours rather than days. "
        "An adviser supports the customer wherever guidance is needed."
    ),
    "rates": (
        "Indicative starting rates: New Home Loan from 7.10% p.a., Loan Against "
        "Property from 8% p.a. Balance Transfer can save up to ~40% on interest, "
        "and Top-up offers up to ₹2 Cr of extra funds. Final rates and approvals "
        "are always at lender discretion."
    ),
    "eligibility": (
        "Eligibility depends on income, credit profile, the property and "
        "lender-specific policy. Customers can check eligibility on Nestara before "
        "applying, and even before finalising a property. A soft credit check has "
        "no impact on the credit score."
    ),
    "documents": (
        "Typical documents: identity (PAN, Aadhaar), income proof (salary slips / "
        "ITR), 6 months' bank statements, and property papers. Exact requirements "
        "vary by lender and product."
    ),
    "privacy": (
        "Nestara uses customer information only with consent, follows CICRA-"
        "compliant credit checks, and never sells data or spams. It is RBI "
        "compliant and operated by Loan Network Technologies Pvt. Ltd."
    ),
    "balance_transfer": (
        "A balance transfer moves an existing home loan to a lender offering a "
        "lower interest rate, reducing EMI or tenure. It can be combined with a "
        "top-up for extra funds."
    ),
    "top_up": (
        "A top-up provides additional funds on top of an existing home loan, "
        "usually at home-loan rates — useful for renovation or other needs."
    ),
    "contact": (
        "Support: support@nestara.in, +91 77188 27472. Customers can also book a "
        "free 15-minute call with an adviser — no pressure, no commitment."
    ),
}


@tool(
    name="get_loan_info",
    description=(
        "Look up factual information about Nestara and its home-loan products so "
        "you answer accurately instead of guessing. Topics: about, process, rates, "
        "eligibility, documents, privacy, balance_transfer, top_up, contact, "
        "products. Use for any general (non-account) question."
    ),
    parameters={
        "type": "object",
        "properties": {
            "topic": {
                "type": "string",
                "description": (
                    "One of: about, process, rates, eligibility, documents, "
                    "privacy, balance_transfer, top_up, contact, products."
                ),
            }
        },
        "required": ["topic"],
    },
    scope=Scope.PUBLIC,
)
def get_loan_info(session: Session, topic: str) -> dict:
    key = (topic or "").strip().lower()
    if key in ("products", "product", "catalogue", "catalog"):
        return {
            "products": [
                {
                    "name": p["name"],
                    "rate_from": p["rate_from"],
                    "blurb": p["blurb"],
                    "link": p["link"],
                }
                for p in mock_db.all_products()
            ]
        }
    if key in _KB:
        return {"topic": key, "info": _KB[key]}
    # Unknown topic — hand back the menu plus the general overview so the agent
    # can still respond usefully rather than hitting a dead end.
    return {
        "topic": key,
        "info": _KB["about"],
        "available_topics": sorted(list(_KB.keys()) + ["products"]),
    }
