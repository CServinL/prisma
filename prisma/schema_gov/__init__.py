"""Generic, domain-agnostic persistence-governance primitives: versioned
schema migration, a type registry, JSON Schema export, and a typed
multi-format content wrapper.

Nothing under this package imports from `prisma.storage`, `prisma.services`,
or any other prisma-domain module -- see docs/wiki/adr/ADR-019-persisted-
format-governance-and-migrations.md. Prisma's own domain models (Note,
Source, Chat, ...) depend on this package and register themselves
into it; this package never depends back. That one-way boundary is what
would let this package move to its own repo for reuse across future
projects without disentangling prisma-specific references first.
"""
from .content import ContentFormat, RichContent
from .export import export_schemas
from .registry import TypeRegistry
from .versioning import VersionedModel

__all__ = [
    "ContentFormat",
    "RichContent",
    "TypeRegistry",
    "VersionedModel",
    "export_schemas",
]
