"""
Tests for the entity mapping schema.

Verifies that lookups, index mapping generation, and relationship resolution
work correctly for all defined entity and relationship types.
"""
from __future__ import annotations

import pytest

from ..schema import (
    ENTITY_SCHEMA,
    RELATIONSHIP_SCHEMA,
    get_entity_mapping,
    get_relationship_mapping,
    opensearch_index_mapping,
)


# ── Entity schema coverage ─────────────────────────────────────────────────────

class TestEntitySchema:
    EXPECTED_TYPES = [
        "maltego.Domain",
        "maltego.IPv4Address",
        "maltego.MXRecord",
        "maltego.URL",
        "maltego.Person",
        "maltego.EmailAddress",
        "maltego.PhoneNumber",
        "maltego.Organization",
        "maltego.Location",
        "maltego.AS",
    ]

    def test_all_expected_types_present(self):
        for t in self.EXPECTED_TYPES:
            assert t in ENTITY_SCHEMA, f"Missing entity type: {t}"

    def test_every_mapping_has_opensearch_index(self):
        for entity_type, mapping in ENTITY_SCHEMA.items():
            assert mapping.opensearch_index, f"{entity_type}: opensearch_index is empty"
            assert mapping.opensearch_index.startswith("entities-"), \
                f"{entity_type}: index name should start with 'entities-'"

    def test_every_mapping_has_neo4j_label(self):
        for entity_type, mapping in ENTITY_SCHEMA.items():
            assert mapping.neo4j_label, f"{entity_type}: neo4j_label is empty"

    def test_every_mapping_has_neo4j_id_property(self):
        for entity_type, mapping in ENTITY_SCHEMA.items():
            assert mapping.neo4j_id_property, f"{entity_type}: neo4j_id_property is empty"

    def test_every_mapping_has_at_least_one_opensearch_field(self):
        for entity_type, mapping in ENTITY_SCHEMA.items():
            assert len(mapping.opensearch_fields) > 0, \
                f"{entity_type}: no opensearch_fields defined"

    def test_all_mappings_have_value_field(self):
        for entity_type, mapping in ENTITY_SCHEMA.items():
            assert "value" in mapping.opensearch_fields, \
                f"{entity_type}: missing 'value' field in opensearch_fields"

    def test_all_mappings_have_first_seen_last_seen(self):
        for entity_type, mapping in ENTITY_SCHEMA.items():
            assert "first_seen" in mapping.opensearch_fields, \
                f"{entity_type}: missing 'first_seen'"
            assert "last_seen" in mapping.opensearch_fields, \
                f"{entity_type}: missing 'last_seen'"


# ── get_entity_mapping ─────────────────────────────────────────────────────────

class TestGetEntityMapping:
    def test_known_type_returns_mapping(self):
        m = get_entity_mapping("maltego.Domain")
        assert m is not None
        assert m.neo4j_label == "Domain"
        assert m.opensearch_index == "entities-domain"

    def test_unknown_type_returns_none(self):
        assert get_entity_mapping("maltego.Nonexistent") is None

    def test_ip_mapping(self):
        m = get_entity_mapping("maltego.IPv4Address")
        assert m is not None
        assert m.neo4j_label == "IPAddress"
        # IP field should have type "ip" in OpenSearch
        assert m.opensearch_fields["value"].type == "ip"

    def test_location_has_geo_point(self):
        m = get_entity_mapping("maltego.Location")
        assert m is not None
        assert "location" in m.opensearch_fields
        assert m.opensearch_fields["location"].type == "geo_point"


# ── Relationship schema ────────────────────────────────────────────────────────

class TestRelationshipSchema:
    EXPECTED_RELATIONSHIPS = [
        ("DomainToIP", "maltego.Domain", "maltego.IPv4Address"),
        ("DomainToWHOIS", "maltego.Domain", "maltego.Person"),
        ("DomainToWHOIS", "maltego.Domain", "maltego.EmailAddress"),
        ("IPToGeolocation", "maltego.IPv4Address", "maltego.Location"),
        ("IPToGeolocation", "maltego.IPv4Address", "maltego.AS"),
        ("URLToDomain", "maltego.URL", "maltego.Domain"),
    ]

    def test_expected_relationships_present(self):
        for key in self.EXPECTED_RELATIONSHIPS:
            assert key in RELATIONSHIP_SCHEMA, f"Missing relationship: {key}"

    def test_relationship_has_rel_type(self):
        for key, rel in RELATIONSHIP_SCHEMA.items():
            assert rel.rel_type, f"{key}: rel_type is empty"
            # Relationship types should be UPPER_SNAKE_CASE
            assert rel.rel_type == rel.rel_type.upper(), \
                f"{key}: rel_type '{rel.rel_type}' should be uppercase"

    def test_relationship_has_source_and_target_labels(self):
        for key, rel in RELATIONSHIP_SCHEMA.items():
            assert rel.source_label, f"{key}: source_label is empty"
            assert rel.target_label, f"{key}: target_label is empty"


class TestGetRelationshipMapping:
    def test_known_triple_returns_mapping(self):
        rel = get_relationship_mapping("DomainToIP", "maltego.Domain", "maltego.IPv4Address")
        assert rel is not None
        assert rel.rel_type == "RESOLVES_TO"

    def test_unknown_triple_returns_none(self):
        rel = get_relationship_mapping("FakeTransform", "maltego.Foo", "maltego.Bar")
        assert rel is None

    def test_whois_domain_to_person(self):
        rel = get_relationship_mapping("DomainToWHOIS", "maltego.Domain", "maltego.Person")
        assert rel is not None
        assert rel.rel_type == "REGISTERED_BY"

    def test_ip_to_location(self):
        rel = get_relationship_mapping("IPToGeolocation", "maltego.IPv4Address", "maltego.Location")
        assert rel is not None
        assert rel.rel_type == "GEOLOCATED_IN"

    def test_wrong_transform_name_returns_none(self):
        # Same types, different transform — no mapping
        rel = get_relationship_mapping("WrongTransform", "maltego.Domain", "maltego.IPv4Address")
        assert rel is None


# ── opensearch_index_mapping ───────────────────────────────────────────────────

class TestOpenSearchIndexMapping:
    def test_known_entity_returns_explicit_mapping(self):
        body = opensearch_index_mapping("maltego.Domain")
        assert "mappings" in body
        props = body["mappings"]["properties"]
        assert "value" in props
        assert props["value"]["type"] == "keyword"

    def test_dynamic_is_false_for_known_types(self):
        body = opensearch_index_mapping("maltego.Domain")
        assert body["mappings"]["dynamic"] is False

    def test_unknown_entity_returns_fallback_mapping(self):
        body = opensearch_index_mapping("maltego.Unknown")
        assert "mappings" in body
        # Fallback should have dynamic: True
        assert body["mappings"]["dynamic"] is True

    def test_always_has_entity_type_field(self):
        body = opensearch_index_mapping("maltego.Domain")
        props = body["mappings"]["properties"]
        assert "entity_type" in props
        assert props["entity_type"]["type"] == "keyword"

    def test_ip_field_type(self):
        body = opensearch_index_mapping("maltego.IPv4Address")
        props = body["mappings"]["properties"]
        assert props["value"]["type"] == "ip"

    def test_date_fields_have_date_type(self):
        body = opensearch_index_mapping("maltego.Domain")
        props = body["mappings"]["properties"]
        assert props["first_seen"]["type"] == "date"
        assert props["last_seen"]["type"] == "date"
