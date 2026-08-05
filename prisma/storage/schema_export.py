"""Prisma-specific schema export -- wraps schema_gov.export_schemas with
this repo's type registry plus the session-layer sub-document models that
aren't NodeType-keyed themselves. See ADR-019.
"""
from __future__ import annotations

from prisma.schema_gov import RichContent
from prisma.schema_gov import export_schemas as _export_schemas
from prisma.storage.models.vault_models import Footnote, SessionMessage, ToolCallRecord
from prisma.storage.type_registry import REGISTRY


def _drop_path_from_required(schema: dict) -> dict:
    """`VaultNodeBase.path` is required on every registered node model
    (Note/Source/ChatSession/Stream) because Pydantic sees no default for
    it, but it's never actually part of a stored file's own content --
    every render function (_render_frontmatter's hand-built `fm` dict,
    ChatSession.save_chat_session's explicit `exclude={"path"}`) derives it
    from the file's location on load instead. Validating a real on-disk
    file against the un-adjusted schema would fail on a field that's
    correctly, deliberately absent -- this makes the exported schema
    describe the actual stored shape, not the fuller in-memory one."""
    required = schema.get("required")
    if required and "path" in required:
        schema = {**schema, "required": [f for f in required if f != "path"]}
    return schema


def export_schemas() -> dict[str, dict]:
    schemas = _export_schemas(
        REGISTRY,
        extra={
            "rich-content": RichContent,
            "footnote": Footnote,
            "tool-call-record": ToolCallRecord,
            "session-message": SessionMessage,
        },
    )
    return {key: _drop_path_from_required(schema) for key, schema in schemas.items()}


def schema_filename(key: str) -> str:
    """"NodeType.note" -> "note.schema.json"; "rich-content" ->
    "rich-content.schema.json" -- registry keys are stringified enum
    members ("NodeType.note"), extra keys are already plain names."""
    name = key.rsplit(".", 1)[-1]
    return f"{name}.schema.json"
