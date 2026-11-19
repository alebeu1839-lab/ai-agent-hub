"""Regression tests for hub.redact.

Fake secrets are built programmatically so the file itself contains no
realistic-looking secret literals.
"""
from __future__ import annotations

import unittest

from hub.redact import _PATTERNS, redact

R = "[REDACTED]"

PEM = (
    "-----BEGIN RSA PRIVATE KEY-----\n"
    + "MIIB" + "A" * 60 + "\n" + "B" * 64 + "\n"
    + "-----END RSA PRIVATE KEY-----"
)
JWT = "eyJ" + "a" * 20 + "." + "b" * 20 + "." + "c" * 20
GH_TOKEN = "ghp_" + "A1" * 18
GH_PAT = "github_pat_" + "11ABC" + "_x" * 20
ANTHROPIC = "sk-ant-" + "api03-" + "Z" * 30
OPENAI = "sk-proj-" + "Q" * 40
AWS = "AKIA" + "ABCDEFGH12345678"
GOOGLE = "AIza" + "S" * 35
STRIPE_LIVE = "sk_live_" + "9" * 24
STRIPE_RESTRICTED = "rk_test_" + "8" * 24
NPM = "npm_" + "n" * 36
SLACK = "xoxb-" + "1234-5678-" + "abcdef" * 3

# (name, secret, the exact substring expected to be replaced)
FULL_MATCH_CASES = [
    ("pem_private_key", PEM),
    ("jwt", JWT),
    ("github_token", GH_TOKEN),
    ("github_pat", GH_PAT),
    ("anthropic_key", ANTHROPIC),
    ("openai_key", OPENAI),
    ("aws_access_key_id", AWS),
    ("google_api_key", GOOGLE),
    ("stripe_live_key", STRIPE_LIVE),
    ("stripe_restricted_key", STRIPE_RESTRICTED),
    ("npm_token", NPM),
    ("slack_token", SLACK),
]


class PatternCoverageTest(unittest.TestCase):
    def test_pattern_count(self):
        # If a pattern is added/removed, update the positive tests below.
        self.assertEqual(len(_PATTERNS), 14)


class PositiveRedactionTest(unittest.TestCase):
    def test_full_match_secrets(self):
        for name, secret in FULL_MATCH_CASES:
            with self.subTest(name):
                text = f"before {secret} after"
                out = redact(text)
                self.assertEqual(out, f"before {R} after")
                self.assertNotIn(secret, out)

    def test_authorization_header_keeps_prefix(self):
        token = "t0ken" + "x" * 20
        for scheme in ("Bearer", "token", "Basic"):
            with self.subTest(scheme):
                out = redact(f"Authorization: {scheme} {token}\nnext")
                self.assertEqual(out, f"Authorization: {scheme} {R}\nnext")
                self.assertNotIn(token, out)

    def test_key_value_assignment_keeps_prefix(self):
        value = "hunter" + "2" * 10
        cases = [
            (f"api_key={value}", f"api_key={R}"),
            (f"API-KEY: {value}", f"API-KEY: {R}"),
            (f"password: {value}", f"password: {R}"),
            (f"passwd={value}", f"passwd={R}"),
            (f"secret = {value}", f"secret = {R}"),
            # Known cosmetic quirk: the opening quote of a quoted value is
            # consumed (it sits outside the capture group). Secret is still gone.
            (f'"token": "{value}"', f'"token": {R}"'),
        ]
        for text, expected in cases:
            with self.subTest(text):
                out = redact(text)
                self.assertEqual(out, expected)
                self.assertNotIn(value, out)

    def test_url_embedded_credentials(self):
        pw = "pa55" + "w" * 10
        out = redact(f"clone https://alice:{pw}@git.example.com/repo.git now")
        self.assertEqual(out, f"clone {R}git.example.com/repo.git now")
        self.assertNotIn(pw, out)

    def test_multiple_secrets_in_one_text(self):
        out = redact(f"a={GH_TOKEN} b={AWS} c={NPM}")
        for s in (GH_TOKEN, AWS, NPM):
            self.assertNotIn(s, out)
        self.assertEqual(out.count(R), 3)


class NegativeRedactionTest(unittest.TestCase):
    def test_ordinary_text_unchanged(self):
        samples = [
            "The quick brown fox jumps over the lazy dog.",
            "The password field is required.",
            "Please rotate your token regularly.",
            "sk-short",
            "ghp_short",
            "AKIA lowercase akiaabcdefgh12345678",
            "https://example.com/path?q=1",
            "ssh://git@github.com/org/repo.git",
            "contact user@example.com for help",
            "commit 3f2a9c1e8b7d6a5f4e3d2c1b0a9f8e7d6c5b4a39",
            "token = None",
            "password: abc",
            "eyJ.short.jwt",
            "Authorization header missing",
            "-----BEGIN PUBLIC KEY-----\nAAAA\n-----END PUBLIC KEY-----",
            "日本語のテキストもそのまま",
        ]
        for text in samples:
            with self.subTest(text):
                self.assertEqual(redact(text), text)

    def test_empty_and_none(self):
        self.assertEqual(redact(""), "")
        self.assertIsNone(redact(None))  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
