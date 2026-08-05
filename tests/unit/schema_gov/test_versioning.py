"""Unit tests for VersionedModel -- standalone, no prisma-domain models
involved (schema_gov must not depend on them)."""
import pytest

from prisma.schema_gov import VersionedModel


class Widget(VersionedModel):
    name: str


def test_absent_schema_version_is_treated_as_v1():
    w = Widget.model_validate({"name": "gadget"})
    assert w.schema_version == 1
    assert w.name == "gadget"


def test_current_version_passes_through_unchanged():
    w = Widget.model_validate({"schema_version": 1, "name": "gadget"})
    assert w.schema_version == 1


def test_raises_for_a_version_newer_than_this_build_supports():
    with pytest.raises(ValueError, match="newer than this build supports"):
        Widget.model_validate({"schema_version": 99, "name": "gadget"})


def _widget_v1_to_v2(raw: dict) -> dict:
    raw = dict(raw)
    raw["label"] = raw.pop("name")
    return raw


class WidgetV2(VersionedModel):
    label: str  # renamed from "name" in v2

    SCHEMA_VERSION = 2
    MIGRATIONS = {1: _widget_v1_to_v2}


def test_migration_chain_upgrades_an_old_shape():
    w = WidgetV2.model_validate({"name": "gadget"})  # absent version -> v1 -> migrated to v2
    assert w.label == "gadget"
    assert w.schema_version == 2


def test_missing_migration_step_raises():
    class NoMigrations(VersionedModel):
        SCHEMA_VERSION = 2
        MIGRATIONS = {}

    with pytest.raises(ValueError, match="no migration registered"):
        NoMigrations.model_validate({"schema_version": 1})
