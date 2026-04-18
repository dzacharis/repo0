"""
JWT bearer-token validation against Keycloak.

On first request the JWKS endpoint is fetched and cached.
The cache is refreshed automatically on key-not-found errors
(handles Keycloak key rotation without restart).
"""

from __future__ import annotations

import logging
import time
from functools import lru_cache
from typing import Any

import httpx
from cachetools import TTLCache
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import ExpiredSignatureError, JWTError, jwk, jwt
from jose.utils import base64url_decode

from .config import Settings, get_settings

logger = logging.getLogger(__name__)

# Cache JWKS for 10 minutes; evict single keys on rotation
_jwks_cache: TTLCache = TTLCache(maxsize=4, ttl=600)

bearer_scheme = HTTPBearer(auto_error=True)


def _fetch_jwks(settings: Settings) -> dict[str, Any]:
    """Fetch the public-key set from Keycloak's JWKS endpoint."""
    jwks_uri = (
        f"{settings.keycloak_url}/realms/{settings.keycloak_realm}"
        "/.well-known/openid-configuration"
    )
    try:
        resp = httpx.get(jwks_uri, timeout=10)
        resp.raise_for_status()
        oidc_config = resp.json()
        jwks_resp = httpx.get(oidc_config["jwks_uri"], timeout=10)
        jwks_resp.raise_for_status()
        return jwks_resp.json()
    except Exception as exc:
        logger.error("Failed to fetch JWKS from Keycloak: %s", exc)
        raise


def _get_public_key(kid: str, settings: Settings) -> Any:
    """Return a jose-compatible public key for the given kid."""
    if "jwks" not in _jwks_cache:
        _jwks_cache["jwks"] = _fetch_jwks(settings)

    for key_data in _jwks_cache["jwks"].get("keys", []):
        if key_data.get("kid") == kid:
            return jwk.construct(key_data)

    # kid not found — refresh once (key rotation)
    _jwks_cache["jwks"] = _fetch_jwks(settings)
    for key_data in _jwks_cache["jwks"].get("keys", []):
        if key_data.get("kid") == kid:
            return jwk.construct(key_data)

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Unknown signing key",
    )


def verify_token(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    """
    FastAPI dependency — validates the Bearer token and returns the claims.

    Raises HTTP 401 for any validation failure so callers never need to
    handle raw JWT exceptions.
    """
    token = credentials.credentials

    # Decode header to get kid without full verification first
    try:
        header = jwt.get_unverified_header(token)
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token header: {exc}",
        ) from exc

    public_key = _get_public_key(header.get("kid", ""), settings)

    try:
        claims = jwt.decode(
            token,
            public_key,
            algorithms=["RS256", "ES256"],
            audience=settings.keycloak_client_id,
            issuer=f"{settings.keycloak_url}/realms/{settings.keycloak_realm}",
            options={"verify_exp": True, "verify_aud": True},
        )
    except ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
        )
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Token validation failed: {exc}",
        )

    # Check required scope
    scopes = claims.get("scope", "").split()
    if settings.required_scope and settings.required_scope not in scopes:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Missing required scope: {settings.required_scope}",
        )

    return claims


# Type alias for use in route signatures
TokenClaims = dict[str, Any]
