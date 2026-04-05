"""
IP Address → GeoLocation transform.

Uses the free ip-api.com JSON endpoint (no key required for <45 req/min).
For production, set transform_field api_provider=ipinfo and supply an API key.

Input:  maltego.IPv4Address
Output: maltego.Location, maltego.AS (autonomous system), maltego.Organization
"""

from __future__ import annotations

import httpx

from .. import transforms as registry
from ..models.maltego import MaltegoEntity, TransformRequest, TransformResponse
from .base import BaseTransform, TransformMeta

_IP_API = "http://ip-api.com/json/{ip}?fields=status,message,country,countryCode,region,regionName,city,zip,lat,lon,timezone,isp,org,as,query"


@registry.register
class IPToGeoLocation(BaseTransform):
    name = "IPToGeoLocation"
    meta = TransformMeta(
        name="IPToGeoLocation",
        display_name="IP To GeoLocation",
        description="Returns geographic and ASN information for an IPv4 address.",
        input_entity="maltego.IPv4Address",
        output_entities=["maltego.Location", "maltego.AS", "maltego.Organization"],
    )

    def run(self, entity: MaltegoEntity, request: TransformRequest) -> TransformResponse:
        ip = entity.value.strip()
        response = TransformResponse()

        try:
            data = httpx.get(_IP_API.format(ip=ip), timeout=8).json()
        except Exception as exc:
            return response.error(f"GeoIP lookup failed: {exc}")

        if data.get("status") != "success":
            return response.error(f"ip-api.com returned: {data.get('message', 'unknown error')}")

        # Location entity
        city = data.get("city", "")
        country = data.get("country", "")
        location_val = f"{city}, {country}".strip(", ")
        if location_val:
            loc = MaltegoEntity(type="maltego.Location", value=location_val)
            loc.add_field("location.city", city, "City")
            loc.add_field("location.country", country, "Country")
            loc.add_field("location.countrycode", data.get("countryCode", ""), "Country Code")
            loc.add_field("location.region", data.get("regionName", ""), "Region")
            loc.add_field("location.zipcode", data.get("zip", ""), "ZIP/Postal Code")
            loc.add_field("location.latitude", str(data.get("lat", "")), "Latitude")
            loc.add_field("location.longitude", str(data.get("lon", "")), "Longitude")
            loc.add_field("location.timezone", data.get("timezone", ""), "Timezone")
            response.add_entity(loc)

        # ASN entity
        asn_raw = data.get("as", "")
        if asn_raw:
            asn_entity = MaltegoEntity(type="maltego.AS", value=asn_raw)
            asn_entity.add_field("as.number", asn_raw.split(" ")[0] if " " in asn_raw else asn_raw, "AS Number")
            asn_entity.add_field("as.name", data.get("isp", ""), "ISP")
            response.add_entity(asn_entity)

        # Organisation entity
        org = data.get("org", "")
        if org:
            org_entity = MaltegoEntity(type="maltego.Organization", value=org)
            org_entity.add_field("organization.name", org, "Organisation Name")
            org_entity.add_field("ipaddress", ip, "IP Address")
            response.add_entity(org_entity)

        response.inform(f"GeoIP data retrieved for {ip}")
        return response
