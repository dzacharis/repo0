"""
Tests for OpenSearch and Neo4j writers.

All network I/O is mocked — no running databases required.
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from writers.opensearch_writer import OpenSearchWriter, _entity_doc_id
from writers.neo4j_writer import Neo4jWriter


# ── OpenSearch writer ──────────────────────────────────────────────────────────

class TestEntityDocId:
    def test_same_inputs_same_id(self):
        id1 = _entity_doc_id("maltego.Domain", "example.com")
        id2 = _entity_doc_id("maltego.Domain", "example.com")
        assert id1 == id2

    def test_different_types_different_id(self):
        id1 = _entity_doc_id("maltego.Domain", "example.com")
        id2 = _entity_doc_id("maltego.IPv4Address", "example.com")
        assert id1 != id2

    def test_different_values_different_id(self):
        id1 = _entity_doc_id("maltego.Domain", "example.com")
        id2 = _entity_doc_id("maltego.Domain", "other.com")
        assert id1 != id2

    def test_id_is_hex_string(self):
        doc_id = _entity_doc_id("maltego.Domain", "example.com")
        assert isinstance(doc_id, str)
        int(doc_id, 16)  # raises ValueError if not valid hex


class TestOpenSearchWriter:
    def _make_writer(self):
        writer = OpenSearchWriter(
            host="localhost", port=9200,
            username="admin", password="secret",
            use_tls=False,
        )
        return writer

    @pytest.mark.asyncio
    async def test_ensure_index_creates_if_not_exists(self):
        writer = self._make_writer()
        head_resp = MagicMock(status_code=404)
        put_resp = MagicMock(status_code=201)

        writer._client = AsyncMock()
        writer._client.head = AsyncMock(return_value=head_resp)
        writer._client.put = AsyncMock(return_value=put_resp)

        await writer.ensure_index("maltego.Domain", "entities-domain")
        writer._client.put.assert_called_once()
        call_args = writer._client.put.call_args
        assert "/entities-domain" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_ensure_index_skips_if_exists(self):
        writer = self._make_writer()
        head_resp = MagicMock(status_code=200)
        writer._client = AsyncMock()
        writer._client.head = AsyncMock(return_value=head_resp)
        writer._client.put = AsyncMock()

        await writer.ensure_index("maltego.Domain", "entities-domain")
        writer._client.put.assert_not_called()

    @pytest.mark.asyncio
    async def test_ensure_index_cached_skips_head(self):
        writer = self._make_writer()
        writer._ensured_indices = {"entities-domain"}
        writer._client = AsyncMock()

        await writer.ensure_index("maltego.Domain", "entities-domain")
        writer._client.head.assert_not_called()

    @pytest.mark.asyncio
    async def test_upsert_entity_calls_post(self):
        writer = self._make_writer()
        writer._ensured_indices = {"entities-domain"}
        post_resp = MagicMock(status_code=200)
        writer._client = AsyncMock()
        writer._client.post = AsyncMock(return_value=post_resp)

        await writer.upsert_entity("maltego.Domain", "example.com", {}, sources=["DomainToIP"])
        writer._client.post.assert_called_once()
        url = writer._client.post.call_args[0][0]
        assert "entities-domain" in url
        assert "_update" in url

    @pytest.mark.asyncio
    async def test_upsert_entity_uses_deterministic_id(self):
        writer = self._make_writer()
        writer._ensured_indices = {"entities-domain"}
        post_resp = MagicMock(status_code=200)
        writer._client = AsyncMock()
        writer._client.post = AsyncMock(return_value=post_resp)

        await writer.upsert_entity("maltego.Domain", "example.com", {})
        url = writer._client.post.call_args[0][0]
        expected_id = _entity_doc_id("maltego.Domain", "example.com")
        assert expected_id in url

    @pytest.mark.asyncio
    async def test_bulk_upsert_sends_ndjson(self):
        writer = self._make_writer()
        writer._ensured_indices = {"entities-domain", "entities-ip"}
        bulk_resp = MagicMock(status_code=200)
        bulk_resp.json.return_value = {"errors": False, "items": []}
        writer._client = AsyncMock()
        writer._client.post = AsyncMock(return_value=bulk_resp)

        entities = [
            {"type": "maltego.Domain", "value": "example.com", "fields": {}},
            {"type": "maltego.IPv4Address", "value": "1.2.3.4", "fields": {}},
        ]
        await writer.bulk_upsert(entities, "DomainToIP", "test-client")

        writer._client.post.assert_called_once()
        call_kwargs = writer._client.post.call_args[1]
        assert call_kwargs["headers"]["Content-Type"] == "application/x-ndjson"

    @pytest.mark.asyncio
    async def test_bulk_upsert_empty_is_noop(self):
        writer = self._make_writer()
        writer._client = AsyncMock()
        await writer.bulk_upsert([], "DomainToIP", "test-client")
        writer._client.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_unknown_entity_type_uses_fallback_index(self):
        writer = self._make_writer()
        head_resp = MagicMock(status_code=404)
        put_resp = MagicMock(status_code=201)
        post_resp = MagicMock(status_code=200)
        writer._client = AsyncMock()
        writer._client.head = AsyncMock(return_value=head_resp)
        writer._client.put = AsyncMock(return_value=put_resp)
        writer._client.post = AsyncMock(return_value=post_resp)

        await writer.upsert_entity("maltego.UnknownType", "some-value", {})
        url = writer._client.post.call_args[0][0]
        assert "entities-unknown" in url


# ── Neo4j writer ───────────────────────────────────────────────────────────────

class TestNeo4jWriter:
    def _make_writer(self):
        with patch("writers.neo4j_writer.AsyncGraphDatabase.driver") as mock_driver:
            writer = Neo4jWriter(
                uri="bolt://localhost:7687",
                username="neo4j",
                password="password",
            )
            writer._driver = mock_driver.return_value
        return writer

    @pytest.mark.asyncio
    async def test_ingest_event_merges_input_node(self):
        writer = self._make_writer()

        mock_session = AsyncMock()
        mock_tx = AsyncMock()
        mock_tx.__aenter__ = AsyncMock(return_value=mock_tx)
        mock_tx.__aexit__ = AsyncMock(return_value=False)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.begin_transaction = MagicMock(return_value=mock_tx)
        writer._driver.session = MagicMock(return_value=mock_session)

        await writer.ingest_event(
            transform_name="DomainToIP",
            input_entity={"type": "maltego.Domain", "value": "example.com", "fields": {}},
            output_entities=[{"type": "maltego.IPv4Address", "value": "1.2.3.4", "fields": {}}],
            client_id="test",
        )
        assert mock_tx.run.call_count >= 2

    @pytest.mark.asyncio
    async def test_ingest_event_merges_relationship(self):
        writer = self._make_writer()

        mock_session = AsyncMock()
        mock_tx = AsyncMock()
        mock_tx.__aenter__ = AsyncMock(return_value=mock_tx)
        mock_tx.__aexit__ = AsyncMock(return_value=False)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.begin_transaction = MagicMock(return_value=mock_tx)
        writer._driver.session = MagicMock(return_value=mock_session)

        await writer.ingest_event(
            transform_name="DomainToIP",
            input_entity={"type": "maltego.Domain", "value": "example.com", "fields": {}},
            output_entities=[{"type": "maltego.IPv4Address", "value": "1.2.3.4", "fields": {}}],
            client_id="test",
        )
        assert mock_tx.run.call_count == 3

    @pytest.mark.asyncio
    async def test_ingest_event_no_relationship_for_unknown_triple(self):
        writer = self._make_writer()

        mock_session = AsyncMock()
        mock_tx = AsyncMock()
        mock_tx.__aenter__ = AsyncMock(return_value=mock_tx)
        mock_tx.__aexit__ = AsyncMock(return_value=False)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.begin_transaction = MagicMock(return_value=mock_tx)
        writer._driver.session = MagicMock(return_value=mock_session)

        await writer.ingest_event(
            transform_name="UnknownTransform",
            input_entity={"type": "maltego.Domain", "value": "example.com", "fields": {}},
            output_entities=[{"type": "maltego.IPv4Address", "value": "1.2.3.4", "fields": {}}],
            client_id="test",
        )
        assert mock_tx.run.call_count == 2

    @pytest.mark.asyncio
    async def test_ensure_constraints_runs_for_all_labels(self):
        writer = self._make_writer()
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        writer._driver.session = MagicMock(return_value=mock_session)

        await writer.ensure_constraints()

        from schema import ENTITY_SCHEMA
        expected_labels = {m.neo4j_label for m in ENTITY_SCHEMA.values() if m.neo4j_label}
        assert mock_session.run.call_count >= len(expected_labels)

    @pytest.mark.asyncio
    async def test_upsert_node_cypher_contains_merge(self):
        writer = self._make_writer()
        mock_session = AsyncMock()
        writer._driver.session = MagicMock(return_value=mock_session)

        await writer.upsert_node(mock_session, "maltego.Domain", "example.com")
        assert mock_session.run.called
        cypher = mock_session.run.call_args[0][0]
        assert "MERGE" in cypher
        assert "Domain" in cypher

    @pytest.mark.asyncio
    async def test_upsert_node_unknown_type_uses_generic_label(self):
        writer = self._make_writer()
        mock_session = AsyncMock()
        writer._driver.session = MagicMock(return_value=mock_session)

        await writer.upsert_node(mock_session, "maltego.UnknownType", "some-value")
        cypher = mock_session.run.call_args[0][0]
        assert "Entity" in cypher
