"""
Transform registry.

Every module in this package that defines a class inheriting from
BaseTransform is automatically discovered and registered.
"""

from __future__ import annotations

import importlib
import pkgutil
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .base import BaseTransform

_registry: dict[str, type["BaseTransform"]] = {}


def register(cls: type["BaseTransform"]) -> type["BaseTransform"]:
    """Class decorator — adds the transform to the global registry."""
    _registry[cls.name] = cls
    return cls


def get_transform(name: str) -> type["BaseTransform"] | None:
    return _registry.get(name)


def all_transforms() -> dict[str, type["BaseTransform"]]:
    return dict(_registry)


def _autodiscover() -> None:
    """Import every module in this package so decorators fire."""
    pkg_path = str(Path(__file__).parent)
    for _, module_name, _ in pkgutil.iter_modules([pkg_path]):
        if module_name not in ("__init__", "base"):
            importlib.import_module(f".{module_name}", package=__name__)


_autodiscover()
