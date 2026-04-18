"""
Ingestion Worker — Dapr pub/sub subscriber.

Subscribes to the "entity-graph" topic on the "entity-events" Dapr component.
For each transform result event received:
  1. Validate the event envelope against the EntityEvent schema.
  2. Bulk-upsert all output entities to OpenSearch (deterministic doc IDs).
  3. Merge input + output nodes and relationships to Neo4j.

The worker never calls upstream services and has no external-facing endpoints
beyond the Dapr subscription callback. All network access is outbound-only,
restricted by NetworkPolicy to opensearch:9200 and neo4j:7687.

Event envelope (published by Transform Hub)
───────────────────────────────────────────
{
  "schema_version": "1.0",
  "transform_name": "DomainToIP",
  "input_entity": {
    "type": "maltego.Domain",
    "value": "example.com",
    "fields": {}
  },
  "output_entities": [
    {"type": "maltego.IPv4Address", "value": "1.2.3.4", "fields": {}}
  ],
  "client_id": "maltego-desktop",
  "request_id": "abc123",
  "timestamp": "2024-01-01T00:00:00Z"
}
"""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, ValidationError

from .config import settings
from .writers.neo4j_writer import Neo4jWriter
from .writers.opensearch_writer import OpenSearchWriter

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("ingestion-worker")

# ── State ─────────────────────────────────────────────────────────────────────

_os_writer: OpenSearchWriter | None = None
_neo4j_writer: Neo4jWriter | None = None
_semaphore: asyncio.Semaphore | None = None


# ── Pydantic event schema ─────────────────────────────────────────────────────

class EntityPayload(BaseModel):
    type: str
    value: str
    fields: dict[str, Any] = Field(default_factory=dict)


class EntityEvent(BaseModel):
    schema_version: str = "1.0"
    transform_name: str
    input_entity: EntityPayload
    output_entities: list[EntityPayload]
    client_id: str = ""
    request_id: str = ""
    timestamp: str = ""


# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    global _os_writer, _neo4j_writer, _semaphore

    _semaphore = asyncio.Semaphore(settings.max_concurrent_events)

    if settings.enable_opensearch:
        _os_writer = OpenSearchWriter(
            host=settings.opensearch_host,
            port=settings.opensearch_port,
            username=settings.opensearch_username,
            password=settings.opensearch_password,
            use_tls=settings.opensearch_use_tls,
        )
        logger.info("OpenSearch writer initialised: %s:%d", settings.opensearch_host, settings.opensearch_port)

    if settings.enable_neo4j:
        _neo4j_writer = Neo4jWriter(
            uri=settings.neo4j_uri,
            username=settings.neo4j_username,
            password=settings.neo4j_password,
        )
        try:
            await _neo4j_writer.verify_connectivity()
            await _neo4j_writer.ensure_constraints()
        except Exception as exc:
            logger.warning("Neo4j not reachable at startup: %s — will retry on first event", exc)

    yield

    # Shutdown
    if _os_writer:
        await _os_writer.close()
    if _neo4j_writer:
        await _neo4j_writer.close()


# ── FastAPI app ───────────────────────────────────────────────────────────────

app = FastAPI(
    title="Ingestion Worker",
    version="1.0.0",
    lifespan=lifespan,
    docs_url=None,       # no Swagger UI — internal service
    redoc_url=None,
)


# ── Dapr subscription registration ───────────────────────────────────────────

@app.get("/dapr/subscribe")
async def dapr_subscribe():
    """Tell Dapr which topics this app subscribes to."""
    return [
        {
            "pubsubname": settings.pubsub_name,
            "topic": settings.topic_name,
            "route": "/ingest",
            "deadLetterTopic": f"{settings.topic_name}-dlq",
            "metadata": {
                "maxDeliveryAttempts": "5",
            },
        }
    ]


# ── Ingestion endpoint ────────────────────────────────────────────────────────

@app.post("/ingest", status_code=status.HTTP_200_OK)
async def ingest_entity_event(request: Request) -> JSONResponse:
    """
    Dapr pub/sub callback.
    Dapr wraps the published payload in a CloudEvent envelope:
    {
      "data": { ...entity event... },
      "datacontenttype": "application/json",
      ...CloudEvent fields...
    }
    """
    body = await request.json()

    # Unwrap CloudEvent
    event_data = body.get("data", body)

    try:
        event = EntityEvent.model_validate(event_data)
    except ValidationError as exc:
        logger.warning("Malformed entity event, sending to DLQ: %s", exc)
        # Return 200 so Dapr doesn't retry indefinitely; it will route to DLQ
        return JSONResponse({"status": "DROP", "reason": str(exc)})

    async with _semaphore:
        await _process_event(event)

    return JSONResponse({"status": "SUCCESS"})


async def _process_event(event: EntityEvent) -> None:
    """Write event to OpenSearch and Neo4j, with independent failure handling."""
    sources = [event.transform_name]
    entities_as_dicts = [
        {
            "type": e.type,
            "value": e.value,
            "fields": e.fields,
            "sources": sources,
        }
        for e in event.output_entities
    ]

    # ── OpenSearch ────────────────────────────────────────────────────────────
    if _os_writer and settings.enable_opensearch:
        try:
            await _os_writer.bulk_upsert(
                entities=entities_as_dicts,
                transform_name=event.transform_name,
                client_id=event.client_id,
            )
        except Exception as exc:
            logger.error("OpenSearch write failed for event %s: %s", event.request_id, exc)
            # Continue — Neo4j write is independent

    # ── Neo4j ─────────────────────────────────────────────────────────────────
    if _neo4j_writer and settings.enable_neo4j:
        try:
            await _neo4j_writer.ingest_event(
                transform_name=event.transform_name,
                input_entity=event.input_entity.model_dump(),
                output_entities=[e.model_dump() for e in event.output_entities],
                client_id=event.client_id,
            )
        except Exception as exc:
            logger.error("Neo4j write failed for event %s: %s", event.request_id, exc)


# ── Health endpoints (required by K8s probes) ─────────────────────────────────

@app.get("/health/live")
async def liveness() -> dict:
    return {"status": "ok"}


@app.get("/health/ready")
async def readiness() -> dict:
    checks: dict[str, str] = {}

    if _os_writer and settings.enable_opensearch:
        try:
            resp = await _os_writer._client.get("/_cluster/health")
            checks["opensearch"] = "ok" if resp.status_code == 200 else "degraded"
        except Exception:
            checks["opensearch"] = "unreachable"

    if _neo4j_writer and settings.enable_neo4j:
        try:
            await _neo4j_writer.verify_connectivity()
            checks["neo4j"] = "ok"
        except Exception:
            checks["neo4j"] = "unreachable"

    degraded = any(v != "ok" for v in checks.values())
    return JSONResponse(
        content={"status": "degraded" if degraded else "ok", "checks": checks},
        status_code=207 if degraded else 200,
    )
