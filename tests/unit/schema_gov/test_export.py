"""Unit tests for export_schemas -- standalone, no prisma-domain models."""
from enum import Enum

from pydantic import BaseModel

from prisma.schema_gov import TypeRegistry, export_schemas


class Kind(str, Enum):
    widget = "widget"


class Widget(BaseModel):
    name: str


class SubDoc(BaseModel):
    detail: str


def test_export_schemas_covers_every_registered_type():
    r: TypeRegistry = TypeRegistry()
    r.register(Kind.widget, Widget)
    schemas = export_schemas(r)
    assert schemas["Kind.widget"]["title"] == "Widget"


def test_export_schemas_includes_extra_sub_document_models():
    r: TypeRegistry = TypeRegistry()
    schemas = export_schemas(r, extra={"sub-doc": SubDoc})
    assert schemas["sub-doc"]["title"] == "SubDoc"
