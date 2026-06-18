"""Service-layer tests: mock DB, OTP lifecycle, sessions.

Run from the project root:  python -m unittest discover -s tests
"""
import unittest

from app.services import mock_db, otp
from app.services.sessions import SessionStore


class MockDbTests(unittest.TestCase):
    def test_find_by_phone_various_formats(self):
        for fmt in ["+91 98765 43210", "9876543210", "098765-43210", "+919876543210"]:
            c = mock_db.find_client(fmt)
            self.assertIsNotNone(c, fmt)
            self.assertEqual(c["id"], "CL-1001")

    def test_find_by_email_case_insensitive(self):
        c = mock_db.find_client("PRIYA.IYER@example.com")
        self.assertIsNotNone(c)
        self.assertEqual(c["id"], "CL-1002")

    def test_unknown_returns_none(self):
        self.assertIsNone(mock_db.find_client("+91 00000 00000"))
        self.assertIsNone(mock_db.find_client("nobody@example.com"))

    def test_clients_span_stages(self):
        stages = {c["stage"] for c in mock_db.CLIENTS.values()}
        # At least three distinct journey stages are represented.
        self.assertGreaterEqual(len(stages), 3)


class OtpTests(unittest.TestCase):
    def setUp(self):
        otp.reset()

    def test_send_then_verify_success(self):
        sent = otp.send_otp("+91 98765 43210")
        self.assertEqual(sent["status"], "sent")
        self.assertNotIn("dev_code", sent)  # code never leaves via the result
        code = otp._peek_code("+91 98765 43210")
        res = otp.verify_otp("+91 98765 43210", code)
        self.assertEqual(res["status"], "verified")

    def test_wrong_code_decrements_attempts(self):
        otp.send_otp("9876543210")
        r1 = otp.verify_otp("9876543210", "000000")
        self.assertEqual(r1["status"], "mismatch")
        self.assertIn("attempts_left", r1)

    def test_lock_after_max_attempts(self):
        otp.send_otp("9876543210")
        last = None
        for _ in range(10):
            last = otp.verify_otp("9876543210", "111111")
            if last["status"] == "locked":
                break
        self.assertEqual(last["status"], "locked")

    def test_expired_code(self):
        otp.send_otp("9876543210")
        # Force expiry without waiting.
        key = "9876543210"
        otp._store[key].expires_at = 0
        res = otp.verify_otp(key, "123456")
        self.assertEqual(res["status"], "expired")

    def test_verify_without_send(self):
        self.assertEqual(otp.verify_otp("9000000000", "123456")["status"], "no_otp")


class SessionTests(unittest.TestCase):
    def test_get_or_create_and_persist(self):
        store = SessionStore()
        s1 = store.get_or_create(None)
        s2 = store.get_or_create(s1.id)
        self.assertIs(s1, s2)

    def test_reset_clears_state(self):
        store = SessionStore()
        s = store.get_or_create(None)
        s.authorized_client_id = "CL-1001"
        s.messages.append({"role": "user", "content": "hi"})
        fresh = store.reset(s.id)
        self.assertIsNone(fresh.authorized_client_id)
        self.assertEqual(fresh.messages, [])

    def test_is_authenticated(self):
        store = SessionStore()
        s = store.get_or_create(None)
        self.assertFalse(s.is_authenticated)
        s.verified_phone = "9876543210"
        self.assertTrue(s.is_authenticated)


if __name__ == "__main__":
    unittest.main()
