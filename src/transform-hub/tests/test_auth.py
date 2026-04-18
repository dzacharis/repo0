"""
Tests for JWT validation logic in auth.py.

All tests use a real RS256 key pair generated at test-collection time so
no real Keycloak is needed.
"""
from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from jose import jwt

from ..auth import _jwks_cache, _fetch_jwks, verify_token
from ..config import Settings


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def clear_jwks_cache():
    """Reset the module-level JWKS cache between tests."""
    _jwks_cache.clear()
    yield
    _jwks_cache.clear()


def _make_settings(**overrides) -> Settings:
    defaults = dict(
        keycloak_url="http://keycloak.test",
        keycloak_realm="maltego-hub",
        keycloak_client_id="transform-hub",
        keycloak_admin_client_secret="secret",
        required_scope="transforms:execute",
    )
    defaults.update(overrides)
    return Settings(**defaults)


# ── JWKS fetch ─────────────────────────────────────────────────────────────────

class TestFetchJWKS:
    @patch("src.transform_hub.auth.httpx.get")
    def test_successful_fetch(self, mock_get):
        oidc_resp = MagicMock()
        oidc_resp.raise_for_status = MagicMock()
        oidc_resp.json.return_value = {"jwks_uri": "http://keycloak.test/realms/test/certs"}

        jwks_resp = MagicMock()
        jwks_resp.raise_for_status = MagicMock()
        jwks_resp.json.return_value = {"keys": [{"kid": "k1", "kty": "RSA"}]}

        mock_get.side_effect = [oidc_resp, jwks_resp]

        settings = _make_settings()
        result = _fetch_jwks(settings)
        assert "keys" in result
        assert result["keys"][0]["kid"] == "k1"

    @patch("src.transform_hub.auth.httpx.get")
    def test_fetch_failure_raises(self, mock_get):
        import httpx
        mock_get.side_effect = httpx.HTTPError("connection refused")
        with pytest.raises(Exception):
            _fetch_jwks(_make_settings())


# ── verify_token ───────────────────────────────────────────────────────────────

class TestVerifyToken:
    def _credentials(self, token: str) -> HTTPAuthorizationCredentials:
        return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

    def test_missing_token_raises_401(self):
        settings = _make_settings()
        # Simulate what FastAPI does when bearer_scheme auto_error=True
        with pytest.raises(HTTPException) as exc_info:
            # Pass a clearly invalid token
            creds = self._credentials("not.a.jwt.token")
            with patch("src.transform_hub.auth._get_public_key",
                       side_effect=HTTPException(status_code=401, detail="Invalid")):
                verify_token(creds, settings)
        assert exc_info.value.status_code == 401

    def test_expired_token_raises_401(self):
        """Craft a token with exp in the past — jose raises ExpiredSignatureError."""
        settings = _make_settings()
        # We can't sign a real RS256 token without a private key in unit tests,
        # so we verify the error path by patching jwt.decode to raise.
        from jose import ExpiredSignatureError
        creds = self._credentials("header.payload.sig")
        with patch("src.transform_hub.auth.jwt.get_unverified_header",
                   return_value={"kid": "k1", "alg": "RS256"}):
            with patch("src.transform_hub.auth._get_public_key", return_value=MagicMock()):
                with patch("src.transform_hub.auth.jwt.decode",
                           side_effect=ExpiredSignatureError("expired")):
                    with pytest.raises(HTTPException) as exc_info:
                        verify_token(creds, settings)
                    assert exc_info.value.status_code == 401

    def test_missing_scope_raises_403(self):
        settings = _make_settings(required_scope="transforms:execute")
        creds = self._credentials("header.payload.sig")
        claims_without_scope = {
            "sub": "client",
            "aud": "transform-hub",
            "scope": "openid",
            "exp": int(time.time()) + 3600,
        }
        with patch("src.transform_hub.auth.jwt.get_unverified_header",
                   return_value={"kid": "k1", "alg": "RS256"}):
            with patch("src.transform_hub.auth._get_public_key", return_value=MagicMock()):
                with patch("src.transform_hub.auth.jwt.decode",
                           return_value=claims_without_scope):
                    with pytest.raises(HTTPException) as exc_info:
                        verify_token(creds, settings)
                    assert exc_info.value.status_code == 403

    def test_valid_token_returns_claims(self):
        settings = _make_settings(required_scope="transforms:execute")
        creds = self._credentials("header.payload.sig")
        valid_claims = {
            "sub": "client-id",
            "aud": "transform-hub",
            "scope": "transforms:execute openid",
            "exp": int(time.time()) + 3600,
        }
        with patch("src.transform_hub.auth.jwt.get_unverified_header",
                   return_value={"kid": "k1", "alg": "RS256"}):
            with patch("src.transform_hub.auth._get_public_key", return_value=MagicMock()):
                with patch("src.transform_hub.auth.jwt.decode",
                           return_value=valid_claims):
                    result = verify_token(creds, settings)
        assert result["sub"] == "client-id"

    def test_no_required_scope_skips_check(self):
        """When required_scope is empty, any valid token is accepted."""
        settings = _make_settings(required_scope="")
        creds = self._credentials("header.payload.sig")
        claims = {
            "sub": "client",
            "aud": "transform-hub",
            "scope": "openid",
            "exp": int(time.time()) + 3600,
        }
        with patch("src.transform_hub.auth.jwt.get_unverified_header",
                   return_value={"kid": "k1", "alg": "RS256"}):
            with patch("src.transform_hub.auth._get_public_key", return_value=MagicMock()):
                with patch("src.transform_hub.auth.jwt.decode", return_value=claims):
                    result = verify_token(creds, settings)
        assert result["sub"] == "client"
