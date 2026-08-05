"""Unit tests for TypeRegistry -- standalone, no prisma-domain models."""
from enum import Enum

from pydantic import BaseModel

from prisma.schema_gov import TypeRegistry


class Kind(str, Enum):
    widget = "widget"
    gadget = "gadget"


class Widget(BaseModel):
    name: str


class Gadget(BaseModel):
    label: str


def _registry() -> TypeRegistry:
    r: TypeRegistry = TypeRegistry()
    r.register(Kind.widget, Widget)
    r.register(Kind.gadget, Gadget)
    return r


def test_get_returns_the_registered_class():
    assert _registry().get(Kind.widget) is Widget


def test_contains():
    r = _registry()
    assert Kind.widget in r
    assert "not-a-key" not in r


def test_iterates_registered_keys():
    assert set(_registry()) == {Kind.widget, Kind.gadget}


def test_schema_for_returns_json_schema():
    schema = _registry().schema_for(Kind.widget)
    assert schema["title"] == "Widget"
    assert "name" in schema["properties"]


def test_all_schemas_keys_by_stringified_key():
    schemas = _registry().all_schemas()
    assert set(schemas) == {"Kind.widget", "Kind.gadget"}
