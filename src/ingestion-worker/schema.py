"""
Entity mapping schema.

Defines how each Maltego entity type maps to:
  - An OpenSearch index with explicit field mappings
  - A Neo4j node label with property definitions
  - Relationships inferred from (transform_name, input_type, output_type)

Adding a new entity type
────────────────────────
1. Add an EntityMapping to ENTITY_SCHEMA.
2. If the producing transform creates a graph relationship, add a row to
   RELATIONSHIP_SCHEMA keyed by (transform_name, input_entity_type, output_entity_type).

That's all. The ingestion worker reads this schema at startup — no code changes needed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


# ── Field type aliases (OpenSearch mapping types) ─────────────────────────────

OSFieldType = Literal[
    "keyword", "text", "ip", "integer", "long", "float",
    "boolean", "date", "geo_point", "object",
]


@dataclass
class OSField:
    type: OSFieldType
    analyzer: str | None = None       # for "text" fields only
    index: bool = True                 # False = stored but not indexed


@dataclass
class Neo4jProperty:
    name: str                          # property key in Neo4j
    source_field: str                  # field name in the entity event
    required: bool = True


@dataclass
class EntityMapping:
    # ── OpenSearch ────────────────────────────────────────────────────────────
    opensearch_index: str              # e.g. "entities-domain"
    opensearch_fields: dict[str, OSField] = field(default_factory=dict)

    # ── Neo4j ─────────────────────────────────────────────────────────────────
    neo4j_label: str = ""              # Node label, e.g. "Domain"
    neo4j_id_property: str = "value"   # property used as merge key (MERGE ON)
    neo4j_properties: list[Neo4jProperty] = field(default_factory=list)


@dataclass
class RelationshipMapping:
    rel_type: str                      # Cypher relationship type, e.g. "RESOLVES_TO"
    source_label: str                  # Neo4j label of the input entity
    target_label: str                  # Neo4j label of the output entity
    # Optional extra properties to set on the relationship
    properties: dict[str, str] = field(default_factory=dict)


# ── Entity schema ─────────────────────────────────────────────────────────────
# Keys are Maltego entity type strings (e.g. "maltego.Domain").

ENTITY_SCHEMA: dict[str, EntityMapping] = {
    "maltego.Domain": EntityMapping(
        opensearch_index="entities-domain",
        opensearch_fields={
            "value":       OSField("keyword"),
            "fqdn":        OSField("keyword"),
            "whois_registrar": OSField("keyword"),
            "whois_created": OSField("date"),
            "sources":     OSField("keyword"),
            "first_seen":  OSField("date"),
            "last_seen":   OSField("date"),
            "tags":        OSField("keyword"),
        },
        neo4j_label="Domain",
        neo4j_id_property="value",
        neo4j_properties=[
            Neo4jProperty("value",   "value"),
            Neo4jProperty("fqdn",    "value", required=False),
        ],
    ),

    "maltego.IPv4Address": EntityMapping(
        opensearch_index="entities-ip",
        opensearch_fields={
            "value":       OSField("ip"),
            "asn":         OSField("keyword"),
            "asn_org":     OSField("keyword"),
            "country":     OSField("keyword"),
            "city":        OSField("keyword"),
            "location":    OSField("geo_point"),
            "sources":     OSField("keyword"),
            "first_seen":  OSField("date"),
            "last_seen":   OSField("date"),
            "tags":        OSField("keyword"),
        },
        neo4j_label="IPAddress",
        neo4j_id_property="value",
        neo4j_properties=[
            Neo4jProperty("value",   "value"),
            Neo4jProperty("asn",     "asn",     required=False),
            Neo4jProperty("country", "country", required=False),
        ],
    ),

    "maltego.MXRecord": EntityMapping(
        opensearch_index="entities-mx",
        opensearch_fields={
            "value":       OSField("keyword"),
            "priority":    OSField("integer"),
            "sources":     OSField("keyword"),
            "first_seen":  OSField("date"),
            "last_seen":   OSField("date"),
        },
        neo4j_label="MXRecord",
        neo4j_id_property="value",
        neo4j_properties=[
            Neo4jProperty("value",    "value"),
            Neo4jProperty("priority", "mxrecord.priority", required=False),
        ],
    ),

    "maltego.URL": EntityMapping(
        opensearch_index="entities-url",
        opensearch_fields={
            "value":       OSField("keyword"),
            "url":         OSField("keyword"),
            "scheme":      OSField("keyword"),
            "path":        OSField("text", analyzer="standard"),
            "sources":     OSField("keyword"),
            "first_seen":  OSField("date"),
            "last_seen":   OSField("date"),
        },
        neo4j_label="URL",
        neo4j_id_property="value",
        neo4j_properties=[
            Neo4jProperty("value", "value"),
        ],
    ),

    "maltego.Person": EntityMapping(
        opensearch_index="entities-person",
        opensearch_fields={
            "value":       OSField("text", analyzer="standard"),
            "firstname":   OSField("keyword"),
            "lastname":    OSField("keyword"),
            "email":       OSField("keyword"),
            "sources":     OSField("keyword"),
            "first_seen":  OSField("date"),
            "last_seen":   OSField("date"),
        },
        neo4j_label="Person",
        neo4j_id_property="value",
        neo4j_properties=[
            Neo4jProperty("value",     "value"),
            Neo4jProperty("firstname", "person.firstname", required=False),
            Neo4jProperty("lastname",  "person.lastname",  required=False),
        ],
    ),

    "maltego.EmailAddress": EntityMapping(
        opensearch_index="entities-email",
        opensearch_fields={
            "value":       OSField("keyword"),
            "domain":      OSField("keyword"),
            "sources":     OSField("keyword"),
            "first_seen":  OSField("date"),
            "last_seen":   OSField("date"),
        },
        neo4j_label="EmailAddress",
        neo4j_id_property="value",
        neo4j_properties=[
            Neo4jProperty("value",  "value"),
            Neo4jProperty("domain", "domain", required=False),
        ],
    ),

    "maltego.PhoneNumber": EntityMapping(
        opensearch_index="entities-phone",
        opensearch_fields={
            "value":       OSField("keyword"),
            "country":     OSField("keyword"),
            "sources":     OSField("keyword"),
            "first_seen":  OSField("date"),
            "last_seen":   OSField("date"),
        },
        neo4j_label="PhoneNumber",
        neo4j_id_property="value",
        neo4j_properties=[
            Neo4jProperty("value", "value"),
        ],
    ),

    "maltego.Organization": EntityMapping(
        opensearch_index="entities-organization",
        opensearch_fields={
            "value":       OSField("text", analyzer="standard"),
            "name":        OSField("keyword"),
            "country":     OSField("keyword"),
            "sources":     OSField("keyword"),
            "first_seen":  OSField("date"),
            "last_seen":   OSField("date"),
        },
        neo4j_label="Organization",
        neo4j_id_property="value",
        neo4j_properties=[
            Neo4jProperty("value", "value"),
        ],
    ),

    "maltego.Location": EntityMapping(
        opensearch_index="entities-location",
        opensearch_fields={
            "value":          OSField("keyword"),
            "country_name":   OSField("keyword"),
            "country_code":   OSField("keyword"),
            "city":           OSField("keyword"),
            "area":           OSField("keyword"),
            "location":       OSField("geo_point"),
            "latitude":       OSField("float"),
            "longitude":      OSField("float"),
            "sources":        OSField("keyword"),
            "first_seen":     OSField("date"),
            "last_seen":      OSField("date"),
        },
        neo4j_label="Location",
        neo4j_id_property="value",
        neo4j_properties=[
            Neo4jProperty("value",        "value"),
            Neo4jProperty("country_code", "location.country_code", required=False),
            Neo4jProperty("city",         "location.city",         required=False),
        ],
    ),

    "maltego.AS": EntityMapping(
        opensearch_index="entities-asn",
        opensearch_fields={
            "value":       OSField("keyword"),
            "asn":         OSField("keyword"),
            "org":         OSField("keyword"),
            "sources":     OSField("keyword"),
            "first_seen":  OSField("date"),
            "last_seen":   OSField("date"),
        },
        neo4j_label="AutonomousSystem",
        neo4j_id_property="value",
        neo4j_properties=[
            Neo4jProperty("value", "value"),
            Neo4jProperty("asn",   "asn.number", required=False),
        ],
    ),
}


# ── Relationship schema ───────────────────────────────────────────────────────
# Key: (transform_name, input_entity_type, output_entity_type)
# Value: RelationshipMapping describing the graph edge to create.
#
# When a transform execution event arrives, the ingestion worker looks up
# each (transform, input_type, output_type) triple to determine what
# relationships to create between existing/merged nodes.

RELATIONSHIP_SCHEMA: dict[tuple[str, str, str], RelationshipMapping] = {
    # DNS / network
    ("DomainToIP", "maltego.Domain", "maltego.IPv4Address"): RelationshipMapping(
        rel_type="RESOLVES_TO",
        source_label="Domain",
        target_label="IPAddress",
    ),
    ("DomainToMX", "maltego.Domain", "maltego.MXRecord"): RelationshipMapping(
        rel_type="HAS_MX",
        source_label="Domain",
        target_label="MXRecord",
    ),
    ("DomainToMXRecord", "maltego.Domain", "maltego.MXRecord"): RelationshipMapping(
        rel_type="HAS_MX",
        source_label="Domain",
        target_label="MXRecord",
    ),
    ("URLToDomain", "maltego.URL", "maltego.Domain"): RelationshipMapping(
        rel_type="HOSTED_ON",
        source_label="URL",
        target_label="Domain",
    ),
    ("URLToDomain", "maltego.URL", "maltego.IPv4Address"): RelationshipMapping(
        rel_type="RESOLVES_TO",
        source_label="URL",
        target_label="IPAddress",
    ),

    # WHOIS / identity
    ("DomainToWHOIS", "maltego.Domain", "maltego.Person"): RelationshipMapping(
        rel_type="REGISTERED_BY",
        source_label="Domain",
        target_label="Person",
    ),
    ("DomainToWHOIS", "maltego.Domain", "maltego.Organization"): RelationshipMapping(
        rel_type="REGISTERED_BY",
        source_label="Domain",
        target_label="Organization",
    ),
    ("DomainToWHOIS", "maltego.Domain", "maltego.EmailAddress"): RelationshipMapping(
        rel_type="CONTACT_EMAIL",
        source_label="Domain",
        target_label="EmailAddress",
    ),
    ("DomainToWHOIS", "maltego.Domain", "maltego.PhoneNumber"): RelationshipMapping(
        rel_type="CONTACT_PHONE",
        source_label="Domain",
        target_label="PhoneNumber",
    ),

    # Geolocation
    ("IPToGeolocation", "maltego.IPv4Address", "maltego.Location"): RelationshipMapping(
        rel_type="GEOLOCATED_IN",
        source_label="IPAddress",
        target_label="Location",
    ),
    ("IPToGeolocation", "maltego.IPv4Address", "maltego.AS"): RelationshipMapping(
        rel_type="BELONGS_TO_ASN",
        source_label="IPAddress",
        target_label="AutonomousSystem",
    ),
    ("IPToGeolocation", "maltego.IPv4Address", "maltego.Organization"): RelationshipMapping(
        rel_type="OPERATED_BY",
        source_label="IPAddress",
        target_label="Organization",
    ),
}


# ── Index template helpers ────────────────────────────────────────────────────

def opensearch_index_mapping(entity_type: str) -> dict:
    """Return an OpenSearch PUT /<index>/_mapping body for an entity type."""
    mapping = ENTITY_SCHEMA.get(entity_type)
    if not mapping:
        # Fallback: dynamic mapping for unknown entity types
        return {
            "mappings": {
                "dynamic": True,
                "properties": {
                    "value":      {"type": "keyword"},
                    "entity_type": {"type": "keyword"},
                    "sources":    {"type": "keyword"},
                    "first_seen": {"type": "date"},
                    "last_seen":  {"type": "date"},
                },
            }
        }

    properties: dict = {
        "entity_type": {"type": "keyword"},
        "ingested_at": {"type": "date"},
    }
    for fname, fdef in mapping.opensearch_fields.items():
        prop: dict = {"type": fdef.type}
        if fdef.analyzer:
            prop["analyzer"] = fdef.analyzer
        if not fdef.index:
            prop["index"] = False
        properties[fname] = prop

    return {
        "mappings": {
            "dynamic": False,   # reject unknown fields; schema is the contract
            "properties": properties,
        }
    }


def get_entity_mapping(entity_type: str) -> EntityMapping | None:
    return ENTITY_SCHEMA.get(entity_type)


def get_relationship_mapping(
    transform_name: str,
    input_type: str,
    output_type: str,
) -> RelationshipMapping | None:
    return RELATIONSHIP_SCHEMA.get((transform_name, input_type, output_type))
