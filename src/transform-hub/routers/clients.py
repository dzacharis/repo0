"""
Client registration router.

Allows a new Maltego operator to self-register and receive a Keycloak
client_id / client_secret pair they can plug directly into the Maltego
"Transform Server" settings.

Endpoints
---------
POST /api/v1/clients/register
    Create a new confidential Keycloak client scoped to transforms:execute.
    Returns: { client_id, client_secret, token_url }

POST /api/v1/clients/token  (proxy convenience)
    Exchange client_credentials for a bearer token without leaving this service.
    Returns: { access_token, expires_in, token_type }

DELETE /api/v1/clients/{client_id}
    Revoke / delete a client. Requires admin scope.
"""

from __future__ import annotations

import logging
import secrets
import string
from typing import Any

import httpx
from fastapi import APIRouter, Body, Depends, HTTPException, status
from pydantic import BaseModel

from ..auth import TokenClaims, verify_token
from ..config import Settings, get_settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/clients", tags=["Client Registration"])

ADMIN_SCOPE = "transforms:admin"


# ── Request / response models ─────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    client_name: str
    description: str = ""


class RegisterResponse(BaseModel):
    client_id: str
    client_secret: str
    token_url: str
    instructions: str


class TokenRequest(BaseModel):
    client_id: str
    client_secret: str


# ── Helpers ───────────────────────────────────────────────────────────────────

def _admin_token(settings: Settings) -> str:
    """Obtain a short-lived admin token from Keycloak to manage clients."""
    resp = httpx.post(
        f"{settings.keycloak_url}/realms/master/protocol/openid-connect/token",
        data={
            "grant_type": "client_credentials",
            "client_id": "transform-hub-admin",
            "client_secret": settings.keycloak_admin_client_secret,
        },
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def _keycloak_admin_url(settings: Settings) -> str:
    return f"{settings.keycloak_url}/admin/realms/{settings.keycloak_realm}"


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post(
    "/register",
    response_model=RegisterResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new Maltego client",
)
async def register_client(
    body: RegisterRequest = Body(...),
    claims: TokenClaims = Depends(verify_token),
    settings: Settings = Depends(get_settings),
) -> RegisterResponse:
    """
    Creates a new confidential Keycloak client and returns credentials.
    The returned client_id and client_secret are used in Maltego's
    Transform Server settings to obtain bearer tokens automatically.

    Requires the calling token to have the `transforms:admin` scope
    (i.e. only admins can create new client registrations).
    """
    scopes = claims.get("scope", "").split()
    if ADMIN_SCOPE not in scopes:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Missing required scope: {ADMIN_SCOPE}",
        )

    # Generate a strong random secret
    alphabet = string.ascii_letters + string.digits
    client_secret = "".join(secrets.choice(alphabet) for _ in range(48))
    client_id = f"maltego-{body.client_name.lower().replace(' ', '-')}-{secrets.token_hex(4)}"

    try:
        admin_token = _admin_token(settings)
    except Exception as exc:
        logger.error("Failed to obtain Keycloak admin token: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not contact Keycloak admin API",
        ) from exc

    client_payload: dict[str, Any] = {
        "clientId": client_id,
        "name": body.client_name,
        "description": body.description,
        "enabled": True,
        "protocol": "openid-connect",
        "clientAuthenticatorType": "client-secret",
        "secret": client_secret,
        "publicClient": False,
        "serviceAccountsEnabled": True,  # client_credentials grant
        "standardFlowEnabled": False,
        "implicitFlowEnabled": False,
        "directAccessGrantsEnabled": False,
        "defaultClientScopes": ["transforms:execute"],
        "optionalClientScopes": [],
    }

    resp = httpx.post(
        f"{_keycloak_admin_url(settings)}/clients",
        json=client_payload,
        headers={"Authorization": f"Bearer {admin_token}"},
        timeout=10,
    )
    if resp.status_code == 409:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Client '{client_id}' already exists",
        )
    if not resp.is_success:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Keycloak returned {resp.status_code}: {resp.text}",
        )

    token_url = (
        f"{settings.keycloak_url}/realms/{settings.keycloak_realm}"
        "/protocol/openid-connect/token"
    )
    return RegisterResponse(
        client_id=client_id,
        client_secret=client_secret,
        token_url=token_url,
        instructions=(
            "In Maltego: Settings → Advanced → Transform Servers → Add Server. "
            f"Set URL to {settings.hub_url}, Auth to OAuth2 Client Credentials, "
            f"token URL to {token_url}, client_id to {client_id}."
        ),
    )


@router.post("/token", summary="Exchange client credentials for a bearer token")
async def get_token(
    body: TokenRequest = Body(...),
    settings: Settings = Depends(get_settings),
) -> dict:
    """
    Convenience proxy — exchanges a client_id/client_secret pair for a
    Keycloak access token. Maltego clients can call this endpoint directly
    instead of constructing the Keycloak token request themselves.
    """
    resp = httpx.post(
        f"{settings.keycloak_url}/realms/{settings.keycloak_realm}"
        "/protocol/openid-connect/token",
        data={
            "grant_type": "client_credentials",
            "client_id": body.client_id,
            "client_secret": body.client_secret,
            "scope": settings.required_scope,
        },
        timeout=10,
    )
    if not resp.is_success:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid client credentials or client not found",
        )
    data = resp.json()
    return {
        "access_token": data["access_token"],
        "expires_in": data.get("expires_in", 300),
        "token_type": data.get("token_type", "Bearer"),
    }


@router.delete("/{client_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_client(
    client_id: str,
    claims: TokenClaims = Depends(verify_token),
    settings: Settings = Depends(get_settings),
) -> None:
    """Revoke a registered client (admin only)."""
    scopes = claims.get("scope", "").split()
    if ADMIN_SCOPE not in scopes:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail=f"Missing scope: {ADMIN_SCOPE}")
    try:
        admin_token = _admin_token(settings)
        # Find the internal UUID for this clientId
        search = httpx.get(
            f"{_keycloak_admin_url(settings)}/clients",
            params={"clientId": client_id},
            headers={"Authorization": f"Bearer {admin_token}"},
            timeout=10,
        )
        search.raise_for_status()
        results = search.json()
        if not results:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                                detail=f"Client '{client_id}' not found")
        internal_id = results[0]["id"]
        del_resp = httpx.delete(
            f"{_keycloak_admin_url(settings)}/clients/{internal_id}",
            headers={"Authorization": f"Bearer {admin_token}"},
            timeout=10,
        )
        del_resp.raise_for_status()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY,
                            detail=str(exc)) from exc
