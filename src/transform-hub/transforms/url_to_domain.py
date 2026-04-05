"""
URL → Domain transform.

Input:  maltego.URL  (e.g. "https://www.example.com/path?q=1")
Output: maltego.Domain, maltego.IPv4Address (resolved), maltego.URL (scheme+host)
"""

from __future__ import annotations

import socket
from urllib.parse import urlparse

from .. import transforms as registry
from ..models.maltego import MaltegoEntity, TransformRequest, TransformResponse
from .base import BaseTransform, TransformMeta


@registry.register
class URLToDomain(BaseTransform):
    name = "URLToDomain"
    meta = TransformMeta(
        name="URLToDomain",
        display_name="URL To Domain",
        description="Extracts the domain from a URL and optionally resolves it.",
        input_entity="maltego.URL",
        output_entities=["maltego.Domain", "maltego.IPv4Address"],
    )

    def run(self, entity: MaltegoEntity, request: TransformRequest) -> TransformResponse:
        raw = entity.value.strip()
        if not raw.startswith(("http://", "https://")):
            raw = "https://" + raw
        response = TransformResponse()

        try:
            parsed = urlparse(raw)
        except Exception as exc:
            return response.error(f"Could not parse URL: {exc}", fatal=True)

        hostname = parsed.hostname
        if not hostname:
            return response.error(f"No hostname found in URL: {raw}", fatal=True)

        # Domain entity
        domain_entity = MaltegoEntity(type="maltego.Domain", value=hostname)
        domain_entity.add_field("fqdn", hostname, "FQDN")
        domain_entity.add_field("url.scheme", parsed.scheme, "Scheme")
        domain_entity.add_field("url.port", str(parsed.port or ""), "Port")
        domain_entity.add_field("url.path", parsed.path or "/", "Path")
        response.add_entity(domain_entity)

        # Attempt DNS resolution
        try:
            ip = socket.gethostbyname(hostname)
            ip_entity = MaltegoEntity(type="maltego.IPv4Address", value=ip)
            ip_entity.add_field("ipaddress", ip, "IP Address")
            ip_entity.add_field("fqdn", hostname, "Resolved From")
            response.add_entity(ip_entity)
        except socket.gaierror:
            response.inform(f"Could not resolve {hostname} to an IP address.")

        response.inform(f"Extracted domain '{hostname}' from URL")
        return response
