import base64
import unittest

from app.security import credentials_match, is_cross_site, is_json, parse_basic_auth


class BasicAuthTests(unittest.TestCase):
    def _header(self, user, password):
        return "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()

    def test_parses_valid_header(self):
        self.assertEqual(parse_basic_auth(self._header("alice", "secret")), ("alice", "secret"))

    def test_rejects_missing_header(self):
        self.assertIsNone(parse_basic_auth(None))

    def test_rejects_non_basic_scheme(self):
        self.assertIsNone(parse_basic_auth("Bearer abcdef"))

    def test_rejects_garbage_base64(self):
        self.assertIsNone(parse_basic_auth("Basic not-base64!!"))

    def test_matches_correct_credentials(self):
        self.assertTrue(credentials_match(("alice", "secret"), "alice", "secret"))

    def test_rejects_wrong_password(self):
        self.assertFalse(credentials_match(("alice", "wrong"), "alice", "secret"))

    def test_rejects_none_given(self):
        self.assertFalse(credentials_match(None, "alice", "secret"))


class CrossSiteTests(unittest.TestCase):
    def test_same_origin_is_not_cross_site(self):
        self.assertFalse(is_cross_site("https://app.example.com", "app.example.com"))

    def test_different_origin_is_cross_site(self):
        self.assertTrue(is_cross_site("https://evil.example.com", "app.example.com"))

    def test_allowed_origin_override(self):
        self.assertFalse(is_cross_site("https://other.example.com", "app.example.com",
                                       allowed={"https://other.example.com"}))

    def test_sec_fetch_site_fallback_cross_site(self):
        self.assertTrue(is_cross_site(None, "app.example.com", sec_fetch_site="cross-site"))

    def test_sec_fetch_site_fallback_same_origin(self):
        self.assertFalse(is_cross_site(None, "app.example.com", sec_fetch_site="same-origin"))

    def test_no_signal_defaults_to_not_blocked(self):
        # Old browsers without Origin or Sec-Fetch-Site: don't lock legitimate users out.
        self.assertFalse(is_cross_site(None, "app.example.com"))


class ContentTypeTests(unittest.TestCase):
    def test_json_accepted(self):
        self.assertTrue(is_json("application/json"))

    def test_json_with_charset_accepted(self):
        self.assertTrue(is_json("application/json; charset=utf-8"))

    def test_form_encoded_rejected(self):
        self.assertFalse(is_json("text/plain"))

    def test_missing_rejected(self):
        self.assertFalse(is_json(None))


if __name__ == "__main__":
    unittest.main()
