"""
Domain → WHOIS transform.

Queries the RDAP (Registration Data Access Protocol) endpoint — a structured,
JSON-based successor to raw WHOIS that doesn't require a whois binary.

Input:  maltego.Domain
Output: maltego.Person (registrant), maltego.Organization, maltego.EmailAddress,
        maltego.PhoneNumber, maltego.Alias (nameservers)
"""

from __future__ import annotations

import httpx

import transforms as registry
from models.maltego import MaltegoEntity, TransformRequest, TransformResponse
from .base import BaseTransform, TransformMeta

_RDAP_URL = "https://rdap.org/domain/{domain}"


@registry.register
class DomainToWhois(BaseTransform):
    name = "DomainToWhois"
    meta = TransformMeta(
        name="DomainToWhois",
        display_name="Domain To WHOIS (RDAP)",
        description="Returns WHOIS / RDAP registration data for a domain.",
        input_entity="maltego.Domain",
        output_entities=["maltego.Person", "maltego.Organization", "maltego.EmailAddress",
                         "maltego.PhoneNumber", "maltego.Domain"],
    )

    def run(self, entity: MaltegoEntity, request: TransformRequest) -> TransformResponse:
        domain = entity.value.strip().lower()
        response = TransformResponse()

        try:
            resp = httpx.get(_RDAP_URL.format(domain=domain), timeout=10, follow_redirects=True)
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPStatusError as exc:
            return response.error(f"RDAP lookup failed ({exc.response.status_code}): {exc}")
        except Exception as exc:
            return response.error(f"RDAP request error: {exc}")

        # ── Nameservers ──────────────────────────────────────────────────────
        for ns in data.get("nameservers", []):
            ns_name = ns.get("ldhName", "").lower()
            if ns_name:
                ns_entity = MaltegoEntity(type="maltego.Domain", value=ns_name)
                ns_entity.add_field("fqdn", ns_name, "Nameserver FQDN")
                ns_entity.add_field("ns.for", domain, "Nameserver For")
                response.add_entity(ns_entity)

        # ── Entities (registrant, tech, admin contacts) ──────────────────────
        for rdap_entity in data.get("entities", []):
            roles = rdap_entity.get("roles", [])
            vcard = rdap_entity.get("vcardArray", [None, []])[1]

            name = ""
            email = ""
            phone = ""
            org = ""

            for prop in vcard:
                if not isinstance(prop, list) or len(prop) < 4:
                    continue
                pname, _, ptype, pvalue = prop[0], prop[1], prop[2], prop[3]
                if pname == "fn":
                    name = pvalue
                elif pname == "email":
                    email = pvalue if isinstance(pvalue, str) else ""
                elif pname == "tel":
                    phone = pvalue if isinstance(pvalue, str) else ""
                elif pname == "org":
                    org = pvalue if isinstance(pvalue, str) else ""

            role_str = ", ".join(roles)

            if org:
                o = MaltegoEntity(type="maltego.Organization", value=org)
                o.add_field("organization.name", org, "Organisation")
                o.add_field("whois.role", role_str, "WHOIS Role")
                response.add_entity(o)

            if name and not name == org:
                p = MaltegoEntity(type="maltego.Person", value=name)
                p.add_field("person.fullname", name, "Full Name")
                p.add_field("whois.role", role_str, "WHOIS Role")
                response.add_entity(p)

            if email:
                e = MaltegoEntity(type="maltego.EmailAddress", value=email)
                e.add_field("email.address", email, "Email Address")
                e.add_field("whois.role", role_str, "WHOIS Role")
                response.add_entity(e)

            if phone:
                ph = MaltegoEntity(type="maltego.PhoneNumber", value=phone)
                ph.add_field("phonenumber", phone, "Phone Number")
                response.add_entity(ph)

        response.inform(f"RDAP data retrieved for {domain}")
        return response
