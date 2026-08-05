"""JSON Schema export, operating on any TypeRegistry instance."""
from __future__ import annotations

from typing import Mapping

from pydantic import BaseModel

from .registry import TypeRegistry

__all__ = ["export_schemas"]


def export_schemas(
    registry: TypeRegistry, *, extra: Mapping[str, type[BaseModel]] | None = None
) -> dict[str, dict]:
    """name -> JSON Schema for every type in `registry`, plus any `extra`
    sub-document models a caller wants included (e.g. models that aren't
    keyed in the registry itself, like a footnote or tool-call sub-type)."""
    schemas = registry.all_schemas()
    if extra:
        for name, cls in extra.items():
            schemas[name] = cls.model_json_schema()
    return schemas
