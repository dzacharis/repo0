"""Shared fixtures for the ingestion-worker test suite."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


# ── Sample event payloads ──────────────────────────────────────────────────────

def make_entity_event(
    transform_name: str = "DomainToIP",
    input_type: str = "maltego.Domain",
    input_value: str = "example.com",
    output_entities: list[dict] | None = None,
) -> dict:
    return {
        "schema_version": "1.0",
        "transform_name": transform_name,
        "input_entity": {"type": input_type, "value": input_value, "fields": {}},
        "output_entities": output_entities or [
            {"type": "maltego.IPv4Address", "value": "1.2.3.4", "fields": {}}
        ],
        "client_id": "test-client",
        "request_id": "req-001",
        "timestamp": "2024-01-01T00:00:00Z",
    }


def make_cloudevent(data: dict) -> dict:
    """Wrap an entity event in a minimal Dapr CloudEvent envelope."""
    return {
        "specversion": "1.0",
        "type": "com.dapr.event.sent",
        "source": "transform-hub",
        "id": "test-event-id",
        "datacontenttype": "application/json",
        "data": data,
    }


@pytest.fixture
def domain_to_ip_event():
    return make_entity_event(
        transform_name="DomainToIP",
        input_type="maltego.Domain",
        input_value="example.com",
        output_entities=[
            {"type": "maltego.IPv4Address", "value": "1.2.3.4", "fields": {}},
            {"type": "maltego.IPv4Address", "value": "5.6.7.8", "fields": {}},
        ],
    )


@pytest.fixture
def domain_to_whois_event():
    return make_entity_event(
        transform_name="DomainToWHOIS",
        input_type="maltego.Domain",
        input_value="example.com",
        output_entities=[
            {"type": "maltego.Person", "value": "John Doe", "fields": {}},
            {"type": "maltego.EmailAddress", "value": "john@example.com", "fields": {}},
            {"type": "maltego.Organization", "value": "Example Corp", "fields": {}},
        ],
    )


@pytest.fixture
def ip_to_geo_event():
    return make_entity_event(
        transform_name="IPToGeolocation",
        input_type="maltego.IPv4Address",
        input_value="1.2.3.4",
        output_entities=[
            {"type": "maltego.Location", "value": "Los Angeles, US", "fields": {}},
            {"type": "maltego.AS", "value": "AS12345", "fields": {}},
        ],
    )


# ── Mock writer fixtures ───────────────────────────────────────────────────────

@pytest.fixture
def mock_os_writer():
    writer = MagicMock()
    writer.bulk_upsert = AsyncMock()
    writer.upsert_entity = AsyncMock()
    writer.ensure_index = AsyncMock()
    writer.close = AsyncMock()
    return writer


@pytest.fixture
def mock_neo4j_writer():
    writer = MagicMock()
    writer.ingest_event = AsyncMock()
    writer.ensure_constraints = AsyncMock()
    writer.verify_connectivity = AsyncMock()
    writer.close = AsyncMock()
    return writer
