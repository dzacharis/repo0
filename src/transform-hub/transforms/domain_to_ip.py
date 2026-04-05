"""
Domain → IP Address transform.

Input:  maltego.Domain  (e.g. "example.com")
Output: maltego.IPv4Address entities (one per A record)
"""

from __future__ import annotations

import dns.resolver

from .. import transforms as registry
from ..models.maltego import MaltegoEntity, TransformRequest, TransformResponse
from .base import BaseTransform, TransformMeta


@registry.register
class DomainToIP(BaseTransform):
    name = "DomainToIP"
    meta = TransformMeta(
        name="DomainToIP",
        display_name="Domain To IP Address",
        description="Resolves a domain name to its A-record IPv4 addresses.",
        input_entity="maltego.Domain",
        output_entities=["maltego.IPv4Address"],
    )

    def run(self, entity: MaltegoEntity, request: TransformRequest) -> TransformResponse:
        domain = entity.value.strip().lower()
        response = TransformResponse()

        try:
            answers = dns.resolver.resolve(domain, "A")
        except dns.resolver.NXDOMAIN:
            return response.error(f"Domain '{domain}' does not exist (NXDOMAIN).")
        except dns.resolver.NoAnswer:
            return response.error(f"No A records found for '{domain}'.")
        except Exception as exc:
            return response.error(f"DNS resolution failed: {exc}")

        added = 0
        for rdata in answers:
            if added >= request.limits.soft_limit:
                response.inform(f"Soft limit reached ({request.limits.soft_limit}). Truncating.")
                break
            ip = str(rdata)
            result = MaltegoEntity(type="maltego.IPv4Address", value=ip)
            result.add_field("ipaddress", ip, "IP Address")
            result.add_field("fqdn", domain, "Source Domain")
            response.add_entity(result)
            added += 1

        response.inform(f"Resolved {added} IP address(es) for {domain}")
        return response
