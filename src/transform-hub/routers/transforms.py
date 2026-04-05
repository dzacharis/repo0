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
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from ..auth import TokenClaims, verify_token
from ..models.maltego import TransformRequest, TransformResponse
from ..transforms import all_transforms, get_transform

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v2/transforms", tags=["Transforms"])


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
    _claims: TokenClaims = Depends(verify_token),
) -> Response:
    transform_cls = get_transform(transform_name)
    if transform_cls is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Transform '{transform_name}' not found",
        )

    content_type = request.headers.get("content-type", "application/xml").lower()
    body = await request.body()

    # ── Parse request ─────────────────────────────────────────────────────────
    try:
        if "json" in content_type:
            import json
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
                content=str(error_resp.to_dict()),
                media_type="application/json",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        return Response(
            content=error_resp.to_xml(),
            media_type="application/xml",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    # ── Serialise response ────────────────────────────────────────────────────
    if use_json:
        import json
        return Response(content=json.dumps(result.to_dict()), media_type="application/json")

    return Response(content=result.to_xml(), media_type="application/xml")
