"""
Shared fixtures for the Transform Hub test suite.
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from models.maltego import EntityField, MaltegoEntity, TransformLimits, TransformRequest


# ── Entity / request factories ─────────────────────────────────────────────────

def make_entity(entity_type: str = "maltego.Domain", value: str = "example.com",
                fields: dict[str, str] | None = None) -> MaltegoEntity:
    entity = MaltegoEntity(type=entity_type, value=value)
    for name, val in (fields or {}).items():
        entity.add_field(name, val)
    return entity


def make_request(entity: MaltegoEntity | None = None,
                 soft_limit: int = 12) -> TransformRequest:
    entity = entity or make_entity()
    return TransformRequest(
        entities=[entity],
        limits=TransformLimits(soft_limit=soft_limit, hard_limit=255),
    )


@pytest.fixture
def domain_entity():
    return make_entity("maltego.Domain", "example.com")


@pytest.fixture
def ip_entity():
    return make_entity("maltego.IPv4Address", "93.184.216.34")


@pytest.fixture
def url_entity():
    return make_entity("maltego.URL", "https://example.com/path")


@pytest.fixture
def domain_request(domain_entity):
    return make_request(domain_entity)


@pytest.fixture
def ip_request(ip_entity):
    return make_request(ip_entity)


# ── JWT / auth fixtures ────────────────────────────────────────────────────────

MOCK_TOKEN_CLAIMS = {
    "sub": "test-client",
    "iss": "http://keycloak.test/realms/maltego-hub",
    "aud": "transform-hub",
    "scope": "transforms:execute",
    "exp": 9999999999,
}

MOCK_JWKS = {
    "keys": [
        {
            "kid": "test-key-1",
            "kty": "RSA",
            "use": "sig",
            "n": "sIwr8HJMEbNGKgFMbYgk3bNJgNGQxMYyH-dummy-key",
            "e": "AQAB",
        }
    ]
}


@pytest.fixture
def mock_token_claims():
    return MOCK_TOKEN_CLAIMS.copy()


@pytest.fixture
def mock_valid_token(mock_token_claims):
    """Patch verify_token to return a valid TokenClaims without hitting Keycloak."""
    from auth import TokenClaims

    claims = TokenClaims(**mock_token_claims)
    with patch("routers.transforms.verify_token", return_value=claims):
        yield claims


# ── App client ─────────────────────────────────────────────────────────────────

@pytest.fixture
def app_client():
    """
    Synchronous TestClient with auth bypassed.
    Uses dependency_overrides so the whole router is exercised.
    """
    from auth import TokenClaims, verify_token
    from main import app

    claims = TokenClaims(**MOCK_TOKEN_CLAIMS)
    app.dependency_overrides[verify_token] = lambda: claims

    with TestClient(app) as client:
        yield client

    app.dependency_overrides.clear()
