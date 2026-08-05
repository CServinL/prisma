"""Versioned-migration base class.

Generalizes the pattern prisma's own vault.py first built by hand for the
chat prisma:meta blob (`_migrate_chat_meta`): a `schema_version` field, an
absent-version-means-v1 convention (the shape a model had before this
mechanism was ever applied to it), and a migration chain applied before
Pydantic's normal field validation runs -- rather than every model that
needs this hand-rolling its own dispatch function.
"""
from __future__ import annotations

from typing import Any, Callable, ClassVar

from pydantic import BaseModel, model_validator


class VersionedModel(BaseModel):
    """Subclass and set SCHEMA_VERSION; once the shape actually changes, add
    an entry to MIGRATIONS keyed by the version being upgraded *from* (e.g.
    `MIGRATIONS = {1: _upgrade_v1_to_v2}`). Never rewrite an existing
    migration step once shipped -- each version's upgrade path must stay
    correct for data frozen at that version, however old."""

    schema_version: int = 1

    SCHEMA_VERSION: ClassVar[int] = 1
    MIGRATIONS: ClassVar[dict[int, Callable[[dict], dict]]] = {}

    @model_validator(mode="before")
    @classmethod
    def _migrate(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data  # already a model instance (or something else) -- nothing to migrate
        raw = dict(data)
        version = raw.get("schema_version", 1)
        if version > cls.SCHEMA_VERSION:
            raise ValueError(
                f"{cls.__name__} schema_version {version} is newer than this "
                f"build supports ({cls.SCHEMA_VERSION})"
            )
        while version < cls.SCHEMA_VERSION:
            migrate = cls.MIGRATIONS.get(version)
            if migrate is None:
                raise ValueError(
                    f"{cls.__name__}: no migration registered from schema_version {version}"
                )
            raw = migrate(raw)
            version += 1
        raw["schema_version"] = cls.SCHEMA_VERSION
        return raw
