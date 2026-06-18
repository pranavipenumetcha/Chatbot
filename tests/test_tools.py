"""Tool + dispatcher tests, with the authorisation guardrail front and centre.

These prove the security property the prompt cannot guarantee on its own: account
data is unreachable without authorisation, and one session can never read another
client's record.
"""
import unittest

from app import tools
from app.services import mock_db, otp
from app.services.sessions import Session


class SchemaTests(unittest.TestCase):
    def test_every_tool_schema_well_formed(self):
        for s in tools.get_schemas():
            self.assertIn("name", s)
            self.assertTrue(s["description"])
            self.assertEqual(s["parameters"].get("type"), "object")

    def test_expected_tools_registered(self):
        names = {s["name"] for s in tools.get_schemas()}
        expected = {
            "lookup_client", "get_application_status", "get_outstanding_documents",
            "log_document", "send_otp", "verify_otp", "create_lead",
            "share_application_link", "notify_adviser", "get_loan_info",
        }
        self.assertTrue(expected.issubset(names), expected - names)


class AuthorizationTests(unittest.TestCase):
    def setUp(self):
        otp.reset()
        self.session = Session(id="t-auth")

    def test_account_tool_blocked_when_unauthorised(self):
        res = tools.dispatch(self.session, "get_application_status", {})
        self.assertEqual(res["error"], "authorization_required")

    def test_recognition_authorises_then_status_works(self):
        look = tools.dispatch(self.session, "lookup_client", {"identifier": "+91 98765 43210"})
        self.assertTrue(look["found"])
        self.assertEqual(look["first_name"], "Aarav")
        # Under the default "recognition" policy the session is now authorised.
        status = tools.dispatch(self.session, "get_application_status", {})
        self.assertEqual(status["name"], "Aarav Sharma")
        self.assertEqual(status["stage"], "Documents Pending")

    def test_cannot_read_a_different_client(self):
        tools.dispatch(self.session, "lookup_client", {"identifier": "+91 98765 43210"})
        # Try to force-read another client's record by passing their id.
        status = tools.dispatch(
            self.session, "get_application_status", {"client_id": "CL-1002"}
        )
        # Dispatcher ignores the injected id and serves only the authorised client.
        self.assertEqual(status["name"], "Aarav Sharma")

    def test_unknown_lookup_does_not_authorise(self):
        look = tools.dispatch(self.session, "lookup_client", {"identifier": "+91 00000 00000"})
        self.assertFalse(look["found"])
        res = tools.dispatch(self.session, "get_application_status", {})
        self.assertEqual(res["error"], "authorization_required")

    def test_log_document_notifies_adviser(self):
        before = len(mock_db.NOTIFICATIONS)
        tools.dispatch(self.session, "lookup_client", {"identifier": "+91 98765 43210"})
        res = tools.dispatch(
            self.session, "log_document", {"document_name": "salary slips"}
        )
        self.assertEqual(res["status"], "logged")
        self.assertEqual(res["adviser_notified"], "Sneha Reddy")
        self.assertEqual(len(mock_db.NOTIFICATIONS), before + 1)

    def test_unknown_tool(self):
        self.assertEqual(
            tools.dispatch(self.session, "nope", {})["error"], "unknown_tool"
        )


class ProspectFlowTests(unittest.TestCase):
    def setUp(self):
        otp.reset()
        self.session = Session(id="t-prospect")

    def test_otp_promotion_for_known_number(self):
        sent = tools.dispatch(self.session, "send_otp", {"phone": "+91 91234 56780"})
        code = otp._peek_code("+91 91234 56780")
        res = tools.dispatch(self.session, "verify_otp", {"code": code})
        self.assertEqual(res["status"], "verified")
        # That number belongs to Priya -> session becomes authorised for her.
        self.assertEqual(self.session.authorized_client_id, "CL-1002")

    def test_create_lead_and_handoff(self):
        lead = tools.dispatch(
            self.session, "create_lead",
            {"name": "Rohit", "phone": "9000000000", "interest": "new home loan"},
        )
        self.assertEqual(lead["status"], "captured")
        self.assertTrue(self.session.lead_id)
        handoff = tools.dispatch(
            self.session, "notify_adviser",
            {"summary": "Rohit wants a 50L home loan", "desk": "new_home_loan"},
        )
        self.assertEqual(handoff["status"], "handed_off")
        self.assertEqual(handoff["adviser_name"], "Sneha Reddy")

    def test_channel_partner_routes_to_partnerships(self):
        tools.dispatch(
            self.session, "create_lead",
            {"name": "DSA Co", "phone": "9111111111", "role": "channel_partner"},
        )
        self.assertEqual(self.session.role, "partner")
        handoff = tools.dispatch(
            self.session, "notify_adviser",
            {"summary": "DSA onboarding", "desk": "channel_partner"},
        )
        self.assertEqual(handoff["adviser_name"], "Partnerships Desk")

    def test_share_link(self):
        res = tools.dispatch(self.session, "share_application_link", {"product": "top_up"})
        self.assertIn("nestara.in", res["link"])

    def test_knowledge_grounded(self):
        res = tools.dispatch(self.session, "get_loan_info", {"topic": "rates"})
        self.assertIn("7.10%", res["info"])


if __name__ == "__main__":
    unittest.main()
