"""
Transform Hub — entry point.

Simulates the Maltego on-prem ID server with iTDS removed.
Clients authenticate to Keycloak via OAuth2 client_credentials,
receive a bearer token, and call transform endpoints directly.

Architecture:
    Maltego Client
        │  (1) POST /api/v1/clients/token  →  bearer token from Keycloak
        │  (2) GET  /api/v2/manifest       →  discover available transforms
        │  (3) POST /api/v2/transforms/{name}  with Authorization: Bearer <token>
        ▼
    Transform Hub  (this service)
        │  validates JWT against Keycloak JWKS
        │  routes to the correct BaseTransform subclass
        │  returns XML or JSON Maltego response
        ▼
    Maltego-compatible response
"""

import logging

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from config import get_settings
from routers import clients, manifest, transforms

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
logger = logging.getLogger(__name__)

settings = get_settings()

app = FastAPI(
    title="Maltego Transform Hub",
    description=(
        "Open-source Maltego transform server with Keycloak-based "
        "authentication — no iTDS, no Maltego cloud dependency."
    ),
    version=settings.hub_version,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

# CORS — allow the Maltego desktop client and any browser tooling
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(manifest.router)
app.include_router(transforms.router)
app.include_router(clients.router)


@app.exception_handler(Exception)
async def global_exception_handler(request, exc):  # noqa: ANN001
    logger.exception("Unhandled exception: %s", exc)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level,
        reload=False,
    )
