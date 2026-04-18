"""
Discovery / manifest endpoints — the iTDS replacement.

Maltego clients call GET /api/v2/manifest to learn which transforms are
available and how to invoke them, without having to register with the
Maltego iTDS cloud service.

Endpoints
---------
GET /api/v2/manifest
    Full hub manifest: transforms + auth config.
    Used to import the transform set into the Maltego client (Settings →
    Advanced → Transform Servers → Add).

GET /health
    Liveness / readiness probe.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ..auth import TokenClaims, verify_token
from ..config import Settings, get_settings
from ..transforms import all_transforms

router = APIRouter(tags=["Discovery"])


@router.get("/api/v2/manifest", summary="Hub manifest (iTDS replacement)")
async def manifest(
    settings: Settings = Depends(get_settings),
    _claims: TokenClaims = Depends(verify_token),
) -> dict:
    """
    Returns the transform hub manifest in a format compatible with the
    Maltego custom transform server configuration.

    Import in Maltego:
        Settings → Advanced → Transform Servers → Add Server
        URL: https://api.example.com/transforms
        Auth: OAuth2 Bearer  (Keycloak token URL, client_id, client_secret)
    """
    return {
        "version": settings.hub_version,
        "name": settings.hub_name,
        "url": settings.hub_url,
        "authentication": {
            "type": "oauth2_client_credentials",
            "tokenUrl": (
                f"{settings.keycloak_url}/realms/{settings.keycloak_realm}"
                "/protocol/openid-connect/token"
            ),
            "clientId": settings.keycloak_client_id,
            "scopes": [settings.required_scope],
        },
        "transforms": [
            {
                **cls.meta.to_dict(),
                "endpoint": f"{settings.hub_url}/api/v2/transforms/{cls.name}",
            }
            for cls in all_transforms().values()
        ],
    }


@router.get("/health", include_in_schema=False)
async def health() -> dict:
    return {"status": "ok"}
