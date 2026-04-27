"""
BaseTransform — the contract every transform must implement.

To add a new transform:
  1. Create a new .py file in this package.
  2. Define a class that inherits from BaseTransform.
  3. Decorate it with @register.
  4. Implement run().

The autodiscovery in __init__.py will pick it up on startup.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from models.maltego import MaltegoEntity, TransformRequest, TransformResponse


@dataclass
class TransformMeta:
    """Metadata surfaced in the /manifest endpoint (iTDS replacement)."""
    name: str
    display_name: str
    description: str
    author: str = "Platform Team"
    input_entity: str = "maltego.Unknown"
    output_entities: list[str] = field(default_factory=list)
    ui_name: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "displayName": self.display_name or self.name,
            "description": self.description,
            "author": self.author,
            "inputEntity": self.input_entity,
            "outputEntities": self.output_entities,
            "uiName": self.ui_name or self.display_name or self.name,
        }


class BaseTransform(ABC):
    """Abstract base — subclass and implement run()."""

    # Class-level metadata — set these in every subclass
    name: str = ""
    meta: TransformMeta = TransformMeta(name="", display_name="", description="")

    @abstractmethod
    def run(self, entity: MaltegoEntity, request: TransformRequest) -> TransformResponse:
        """
        Execute the transform for a single input entity.

        Args:
            entity:  The first (or primary) input entity.
            request: Full request object; use request.limits, request.transform_fields, etc.

        Returns:
            A TransformResponse containing result entities and optional UI messages.
        """

    def execute(self, request: TransformRequest) -> TransformResponse:
        """Entry-point called by the router — handles multi-entity requests."""
        if not request.entities:
            return TransformResponse().error("No input entities provided.", fatal=True)

        # Process the first entity (standard Maltego single-entity pattern).
        # Override this method if your transform needs to handle all entities.
        return self.run(request.entities[0], request)
