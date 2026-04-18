"""
Maltego transform request / response data models.

Supports both the classic XML envelope (TRX v2) and the newer JSON REST
format that Maltego clients use when connecting to an external transform server.

XML format reference:
  https://docs.maltego.com/support/solutions/articles/15000010781

JSON format mirrors the same structure but is easier to consume from modern
clients and simpler to test with curl.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from lxml import etree
from pydantic import BaseModel, Field


# ── Entity field ──────────────────────────────────────────────────────────────

class EntityField(BaseModel):
    name: str
    display_name: str = ""
    value: str = ""
    matching_rule: str = "strict"


class MaltegoEntity(BaseModel):
    type: str                                 # e.g. "maltego.Domain"
    value: str
    weight: int = 100
    fields: list[EntityField] = Field(default_factory=list)
    icon_url: str = ""
    display_information: list[dict[str, str]] = Field(default_factory=list)
    bookmark: int = -1                        # -1 = none, 0-7 = bookmark colour

    def add_field(self, name: str, value: str, display_name: str = "") -> "MaltegoEntity":
        self.fields.append(EntityField(
            name=name,
            display_name=display_name or name,
            value=value,
        ))
        return self

    # ── XML serialisation ─────────────────────────────────────────────────────
    def to_xml_element(self) -> etree._Element:
        el = etree.Element("Entity", Type=self.type)
        etree.SubElement(el, "Value").text = self.value
        etree.SubElement(el, "Weight").text = str(self.weight)
        if self.fields:
            af = etree.SubElement(el, "AdditionalFields")
            for f in self.fields:
                field_el = etree.SubElement(af, "Field", Name=f.name)
                field_el.set("DisplayName", f.display_name)
                field_el.text = f.value
        if self.icon_url:
            etree.SubElement(el, "IconURL").text = self.icon_url
        return el


# ── UI Message ────────────────────────────────────────────────────────────────

class UIMessageType(str, Enum):
    INFORM = "Inform"
    DEBUG = "Debug"
    PARTIAL_ERROR = "PartialError"
    FATAL_ERROR = "FatalError"


class UIMessage(BaseModel):
    type: UIMessageType = UIMessageType.INFORM
    text: str


# ── Transform request ─────────────────────────────────────────────────────────

class TransformLimits(BaseModel):
    soft_limit: int = 12
    hard_limit: int = 255


class TransformRequest(BaseModel):
    """Normalised transform request — populated from either XML or JSON body."""
    entities: list[MaltegoEntity]
    limits: TransformLimits = Field(default_factory=TransformLimits)
    transform_fields: dict[str, str] = Field(default_factory=dict)

    @classmethod
    def from_xml(cls, body: bytes) -> "TransformRequest":
        root = etree.fromstring(body)
        ns = ""
        req_msg = root.find(f"{ns}MaltegoTransformRequestMessage")
        if req_msg is None:
            req_msg = root  # fallback: treat root as the message

        entities: list[MaltegoEntity] = []
        for ent in req_msg.findall(".//Entity"):
            value_el = ent.find("Value")
            entity = MaltegoEntity(
                type=ent.get("Type", "maltego.Unknown"),
                value=value_el.text if value_el is not None else "",
            )
            weight_el = ent.find("Weight")
            if weight_el is not None:
                try:
                    entity.weight = int(weight_el.text)
                except (TypeError, ValueError):
                    pass
            for field_el in ent.findall(".//Field"):
                entity.fields.append(EntityField(
                    name=field_el.get("Name", ""),
                    display_name=field_el.get("DisplayName", ""),
                    value=field_el.text or "",
                ))
            entities.append(entity)

        limits_el = req_msg.find(".//Limits")
        limits = TransformLimits()
        if limits_el is not None:
            limits.soft_limit = int(limits_el.get("SoftLimit", 12))
            limits.hard_limit = int(limits_el.get("HardLimit", 255))

        transform_fields: dict[str, str] = {}
        for tf in req_msg.findall(".//TransformFields/Field"):
            transform_fields[tf.get("Name", "")] = tf.text or ""

        return cls(entities=entities, limits=limits, transform_fields=transform_fields)

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "TransformRequest":
        entities = [
            MaltegoEntity(
                type=e.get("Type", "maltego.Unknown"),
                value=e.get("Value", ""),
                weight=e.get("Weight", 100),
                fields=[
                    EntityField(
                        name=f.get("Name", ""),
                        display_name=f.get("DisplayName", ""),
                        value=f.get("Value", ""),
                    )
                    for f in e.get("AdditionalFields", {}).get("Field", [])
                    if isinstance(f, dict)
                ],
            )
            for e in data.get("Entities", {}).get("Entity", [])
        ]
        lim = data.get("Limits", {})
        limits = TransformLimits(
            soft_limit=int(lim.get("SoftLimit", 12)),
            hard_limit=int(lim.get("HardLimit", 255)),
        )
        tf = {
            f.get("Name", ""): f.get("Value", "")
            for f in data.get("TransformFields", {}).get("Field", [])
            if isinstance(f, dict)
        }
        return cls(entities=entities, limits=limits, transform_fields=tf)


# ── Transform response ────────────────────────────────────────────────────────

class TransformResponse(BaseModel):
    entities: list[MaltegoEntity] = Field(default_factory=list)
    ui_messages: list[UIMessage] = Field(default_factory=list)

    def add_entity(self, entity: MaltegoEntity) -> "TransformResponse":
        self.entities.append(entity)
        return self

    def inform(self, text: str) -> "TransformResponse":
        self.ui_messages.append(UIMessage(type=UIMessageType.INFORM, text=text))
        return self

    def error(self, text: str, fatal: bool = False) -> "TransformResponse":
        msg_type = UIMessageType.FATAL_ERROR if fatal else UIMessageType.PARTIAL_ERROR
        self.ui_messages.append(UIMessage(type=msg_type, text=text))
        return self

    def to_xml(self) -> bytes:
        root = etree.Element("MaltegoMessage")
        resp = etree.SubElement(root, "MaltegoTransformResponseMessage")

        entities_el = etree.SubElement(resp, "Entities")
        for entity in self.entities:
            entities_el.append(entity.to_xml_element())

        if self.ui_messages:
            msgs_el = etree.SubElement(resp, "UIMessages")
            for msg in self.ui_messages:
                m_el = etree.SubElement(msgs_el, "UIMessage", MessageType=msg.type.value)
                m_el.text = msg.text

        return etree.tostring(root, xml_declaration=True, encoding="UTF-8", pretty_print=True)

    def to_dict(self) -> dict[str, Any]:
        return {
            "MaltegoTransformResponseMessage": {
                "Entities": {
                    "Entity": [
                        {
                            "Type": e.type,
                            "Value": e.value,
                            "Weight": e.weight,
                            "AdditionalFields": {
                                "Field": [
                                    {"Name": f.name, "DisplayName": f.display_name, "Value": f.value}
                                    for f in e.fields
                                ]
                            },
                        }
                        for e in self.entities
                    ]
                },
                "UIMessages": {
                    "UIMessage": [
                        {"MessageType": m.type.value, "Value": m.text}
                        for m in self.ui_messages
                    ]
                },
            }
        }
