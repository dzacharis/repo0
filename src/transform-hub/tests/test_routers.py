"""
HTTP-layer tests for the transform and manifest routers.

Uses FastAPI's synchronous TestClient with the auth dependency overridden.
External calls (DNS, HTTP, Dapr pub/sub) are mocked per test.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from .conftest import MOCK_TOKEN_CLAIMS, SIMPLE_XML


# ── Manifest router ────────────────────────────────────────────────────────────

class TestManifestRouter:
    def test_manifest_returns_200(self, app_client):
        resp = app_client.get("/api/v2/manifest")
        assert resp.status_code == 200

    def test_manifest_contains_transforms(self, app_client):
        resp = app_client.get("/api/v2/manifest")
        data = resp.json()
        assert "transforms" in data
        assert len(data["transforms"]) > 0

    def test_manifest_transform_has_required_keys(self, app_client):
        resp = app_client.get("/api/v2/manifest")
        transform = resp.json()["transforms"][0]
        assert "name" in transform
        assert "inputEntity" in transform

    def test_manifest_requires_auth(self):
        """Manifest endpoint must reject unauthenticated requests."""
        from ..main import app
        # Temporarily clear overrides
        original = app.dependency_overrides.copy()
        app.dependency_overrides.clear()

        from fastapi.testclient import TestClient
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/api/v2/manifest")
        assert resp.status_code in (401, 403)

        app.dependency_overrides.update(original)


# ── Transform router ───────────────────────────────────────────────────────────

SIMPLE_XML = b"""<?xml version="1.0"?>
<MaltegoMessage>
  <MaltegoTransformRequestMessage>
    <Entities>
      <Entity Type="maltego.Domain">
        <Value>example.com</Value>
        <Weight>100</Weight>
      </Entity>
    </Entities>
    <Limits SoftLimit="12" HardLimit="255"/>
  </MaltegoTransformRequestMessage>
</MaltegoMessage>"""

SIMPLE_JSON_BODY = {
    "Entities": {
        "Entity": [{"Type": "maltego.Domain", "Value": "example.com", "Weight": 100,
                     "AdditionalFields": {"Field": []}}]
    },
    "Limits": {"SoftLimit": "12", "HardLimit": "255"},
}


class TestTransformRouter:
    @patch("src.transform_hub.transforms.domain_to_ip.dns.resolver.resolve")
    @patch("src.transform_hub.routers.transforms._publish_entity_event", new_callable=AsyncMock)
    def test_execute_xml_returns_200(self, _mock_pub, mock_dns, app_client):
        mock_dns.return_value = [MagicMock(__str__=lambda self: "1.2.3.4")]
        resp = app_client.post(
            "/api/v2/transforms/DomainToIP",
            content=SIMPLE_XML,
            headers={"Content-Type": "application/xml"},
        )
        assert resp.status_code == 200
        assert b"MaltegoTransformResponseMessage" in resp.content

    @patch("src.transform_hub.transforms.domain_to_ip.dns.resolver.resolve")
    @patch("src.transform_hub.routers.transforms._publish_entity_event", new_callable=AsyncMock)
    def test_execute_json_returns_200(self, _mock_pub, mock_dns, app_client):
        mock_dns.return_value = [MagicMock(__str__=lambda self: "1.2.3.4")]
        resp = app_client.post(
            "/api/v2/transforms/DomainToIP",
            json=SIMPLE_JSON_BODY,
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "MaltegoTransformResponseMessage" in data

    def test_unknown_transform_returns_404(self, app_client):
        resp = app_client.post(
            "/api/v2/transforms/NoSuchTransform",
            content=SIMPLE_XML,
            headers={"Content-Type": "application/xml"},
        )
        assert resp.status_code == 404

    def test_malformed_body_returns_400(self, app_client):
        resp = app_client.post(
            "/api/v2/transforms/DomainToIP",
            content=b"not valid xml",
            headers={"Content-Type": "application/xml"},
        )
        assert resp.status_code == 400

    def test_list_transforms_returns_all(self, app_client):
        resp = app_client.get("/api/v2/transforms")
        assert resp.status_code == 200
        data = resp.json()
        assert "transforms" in data
        names = [t["name"] for t in data["transforms"]]
        assert "DomainToIP" in names

    @patch("src.transform_hub.transforms.domain_to_ip.dns.resolver.resolve")
    @patch("src.transform_hub.routers.transforms._publish_entity_event", new_callable=AsyncMock)
    def test_response_content_type_xml(self, _mock_pub, mock_dns, app_client):
        mock_dns.return_value = [MagicMock(__str__=lambda self: "1.2.3.4")]
        resp = app_client.post(
            "/api/v2/transforms/DomainToIP",
            content=SIMPLE_XML,
            headers={"Content-Type": "application/xml"},
        )
        assert "xml" in resp.headers.get("content-type", "")

    @patch("src.transform_hub.transforms.domain_to_ip.dns.resolver.resolve")
    @patch("src.transform_hub.routers.transforms._publish_entity_event", new_callable=AsyncMock)
    def test_response_content_type_json(self, _mock_pub, mock_dns, app_client):
        mock_dns.return_value = [MagicMock(__str__=lambda self: "1.2.3.4")]
        resp = app_client.post(
            "/api/v2/transforms/DomainToIP",
            json=SIMPLE_JSON_BODY,
            headers={"Content-Type": "application/json"},
        )
        assert "json" in resp.headers.get("content-type", "")


# ── Health endpoint ────────────────────────────────────────────────────────────

class TestHealthEndpoint:
    def test_health_returns_200(self, app_client):
        resp = app_client.get("/health")
        assert resp.status_code == 200

    def test_health_returns_ok(self, app_client):
        resp = app_client.get("/health")
        assert resp.json().get("status") == "ok"
