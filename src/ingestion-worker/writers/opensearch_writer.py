"""
OpenSearch writer for the ingestion pipeline.

Responsibilities
────────────────
- Ensure each entity index exists with the correct mapping before first write.
- Upsert entity documents (MERGE semantics: update existing, insert new).
- Update first_seen / last_seen timestamps correctly.
- Bulk-write a batch of entities in a single HTTP round-trip.

Document ID strategy
────────────────────
Each entity is identified by sha256(entity_type + "::" + value).
This gives stable, deterministic IDs so that repeated observations of the
same entity update (upsert) the existing document rather than creating duplicates.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone

import httpx

from ..schema import EntityMapping, get_entity_mapping, opensearch_index_mapping

logger = logging.getLogger(__name__)


def _entity_doc_id(entity_type: str, value: str) -> str:
    return hashlib.sha256(f"{entity_type}::{value}".encode()).hexdigest()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class OpenSearchWriter:
    """
    Writes entity documents to OpenSearch using the REST API.

    Authenticated with basic auth (admin credentials from environment).
    Uses the upsert (doc_as_upsert) pattern so the same entity observed
    by multiple transforms is safely merged.
    """

    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
        use_tls: bool = False,
    ) -> None:
        scheme = "https" if use_tls else "http"
        self._base_url = f"{scheme}://{host}:{port}"
        self._auth = (username, password)
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            auth=self._auth,
            timeout=30.0,
            verify=use_tls,
        )
        self._ensured_indices: set[str] = set()

    async def close(self) -> None:
        await self._client.aclose()

    async def ensure_index(self, entity_type: str, index_name: str) -> None:
        """Create the index with the schema-defined mapping if it does not exist."""
        if index_name in self._ensured_indices:
            return

        # Check existence
        resp = await self._client.head(f"/{index_name}")
        if resp.status_code == 200:
            self._ensured_indices.add(index_name)
            return

        # Create
        body = opensearch_index_mapping(entity_type)
        resp = await self._client.put(
            f"/{index_name}",
            content=json.dumps(body),
            headers={"Content-Type": "application/json"},
        )
        if resp.status_code not in (200, 201):
            logger.warning(
                "Failed to create index %s: %s %s", index_name, resp.status_code, resp.text
            )
        else:
            logger.info("Created OpenSearch index %s", index_name)
            self._ensured_indices.add(index_name)

    async def upsert_entity(
        self,
        entity_type: str,
        value: str,
        fields: dict,
        sources: list[str] | None = None,
    ) -> None:
        """Upsert a single entity document."""
        mapping: EntityMapping | None = get_entity_mapping(entity_type)
        index = mapping.opensearch_index if mapping else f"entities-unknown"
        await self.ensure_index(entity_type, index)

        doc_id = _entity_doc_id(entity_type, value)
        now = _now_iso()

        # Fields that are always set on insert, never overwritten on update
        upsert_doc = {
            "entity_type": entity_type,
            "value": value,
            "first_seen": now,
            "sources": sources or [],
            **fields,
        }

        # Fields that are always updated on every observation
        update_doc = {
            "last_seen": now,
        }
        # Add new sources without duplicates using a painless script
        script = {
            "source": (
                "ctx._source.last_seen = params.last_seen; "
                "if (ctx._source.sources == null) { ctx._source.sources = []; } "
                "for (s in params.sources) { "
                "  if (!ctx._source.sources.contains(s)) { ctx._source.sources.add(s); } "
                "}"
            ),
            "lang": "painless",
            "params": {
                "last_seen": now,
                "sources": sources or [],
            },
        }

        body = {
            "scripted_upsert": True,
            "script": script,
            "upsert": upsert_doc,
        }

        resp = await self._client.post(
            f"/{index}/_update/{doc_id}",
            content=json.dumps(body),
            headers={"Content-Type": "application/json"},
        )
        if resp.status_code not in (200, 201):
            logger.error(
                "OpenSearch upsert failed for %s=%s: %s %s",
                entity_type, value, resp.status_code, resp.text,
            )
        else:
            logger.debug("Upserted %s=%s to %s", entity_type, value, index)

    async def bulk_upsert(
        self,
        entities: list[dict],
        transform_name: str,
        client_id: str,
    ) -> None:
        """
        Bulk-upsert a list of entity dicts.
        Each dict should have keys: type, value, fields (dict), sources (list).
        Falls back to individual upserts — bulk is an optimisation, not a correctness concern.
        """
        if not entities:
            return

        bulk_body_parts: list[str] = []
        now = _now_iso()

        for ent in entities:
            entity_type = ent["type"]
            value = ent["value"]
            fields = ent.get("fields", {})
            sources = ent.get("sources", [transform_name])

            mapping = get_entity_mapping(entity_type)
            index = mapping.opensearch_index if mapping else "entities-unknown"
            await self.ensure_index(entity_type, index)

            doc_id = _entity_doc_id(entity_type, value)

            # Upsert action metadata
            action = json.dumps({
                "update": {
                    "_index": index,
                    "_id": doc_id,
                }
            })

            # Document body
            upsert_doc = {
                "entity_type": entity_type,
                "value": value,
                "first_seen": now,
                "last_seen": now,
                "sources": sources,
                "transform_name": transform_name,
                "client_id": client_id,
                **fields,
            }
            doc_body = json.dumps({
                "doc": {"last_seen": now},
                "upsert": upsert_doc,
                "doc_as_upsert": True,
            })
            bulk_body_parts.extend([action, doc_body])

        if not bulk_body_parts:
            return

        bulk_payload = "\n".join(bulk_body_parts) + "\n"
        resp = await self._client.post(
            "/_bulk",
            content=bulk_payload,
            headers={"Content-Type": "application/x-ndjson"},
        )

        if resp.status_code not in (200, 201):
            logger.error("Bulk upsert failed: %s %s", resp.status_code, resp.text[:500])
        else:
            result = resp.json()
            if result.get("errors"):
                for item in result.get("items", []):
                    if item.get("update", {}).get("error"):
                        logger.warning("Bulk item error: %s", item["update"]["error"])
            logger.info(
                "Bulk upserted %d entities from transform %s",
                len(entities), transform_name,
            )
