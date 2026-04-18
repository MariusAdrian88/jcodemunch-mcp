"""Tests for redact.py — response-level secret redaction.

Covers findings F1 (pattern tightening), F2 (depth cap), F6 (_meta scan).
"""

from jcodemunch_mcp.redact import redact_dict, _redact_string, _shannon_entropy


# ── F1: pattern tightening ─────────────────────────────────────────────────

class TestBearerTokenPattern:
    """bearer_token is header-anchored; doesn't match identifiers."""

    def test_identifier_in_source_is_preserved(self):
        # `token ` followed by 20+ chars in code must NOT redact.
        source = "def refresh_token  session_identifier_for_handler():\n    pass"
        out, count = _redact_string(source)
        assert count == 0
        assert out == source

    def test_lowercase_token_word_boundary_preserved(self):
        source = "The token validates_against_our_service_boundary_checks_ok"
        out, count = _redact_string(source)
        assert count == 0

    def test_authorization_bearer_header_redacted(self):
        header = "Authorization: Bearer eyJabcdefghijklmnopqrst.u.v"
        out, count = _redact_string(header)
        assert count >= 1
        assert "[REDACTED:" in out

    def test_capital_bearer_standalone_redacted(self):
        line = "Bearer abcdefghijklmnopqrstuvwxyz12345"
        out, count = _redact_string(line)
        assert count >= 1
        assert "[REDACTED:bearer_token]" in out


class TestGenericApiKeyEntropy:
    """generic_api_key only redacts when entropy >= threshold."""

    def test_low_entropy_identifier_preserved(self):
        # `api_key: DEFAULT_CONFIG_IDENTIFIER_CONSTANT` — low entropy, identifier-shaped
        source = "api_key: DEFAULT_CONFIG_IDENTIFIER_CONSTANT_VALUE"
        out, count = _redact_string(source)
        assert count == 0
        assert out == source

    def test_high_entropy_secret_redacted(self):
        # Dense random 40+ char base62 value
        source = "api_key=aZ3x9Kp2Rt8QwE4uYi7Om6Ln5Vb0Cf1Dg2Hj3Kl4Mn"
        out, count = _redact_string(source)
        assert count >= 1
        assert "[REDACTED:generic_api_key]" in out


class TestShannonEntropy:
    def test_empty_string(self):
        assert _shannon_entropy("") == 0.0

    def test_single_char(self):
        assert _shannon_entropy("aaaaa") == 0.0

    def test_high_entropy_is_higher(self):
        low = _shannon_entropy("DEFAULT_CONFIG_IDENTIFIER_CONSTANT")
        high = _shannon_entropy("aZ3x9Kp2Rt8QwE4uYi7Om6Ln5Vb0Cf1Dg")
        assert high > low


# ── F2: depth cap redacts instead of leaking ──────────────────────────────

class TestDepthCap:
    def test_past_depth_cap_is_sentinel_not_raw(self):
        # Build a nested dict 25 levels deep with a secret at the leaf.
        secret = "-----BEGIN RSA PRIVATE KEY-----"
        leaf = {"key": secret}
        nested = leaf
        for _ in range(25):
            nested = {"x": nested}
        out, _ = redact_dict(nested)
        # Walk down: at some point we hit the sentinel. Verify the raw secret
        # never survives end-to-end.
        flat = repr(out)
        assert secret not in flat


# ── F6: _meta string fields get scanned ────────────────────────────────────

class TestMetaScanning:
    def test_meta_string_scanned_for_secrets(self):
        aws_key = "AKIAIOSFODNN7EXAMPLE"
        payload = {"_meta": {"hint": f"See {aws_key} for context"}}
        out, count = redact_dict(payload)
        assert count >= 1
        assert aws_key not in repr(out)
        assert "[REDACTED:aws_access_key]" in out["_meta"]["hint"]

    def test_meta_numeric_fields_passed_through(self):
        payload = {"_meta": {"timing_ms": 12.3, "tokens_saved": 4000}}
        out, _ = redact_dict(payload)
        assert out["_meta"]["timing_ms"] == 12.3
        assert out["_meta"]["tokens_saved"] == 4000

    def test_meta_nested_container_scanned(self):
        aws_key = "AKIAIOSFODNN7EXAMPLE"
        payload = {"_meta": {"errors": [f"failed with {aws_key}"]}}
        out, count = redact_dict(payload)
        assert count >= 1
        assert aws_key not in repr(out)
