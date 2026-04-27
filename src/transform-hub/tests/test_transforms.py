"""
Unit tests for all built-in transforms.

All external I/O (DNS, HTTP) is mocked so tests run offline and deterministically.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from models.maltego import MaltegoEntity, TransformLimits, TransformRequest, TransformResponse
from conftest import make_entity, make_request


# ── Helpers ────────────────────────────────────────────────────────────────────

def run(transform_cls, entity_type: str, value: str, fields: dict | None = None,
        soft_limit: int = 12) -> TransformResponse:
    entity = make_entity(entity_type, value, fields)
    request = make_request(entity, soft_limit)
    instance = transform_cls()
    return instance.execute(request)


# ── DomainToIP ─────────────────────────────────────────────────────────────────

class TestDomainToIP:
    def _mock_answer(self, ips: list[str]):
        answers = [MagicMock(address=ip, __str__=lambda self, ip=ip: ip) for ip in ips]
        mock = MagicMock()
        mock.__iter__ = MagicMock(return_value=iter(answers))
        return mock

    @patch("transforms.domain_to_ip.dns.resolver.resolve")
    def test_single_ip(self, mock_resolve):
        from transforms.domain_to_ip import DomainToIP
        mock_resolve.return_value = self._mock_answer(["1.2.3.4"])
        resp = run(DomainToIP, "maltego.Domain", "example.com")
        assert len(resp.entities) == 1
        assert resp.entities[0].value == "1.2.3.4"
        assert resp.entities[0].type == "maltego.IPv4Address"

    @patch("transforms.domain_to_ip.dns.resolver.resolve")
    def test_multiple_ips(self, mock_resolve):
        from transforms.domain_to_ip import DomainToIP
        mock_resolve.return_value = self._mock_answer(["1.1.1.1", "1.0.0.1"])
        resp = run(DomainToIP, "maltego.Domain", "cloudflare.com")
        assert len(resp.entities) == 2

    @patch("transforms.domain_to_ip.dns.resolver.resolve")
    def test_soft_limit_respected(self, mock_resolve):
        from transforms.domain_to_ip import DomainToIP
        mock_resolve.return_value = self._mock_answer(["1.1.1.1", "2.2.2.2", "3.3.3.3"])
        resp = run(DomainToIP, "maltego.Domain", "example.com", soft_limit=2)
        assert len(resp.entities) == 2

    @patch("transforms.domain_to_ip.dns.resolver.resolve")
    def test_nxdomain_returns_error(self, mock_resolve):
        from transforms.domain_to_ip import DomainToIP
        import dns.resolver
        mock_resolve.side_effect = dns.resolver.NXDOMAIN()
        resp = run(DomainToIP, "maltego.Domain", "nonexistent.invalid")
        assert len(resp.entities) == 0
        assert any("NXDOMAIN" in m.text for m in resp.ui_messages)

    @patch("transforms.domain_to_ip.dns.resolver.resolve")
    def test_no_answer_returns_error(self, mock_resolve):
        from transforms.domain_to_ip import DomainToIP
        import dns.resolver
        mock_resolve.side_effect = dns.resolver.NoAnswer()
        resp = run(DomainToIP, "maltego.Domain", "example.com")
        assert len(resp.entities) == 0
        assert len(resp.ui_messages) > 0

    @patch("transforms.domain_to_ip.dns.resolver.resolve")
    def test_generic_exception_returns_error(self, mock_resolve):
        from transforms.domain_to_ip import DomainToIP
        mock_resolve.side_effect = Exception("network timeout")
        resp = run(DomainToIP, "maltego.Domain", "example.com")
        assert len(resp.entities) == 0


# ── DomainToMX ────────────────────────────────────────────────────────────────

class TestDomainToMX:
    def _mock_mx_answer(self, records: list[tuple[str, int]]):
        answers = []
        for exchange, pref in records:
            r = MagicMock()
            r.exchange = MagicMock(__str__=lambda self, e=exchange: e + ".")
            r.preference = pref
            answers.append(r)
        mock = MagicMock()
        mock.__iter__ = MagicMock(return_value=iter(answers))
        return mock

    @patch("transforms.domain_to_mx.dns.resolver.resolve")
    def test_single_mx(self, mock_resolve):
        from transforms.domain_to_mx import DomainToMX
        mock_resolve.return_value = self._mock_mx_answer([("mail.example.com", 10)])
        resp = run(DomainToMX, "maltego.Domain", "example.com")
        assert len(resp.entities) >= 1
        mx_entities = [e for e in resp.entities if e.type == "maltego.MXRecord"]
        assert len(mx_entities) == 1
        assert "mail.example.com" in mx_entities[0].value

    @patch("transforms.domain_to_mx.dns.resolver.resolve")
    def test_multiple_mx_records(self, mock_resolve):
        from transforms.domain_to_mx import DomainToMX
        mock_resolve.return_value = self._mock_mx_answer([
            ("alt1.aspmx.l.google.com", 5),
            ("aspmx.l.google.com", 1),
        ])
        resp = run(DomainToMX, "maltego.Domain", "gmail.com")
        mx = [e for e in resp.entities if e.type == "maltego.MXRecord"]
        assert len(mx) == 2

    @patch("transforms.domain_to_mx.dns.resolver.resolve")
    def test_dns_error_returns_error_message(self, mock_resolve):
        from transforms.domain_to_mx import DomainToMX
        import dns.resolver
        mock_resolve.side_effect = dns.resolver.NoAnswer()
        resp = run(DomainToMX, "maltego.Domain", "example.com")
        assert len(resp.entities) == 0


# ── URLToDomain ───────────────────────────────────────────────────────────────

class TestURLToDomain:
    def test_basic_url_extraction(self):
        from transforms.url_to_domain import URLToDomain
        with patch("transforms.url_to_domain.socket.gethostbyname",
                   return_value="93.184.216.34"):
            resp = run(URLToDomain, "maltego.URL", "https://example.com/some/path?q=1")
        domain_entities = [e for e in resp.entities if e.type == "maltego.Domain"]
        assert len(domain_entities) == 1
        assert domain_entities[0].value == "example.com"

    def test_ip_entity_returned(self):
        from transforms.url_to_domain import URLToDomain
        with patch("transforms.url_to_domain.socket.gethostbyname",
                   return_value="1.2.3.4"):
            resp = run(URLToDomain, "maltego.URL", "https://example.com/")
        ip_entities = [e for e in resp.entities if e.type == "maltego.IPv4Address"]
        assert len(ip_entities) == 1
        assert ip_entities[0].value == "1.2.3.4"

    def test_dns_failure_still_returns_domain(self):
        from transforms.url_to_domain import URLToDomain
        import socket
        with patch("transforms.url_to_domain.socket.gethostbyname",
                   side_effect=socket.gaierror("no address")):
            resp = run(URLToDomain, "maltego.URL", "https://example.com/")
        domain_entities = [e for e in resp.entities if e.type == "maltego.Domain"]
        assert len(domain_entities) == 1

    def test_empty_value_returns_error(self):
        from transforms.url_to_domain import URLToDomain
        resp = run(URLToDomain, "maltego.URL", "")
        assert len(resp.ui_messages) > 0


# ── DomainToWHOIS ─────────────────────────────────────────────────────────────

class TestDomainToWHOIS:
    RDAP_RESPONSE = {
        "ldhName": "EXAMPLE.COM",
        "entities": [
            {
                "roles": ["registrant"],
                "vcardArray": ["vcard", [
                    ["version", {}, "text", "4.0"],
                    ["fn", {}, "text", "John Doe"],
                    ["email", {}, "text", "john@example.com"],
                    ["tel", {}, "uri", "tel:+15551234567"],
                ]],
            }
        ],
        "nameservers": [
            {"ldhName": "NS1.EXAMPLE.COM"},
            {"ldhName": "NS2.EXAMPLE.COM"},
        ],
    }

    @patch("transforms.domain_to_whois.httpx.get")
    def test_returns_person_entity(self, mock_get):
        from transforms.domain_to_whois import DomainToWhois
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = self.RDAP_RESPONSE
        mock_get.return_value = mock_resp

        resp = run(DomainToWhois, "maltego.Domain", "example.com")
        person_entities = [e for e in resp.entities if e.type == "maltego.Person"]
        assert len(person_entities) >= 1
        assert person_entities[0].value == "John Doe"

    @patch("transforms.domain_to_whois.httpx.get")
    def test_returns_email_entity(self, mock_get):
        from transforms.domain_to_whois import DomainToWhois
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = self.RDAP_RESPONSE
        mock_get.return_value = mock_resp

        resp = run(DomainToWhois, "maltego.Domain", "example.com")
        email_entities = [e for e in resp.entities if e.type == "maltego.EmailAddress"]
        assert any("john@example.com" in e.value for e in email_entities)

    @patch("transforms.domain_to_whois.httpx.get")
    def test_http_error_returns_error_message(self, mock_get):
        from transforms.domain_to_whois import DomainToWhois
        import httpx
        mock_get.side_effect = httpx.HTTPError("connection refused")
        resp = run(DomainToWhois, "maltego.Domain", "example.com")
        assert len(resp.ui_messages) > 0
        assert len(resp.entities) == 0


# ── IPToGeoLocation ────────────────────────────────────────────────────────────

class TestIPToGeoLocation:
    GEO_RESPONSE = {
        "status": "success",
        "country": "United States",
        "countryCode": "US",
        "regionName": "California",
        "city": "Los Angeles",
        "lat": 34.052235,
        "lon": -118.243683,
        "isp": "Example ISP",
        "org": "Example Org",
        "as": "AS12345 Example AS",
        "query": "93.184.216.34",
    }

    @patch("transforms.ip_to_geolocation.httpx.get")
    def test_returns_location_entity(self, mock_get):
        from transforms.ip_to_geolocation import IPToGeoLocation
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = self.GEO_RESPONSE
        mock_get.return_value = mock_resp

        resp = run(IPToGeoLocation, "maltego.IPv4Address", "93.184.216.34")
        location_entities = [e for e in resp.entities if e.type == "maltego.Location"]
        assert len(location_entities) >= 1
        assert "United States" in location_entities[0].value or "Los Angeles" in location_entities[0].value

    @patch("transforms.ip_to_geolocation.httpx.get")
    def test_api_failure_returns_error(self, mock_get):
        from transforms.ip_to_geolocation import IPToGeoLocation
        import httpx
        mock_get.side_effect = httpx.HTTPError("timeout")
        resp = run(IPToGeoLocation, "maltego.IPv4Address", "1.2.3.4")
        assert len(resp.ui_messages) > 0
        assert len(resp.entities) == 0

    @patch("transforms.ip_to_geolocation.httpx.get")
    def test_api_status_fail(self, mock_get):
        from transforms.ip_to_geolocation import IPToGeoLocation
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"status": "fail", "message": "private range"}
        mock_get.return_value = mock_resp
        resp = run(IPToGeoLocation, "maltego.IPv4Address", "192.168.1.1")
        assert len(resp.ui_messages) > 0


# ── BaseTransform contract ─────────────────────────────────────────────────────

class TestBaseTransformContract:
    def test_execute_with_no_entities_returns_error(self):
        from transforms.domain_to_ip import DomainToIP
        empty_request = TransformRequest(entities=[])
        resp = DomainToIP().execute(empty_request)
        assert any(m.text for m in resp.ui_messages)

    def test_transform_registry(self):
        import transforms as registry
        transforms = registry.all_transforms()
        assert "DomainToIP" in transforms
        assert "DomainToMX" in transforms or "DomainToMXRecord" in transforms
        assert "URLToDomain" in transforms

    def test_get_transform_returns_none_for_unknown(self):
        import transforms as registry
        assert registry.get_transform("NonExistentTransform") is None

    def test_meta_has_required_fields(self):
        import transforms as registry
        for name, cls in registry.all_transforms().items():
            instance = cls()
            assert instance.meta.name, f"{name}: meta.name is empty"
            assert instance.meta.input_entity, f"{name}: meta.input_entity is empty"
