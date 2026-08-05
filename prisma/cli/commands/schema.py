#!/usr/bin/env python3
"""
Schema CLI Commands

Regenerates the committed JSON Schema files under prisma/schemas/ from the
live Pydantic models (ADR-019) -- the drift test in
tests/unit/storage/test_schema_export.py fails if a model changes without
this being re-run and the result committed.
"""
import json
from pathlib import Path

import click

from prisma.storage.schema_export import export_schemas, schema_filename

SCHEMAS_DIR = Path(__file__).resolve().parents[3] / "schemas"


@click.group(name="schema")
def schema_group():
    """JSON Schema export for prisma's persisted types (ADR-019)."""
    pass


@schema_group.command("export")
def export_cmd():
    """Regenerate prisma/schemas/*.schema.json from the current Pydantic
    models. Commit the result whenever a persisted model's shape changes."""
    SCHEMAS_DIR.mkdir(parents=True, exist_ok=True)
    schemas = export_schemas()
    for key, schema in schemas.items():
        path = SCHEMAS_DIR / schema_filename(key)
        path.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        click.echo(f"  wrote {path.relative_to(SCHEMAS_DIR.parent)}")
    click.echo(f"\n{len(schemas)} schemas exported to {SCHEMAS_DIR}")
