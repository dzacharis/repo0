"""
Transform execution router.

Endpoints
---------
POST /api/v2/transforms/{name}
    Execute a transform.
    Accepts: application/xml  (classic Maltego TRX envelope)
             application/json (modern REST payload)
    Returns: same Content-Type as request, or application/xml by default.

GET  /api/v2/transforms
    List all registered transforms (JSON).

After each successful execution the router publishes an entity-graph event to
the Dapr "entity-events" pub/sub component.  The ingestion worker (ingestion
namespace) subscribes to this topic and writes results to OpenSearch and Neo4j.
The Transform Hub itself has no knowledge of — and no network path to — either
datastore.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from ..auth import TokenClaims, verify_token
from ..models.maltego import TransformRequest, TransformResponse
from ..transforms import all_transforms, get_transform

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v2/transforms", tags=["Transforms"])

# ── Dapr pub/sub helper ───────────────────────────────────────────────────────
_DAPR_PORT = 3500
_PUBSUB_NAME = "entity-events"
_TOPIC_NAME = "entity-graph"


async def _publish_entity_event(
    transform_name: str,
    trx_request: TransformRequest,
    result: TransformResponse,
    claims: TokenClaims,
    request_id: str,
) -> None:
    """
    Publish the transform result to the entity-graph topic.
    Failures are logged but never surface to the caller — the transform
    response is already serialised and returning to the Maltego client.
    """
    input_ent = trx_request.entities[0]
    payload = {
        "schema_version": "1.0",
        "transform_name": transform_name,
        "input_entity": {
            "type": input_ent.type,
            "value": input_ent.value,
            "fields": {f.name: f.value for f in input_ent.fields},
        },
        "output_entities": [
            {
                "type": e.type,
                "value": e.value,
                "fields": {f.name: f.value for f in e.fields},
            }
            for e in result.entities
        ],
        "client_id": claims.sub if claims else "",
        "request_id": request_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.post(
                f"http://localhost:{_DAPR_PORT}/v1.0/publish/{_PUBSUB_NAME}/{_TOPIC_NAME}",
                content=json.dumps(payload),
                headers={"Content-Type": "application/json"},
            )
            if resp.status_code not in (200, 204):
                logger.warning(
                    "Entity event publish failed for %s: %s", transform_name, resp.text[:200]
                )
    except Exception as exc:
        logger.warning("Could not publish entity event for %s: %s", transform_name, exc)


@router.get("", summary="List all registered transforms")
async def list_transforms(
    _claims: TokenClaims = Depends(verify_token),
) -> dict[str, Any]:
    return {
        "transforms": [
            cls.meta.to_dict()
            for cls in all_transforms().values()
        ]
    }


@router.post("/{transform_name}", summary="Execute a transform")
async def execute_transform(
    transform_name: str,
    request: Request,
    claims: TokenClaims = Depends(verify_token),
) -> Response:
    transform_cls = get_transform(transform_name)
    if transform_cls is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Transform '{transform_name}' not found",
        )

    content_type = request.headers.get("content-type", "application/xml").lower()
    request_id = request.headers.get("x-request-id", "")
    body = await request.body()

    # ── Parse request ─────────────────────────────────────────────────────────
    try:
        if "json" in content_type:
            trx_request = TransformRequest.from_json(json.loads(body))
            use_json = True
        else:
            trx_request = TransformRequest.from_xml(body)
            use_json = False
    except Exception as exc:
        logger.warning("Failed to parse transform request: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Could not parse request body: {exc}",
        ) from exc

    # ── Execute ───────────────────────────────────────────────────────────────
    try:
        instance = transform_cls()
        result: TransformResponse = instance.execute(trx_request)
    except Exception as exc:
        logger.exception("Transform '%s' raised an unhandled exception", transform_name)
        error_resp = TransformResponse().error(
            f"Internal transform error: {exc}", fatal=True
        )
        if use_json:
            return Response(
                content=json.dumps(error_resp.to_dict()),
                media_type="application/json",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        return Response(
            content=error_resp.to_xml(),
            media_type="application/xml",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    # ── Publish entity event (fire-and-forget, never blocks response) ─────────
    if result.entities and trx_request.entities:
        asyncio.create_task(
            _publish_entity_event(
                transform_name=transform_name,
                trx_request=trx_request,
                result=result,
                claims=claims,
                request_id=request_id,
            )
        )

    # ── Serialise response ────────────────────────────────────────────────────
    if use_json:
        return Response(content=json.dumps(result.to_dict()), media_type="application/json")

    return Response(content=result.to_xml(), media_type="application/xml")
