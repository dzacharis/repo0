"""
Domain → MX Records transform.

Input:  maltego.Domain
Output: maltego.MXRecord, maltego.Domain (mail server hostnames)
"""

from __future__ import annotations

import dns.resolver

import transforms as registry
from models.maltego import MaltegoEntity, TransformRequest, TransformResponse
from .base import BaseTransform, TransformMeta


@registry.register
class DomainToMX(BaseTransform):
    name = "DomainToMX"
    meta = TransformMeta(
        name="DomainToMX",
        display_name="Domain To MX Records",
        description="Returns the mail exchange (MX) records for a domain.",
        input_entity="maltego.Domain",
        output_entities=["maltego.MXRecord", "maltego.Domain"],
    )

    def run(self, entity: MaltegoEntity, request: TransformRequest) -> TransformResponse:
        domain = entity.value.strip().lower()
        response = TransformResponse()

        try:
            answers = dns.resolver.resolve(domain, "MX")
        except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer) as exc:
            return response.error(f"No MX records for '{domain}': {exc}")
        except Exception as exc:
            return response.error(f"DNS lookup failed: {exc}")

        for rdata in answers:
            host = str(rdata.exchange).rstrip(".")
            priority = rdata.preference

            # Emit the MX record entity
            mx_entity = MaltegoEntity(type="maltego.MXRecord", value=f"{priority} {host}")
            mx_entity.add_field("mx.priority", str(priority), "Priority")
            mx_entity.add_field("mx.exchange", host, "Mail Server")
            mx_entity.add_field("fqdn", domain, "Domain")
            response.add_entity(mx_entity)

            # Also emit the mail-server domain so users can pivot further
            mail_domain = MaltegoEntity(type="maltego.Domain", value=host)
            mail_domain.add_field("fqdn", host, "FQDN")
            response.add_entity(mail_domain)

        response.inform(f"Found {len(answers)} MX record(s) for {domain}")
        return response
