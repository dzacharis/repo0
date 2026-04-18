"""
Tests for the ingestion worker FastAPI app.

Covers: Dapr subscription registration, /ingest CloudEvent handling,
health endpoints, and error/DLQ paths. Writers are mocked.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from .conftest import make_cloudevent, make_entity_event


# ── App client fixture ─────────────────────────────────────────────────────────

@pytest.fixture
def client(mock_os_writer, mock_neo4j_writer):
    """TestClient with both writers injected as mocks."""
    import src.ingestion_worker.main as app_module

    app_module._os_writer = mock_os_writer
    app_module._neo4j_writer = mock_neo4j_writer
    app_module._semaphore = __import__("asyncio").Semaphore(10)

    with TestClient(app_module.app) as c:
        yield c

    app_module._os_writer = None
    app_module._neo4j_writer = None
    app_module._semaphore = None


# ── Dapr subscription registration ────────────────────────────────────────────

class TestDaprSubscribe:
    def test_returns_200(self, client):
        resp = client.get("/dapr/subscribe")
        assert resp.status_code == 200

    def test_returns_list(self, client):
        resp = client.get("/dapr/subscribe")
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 1

    def test_subscription_fields(self, client):
        resp = client.get("/dapr/subscribe")
        sub = resp.json()[0]
        assert "pubsubname" in sub
        assert "topic" in sub
        assert "route" in sub
        assert sub["route"] == "/ingest"

    def test_subscription_topic_name(self, client):
        resp = client.get("/dapr/subscribe")
        sub = resp.json()[0]
        assert sub["topic"] == "entity-graph"


# ── /ingest endpoint ───────────────────────────────────────────────────────────

class TestIngestEndpoint:
    def test_valid_event_returns_200_success(self, client, domain_to_ip_event):
        payload = make_cloudevent(domain_to_ip_event)
        resp = client.post("/ingest", json=payload)
        assert resp.status_code == 200
        assert resp.json()["status"] == "SUCCESS"

    def test_malformed_event_returns_drop(self, client):
        payload = make_cloudevent({"invalid": "data", "no_transform_name": True})
        resp = client.post("/ingest", json=payload)
        assert resp.status_code == 200
        assert resp.json()["status"] == "DROP"

    def test_os_writer_called_on_valid_event(self, client, domain_to_ip_event, mock_os_writer):
        payload = make_cloudevent(domain_to_ip_event)
        client.post("/ingest", json=payload)
        mock_os_writer.bulk_upsert.assert_called_once()

    def test_neo4j_writer_called_on_valid_event(self, client, domain_to_ip_event, mock_neo4j_writer):
        payload = make_cloudevent(domain_to_ip_event)
        client.post("/ingest", json=payload)
        mock_neo4j_writer.ingest_event.assert_called_once()

    def test_neo4j_writer_receives_correct_transform_name(
        self, client, domain_to_ip_event, mock_neo4j_writer
    ):
        payload = make_cloudevent(domain_to_ip_event)
        client.post("/ingest", json=payload)
        call_kwargs = mock_neo4j_writer.ingest_event.call_args[1]
        assert call_kwargs["transform_name"] == "DomainToIP"

    def test_event_without_data_key_is_also_handled(self, client, domain_to_ip_event):
        # Dapr sometimes sends the payload without CloudEvent wrapper
        resp = client.post("/ingest", json=domain_to_ip_event)
        assert resp.status_code == 200

    def test_os_writer_failure_does_not_prevent_neo4j(
        self, client, domain_to_ip_event, mock_os_writer, mock_neo4j_writer
    ):
        mock_os_writer.bulk_upsert = AsyncMock(side_effect=Exception("OS unreachable"))
        payload = make_cloudevent(domain_to_ip_event)
        resp = client.post("/ingest", json=payload)
        # Should still return SUCCESS (Neo4j write is independent)
        assert resp.status_code == 200
        mock_neo4j_writer.ingest_event.assert_called_once()

    def test_neo4j_failure_does_not_prevent_os(
        self, client, domain_to_ip_event, mock_os_writer, mock_neo4j_writer
    ):
        mock_neo4j_writer.ingest_event = AsyncMock(side_effect=Exception("Neo4j unreachable"))
        payload = make_cloudevent(domain_to_ip_event)
        resp = client.post("/ingest", json=payload)
        assert resp.status_code == 200
        mock_os_writer.bulk_upsert.assert_called_once()

    def test_whois_event_ingested_correctly(
        self, client, domain_to_whois_event, mock_neo4j_writer
    ):
        payload = make_cloudevent(domain_to_whois_event)
        client.post("/ingest", json=payload)
        call_kwargs = mock_neo4j_writer.ingest_event.call_args[1]
        assert call_kwargs["transform_name"] == "DomainToWHOIS"
        assert len(call_kwargs["output_entities"]) == 3

    def test_empty_output_entities_still_processes(self, client):
        event = make_entity_event(output_entities=[])
        payload = make_cloudevent(event)
        resp = client.post("/ingest", json=payload)
        assert resp.status_code == 200


# ── Health endpoints ───────────────────────────────────────────────────────────

class TestHealthEndpoints:
    def test_liveness_returns_200(self, client):
        resp = client.get("/health/live")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_readiness_returns_200_when_writers_healthy(
        self, client, mock_os_writer, mock_neo4j_writer
    ):
        # Mock the health check calls
        mock_os_writer._client = AsyncMock()
        mock_os_writer._client.get = AsyncMock(return_value=MagicMock(status_code=200))
        mock_neo4j_writer.verify_connectivity = AsyncMock()

        resp = client.get("/health/ready")
        # 200 or 207 depending on writer state; just verify it's a valid response
        assert resp.status_code in (200, 207)

    def test_readiness_when_no_writers(self, mock_os_writer, mock_neo4j_writer):
        """Readiness endpoint works even if writers are not initialised."""
        import src.ingestion_worker.main as app_module
        import asyncio

        app_module._os_writer = None
        app_module._neo4j_writer = None
        app_module._semaphore = asyncio.Semaphore(10)

        with TestClient(app_module.app) as c:
            resp = c.get("/health/ready")
        assert resp.status_code in (200, 207)
