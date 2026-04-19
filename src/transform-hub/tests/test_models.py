"""
Tests for Maltego XML / JSON model parsing and serialisation.
"""
from __future__ import annotations

import json

import pytest
from lxml import etree

from ..models.maltego import (
    EntityField,
    MaltegoEntity,
    TransformLimits,
    TransformRequest,
    TransformResponse,
    UIMessageType,
)


# ── MaltegoEntity ──────────────────────────────────────────────────────────────

class TestMaltegoEntity:
    def test_basic_fields(self):
        e = MaltegoEntity(type="maltego.Domain", value="example.com")
        assert e.type == "maltego.Domain"
        assert e.value == "example.com"
        assert e.weight == 100
        assert e.fields == []

    def test_add_field(self):
        e = MaltegoEntity(type="maltego.Domain", value="example.com")
        e.add_field("fqdn", "example.com", "FQDN")
        assert len(e.fields) == 1
        assert e.fields[0].name == "fqdn"
        assert e.fields[0].value == "example.com"
        assert e.fields[0].display_name == "FQDN"

    def test_to_xml_element_no_fields(self):
        e = MaltegoEntity(type="maltego.IPv4Address", value="1.2.3.4")
        el = e.to_xml_element()
        assert el.tag == "Entity"
        assert el.get("Type") == "maltego.IPv4Address"
        assert el.find("Value").text == "1.2.3.4"

    def test_to_xml_element_with_fields(self):
        e = MaltegoEntity(type="maltego.Domain", value="example.com")
        e.add_field("ip", "1.2.3.4", "IP Address")
        el = e.to_xml_element()
        fields = el.findall(".//Field")
        assert len(fields) == 1
        assert fields[0].get("Name") == "ip"
        assert fields[0].text == "1.2.3.4"


# ── TransformRequest XML parsing ───────────────────────────────────────────────

SIMPLE_XML = b"""<?xml version="1.0"?>
<MaltegoMessage>
  <MaltegoTransformRequestMessage>
    <Entities>
      <Entity Type="maltego.Domain">
        <Value>example.com</Value>
        <Weight>100</Weight>
        <AdditionalFields>
          <Field Name="fqdn" DisplayName="FQDN">example.com</Field>
        </AdditionalFields>
      </Entity>
    </Entities>
    <Limits SoftLimit="12" HardLimit="255"/>
  </MaltegoTransformRequestMessage>
</MaltegoMessage>"""


class TestTransformRequestXML:
    def test_parse_entity(self):
        req = TransformRequest.from_xml(SIMPLE_XML)
        assert len(req.entities) == 1
        assert req.entities[0].type == "maltego.Domain"
        assert req.entities[0].value == "example.com"

    def test_parse_limits(self):
        req = TransformRequest.from_xml(SIMPLE_XML)
        assert req.limits.soft_limit == 12
        assert req.limits.hard_limit == 255

    def test_parse_additional_fields(self):
        req = TransformRequest.from_xml(SIMPLE_XML)
        assert len(req.entities[0].fields) == 1
        assert req.entities[0].fields[0].name == "fqdn"

    def test_missing_limits_defaults(self):
        xml = b"""<MaltegoMessage><MaltegoTransformRequestMessage>
          <Entities><Entity Type="maltego.Domain"><Value>x.com</Value></Entity></Entities>
        </MaltegoTransformRequestMessage></MaltegoMessage>"""
        req = TransformRequest.from_xml(xml)
        assert req.limits.soft_limit == 12

    def test_malformed_xml_raises(self):
        with pytest.raises(Exception):
            TransformRequest.from_xml(b"not xml")


# ── TransformRequest JSON parsing ──────────────────────────────────────────────

SIMPLE_JSON = {
    "Entities": {
        "Entity": [
            {
                "Type": "maltego.Domain",
                "Value": "example.com",
                "Weight": 100,
                "AdditionalFields": {"Field": []},
            }
        ]
    },
    "Limits": {"SoftLimit": "6", "HardLimit": "100"},
}


class TestTransformRequestJSON:
    def test_parse_entity(self):
        req = TransformRequest.from_json(SIMPLE_JSON)
        assert req.entities[0].type == "maltego.Domain"
        assert req.entities[0].value == "example.com"

    def test_parse_limits(self):
        req = TransformRequest.from_json(SIMPLE_JSON)
        assert req.limits.soft_limit == 6
        assert req.limits.hard_limit == 100

    def test_empty_entities(self):
        req = TransformRequest.from_json({"Entities": {"Entity": []}, "Limits": {}})
        assert req.entities == []


# ── TransformResponse serialisation ───────────────────────────────────────────

class TestTransformResponse:
    def _make_response(self):
        resp = TransformResponse()
        entity = MaltegoEntity(type="maltego.IPv4Address", value="1.2.3.4")
        resp.add_entity(entity)
        resp.inform("Found 1 IP")
        return resp

    def test_to_xml_roundtrip(self):
        resp = self._make_response()
        xml_bytes = resp.to_xml()
        root = etree.fromstring(xml_bytes)
        entities = root.findall(".//Entity")
        assert len(entities) == 1
        assert entities[0].get("Type") == "maltego.IPv4Address"
        assert entities[0].find("Value").text == "1.2.3.4"

    def test_to_xml_ui_message(self):
        resp = self._make_response()
        xml_bytes = resp.to_xml()
        root = etree.fromstring(xml_bytes)
        msgs = root.findall(".//UIMessage")
        assert any(m.get("MessageType") == "Inform" for m in msgs)

    def test_to_dict_structure(self):
        resp = self._make_response()
        d = resp.to_dict()
        entities = d["MaltegoTransformResponseMessage"]["Entities"]["Entity"]
        assert len(entities) == 1
        assert entities[0]["Value"] == "1.2.3.4"

    def test_error_response(self):
        resp = TransformResponse().error("Something failed", fatal=True)
        assert any(m.type == UIMessageType.FATAL_ERROR for m in resp.ui_messages)

    def test_partial_error(self):
        resp = TransformResponse().error("Partial", fatal=False)
        assert any(m.type == UIMessageType.PARTIAL_ERROR for m in resp.ui_messages)

    def test_xml_is_bytes(self):
        resp = TransformResponse()
        assert isinstance(resp.to_xml(), bytes)

    def test_empty_response_xml(self):
        resp = TransformResponse()
        xml = resp.to_xml()
        root = etree.fromstring(xml)
        assert root.find(".//Entities") is not None
