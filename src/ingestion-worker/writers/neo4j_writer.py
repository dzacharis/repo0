"""
Neo4j writer for the ingestion pipeline.

Responsibilities
────────────────
- MERGE nodes (upsert by id_property) — never creates duplicates.
- MERGE relationships between the input entity and each output entity,
  using the relationship type from the mapping schema.
- Set created_at on first creation, updated_at on every touch.
- All writes are transactional per event batch.

Cypher patterns used
────────────────────
  MERGE (n:Label {id_prop: $value})
  ON CREATE SET n.created_at = $now, n += $props
  ON MATCH  SET n.updated_at = $now, n += $props

  MERGE (src)-[r:REL_TYPE]->(tgt)
  ON CREATE SET r.created_at = $now, r.sources = [$source]
  ON MATCH  SET r.updated_at = $now, r.sources = CASE
    WHEN $source IN r.sources THEN r.sources
    ELSE r.sources + [$source]
  END
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from neo4j import AsyncDriver, AsyncGraphDatabase, AsyncSession
from neo4j.exceptions import Neo4jError

from schema import (
    EntityMapping,
    RelationshipMapping,
    get_entity_mapping,
    get_relationship_mapping,
)

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Neo4jWriter:
    """
    Writes entity nodes and relationships to Neo4j via the Bolt protocol.
    Uses the async driver (neo4j[async] extra).
    """

    def __init__(self, uri: str, username: str, password: str) -> None:
        self._driver: AsyncDriver = AsyncGraphDatabase.driver(
            uri,
            auth=(username, password),
            max_connection_lifetime=3600,
            max_connection_pool_size=10,
            connection_acquisition_timeout=10.0,
        )

    async def close(self) -> None:
        await self._driver.close()

    async def verify_connectivity(self) -> None:
        await self._driver.verify_connectivity()
        logger.info("Neo4j connectivity verified")

    async def upsert_node(
        self,
        session: AsyncSession,
        entity_type: str,
        value: str,
        extra_props: dict | None = None,
    ) -> None:
        """MERGE a node, setting properties on create and updating timestamps on match."""
        mapping: EntityMapping | None = get_entity_mapping(entity_type)
        if not mapping or not mapping.neo4j_label:
            # Unknown entity type — store as a generic Entity node
            label = "Entity"
            id_prop = "value"
        else:
            label = mapping.neo4j_label
            id_prop = mapping.neo4j_id_property

        props = {id_prop: value, "entity_type": entity_type}
        if extra_props:
            # Only include properties declared in the schema (whitelist)
            if mapping:
                allowed = {p.source_field for p in mapping.neo4j_properties}
                props.update({k: v for k, v in extra_props.items() if k in allowed})
            else:
                props.update(extra_props)

        now = _now()
        cypher = (
            f"MERGE (n:{label} {{{id_prop}: $id_val}}) "
            "ON CREATE SET n.created_at = $now, n.updated_at = $now, n += $props "
            "ON MATCH  SET n.updated_at = $now, n += $props"
        )
        try:
            await session.run(cypher, id_val=value, now=now, props=props)
        except Neo4jError as exc:
            logger.error("Neo4j node upsert failed for %s=%s: %s", entity_type, value, exc)
            raise

    async def upsert_relationship(
        self,
        session: AsyncSession,
        rel: RelationshipMapping,
        source_id: str,
        target_id: str,
        source_prop: str,
        target_prop: str,
        transform_name: str,
    ) -> None:
        """MERGE a directed relationship between two already-merged nodes."""
        now = _now()
        cypher = (
            f"MATCH (src:{rel.source_label} {{{source_prop}: $src_id}}) "
            f"MATCH (tgt:{rel.target_label} {{{target_prop}: $tgt_id}}) "
            f"MERGE (src)-[r:{rel.rel_type}]->(tgt) "
            "ON CREATE SET r.created_at = $now, r.updated_at = $now, "
            "              r.sources = [$transform] "
            "ON MATCH  SET r.updated_at = $now, "
            "              r.sources = CASE "
            "                WHEN $transform IN r.sources THEN r.sources "
            "                ELSE r.sources + [$transform] "
            "              END"
        )
        try:
            await session.run(
                cypher,
                src_id=source_id,
                tgt_id=target_id,
                now=now,
                transform=transform_name,
            )
        except Neo4jError as exc:
            logger.warning(
                "Neo4j relationship upsert failed %s -[%s]-> %s: %s",
                source_id, rel.rel_type, target_id, exc,
            )

    async def ingest_event(
        self,
        transform_name: str,
        input_entity: dict,
        output_entities: list[dict],
        client_id: str,
    ) -> None:
        """
        Process one transform result event:
          1. Merge the input entity node.
          2. For each output entity:
             a. Merge the output entity node.
             b. If a relationship mapping exists, merge the relationship.
        All writes happen in a single transaction.
        """
        async with self._driver.session() as session:
            async with session.begin_transaction() as tx:
                input_type = input_entity["type"]
                input_value = input_entity["value"]
                input_fields = input_entity.get("fields", {})

                # 1. Merge input node
                input_mapping = get_entity_mapping(input_type)
                input_id_prop = input_mapping.neo4j_id_property if input_mapping else "value"
                await self.upsert_node(tx, input_type, input_value, input_fields)

                for output_ent in output_entities:
                    output_type = output_ent["type"]
                    output_value = output_ent["value"]
                    output_fields = output_ent.get("fields", {})

                    # 2a. Merge output node
                    output_mapping = get_entity_mapping(output_type)
                    output_id_prop = output_mapping.neo4j_id_property if output_mapping else "value"
                    await self.upsert_node(tx, output_type, output_value, output_fields)

                    # 2b. Merge relationship if schema defines one
                    rel = get_relationship_mapping(transform_name, input_type, output_type)
                    if rel:
                        await self.upsert_relationship(
                            tx,
                            rel=rel,
                            source_id=input_value,
                            target_id=output_value,
                            source_prop=input_id_prop,
                            target_prop=output_id_prop,
                            transform_name=transform_name,
                        )
                    else:
                        logger.debug(
                            "No relationship schema for (%s, %s, %s) — nodes merged only",
                            transform_name, input_type, output_type,
                        )

                await tx.commit()

        logger.info(
            "Neo4j: ingested %d output entities from %s",
            len(output_entities), transform_name,
        )

    async def ensure_constraints(self) -> None:
        """
        Create uniqueness constraints for each entity label.
        Safe to call at startup — constraints are idempotent in Neo4j 5.x.
        """
        from schema import ENTITY_SCHEMA

        async with self._driver.session() as session:
            for entity_type, mapping in ENTITY_SCHEMA.items():
                if not mapping.neo4j_label:
                    continue
                constraint_name = (
                    f"unique_{mapping.neo4j_label.lower()}_{mapping.neo4j_id_property}"
                )
                cypher = (
                    f"CREATE CONSTRAINT {constraint_name} IF NOT EXISTS "
                    f"FOR (n:{mapping.neo4j_label}) "
                    f"REQUIRE n.{mapping.neo4j_id_property} IS UNIQUE"
                )
                try:
                    await session.run(cypher)
                    logger.debug("Constraint ensured: %s", constraint_name)
                except Neo4jError as exc:
                    # Constraint may already exist with slightly different definition
                    logger.warning("Constraint setup warning for %s: %s", constraint_name, exc)
