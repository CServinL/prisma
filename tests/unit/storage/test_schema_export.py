"""Drift test for the committed prisma/schemas/*.schema.json files
(ADR-019) -- fails if a persisted model's shape changed without
`prisma schema export` being re-run and the result committed."""
import json
from pathlib import Path

from prisma.storage.schema_export import export_schemas, schema_filename

SCHEMAS_DIR = Path(__file__).resolve().parents[3] / "schemas"


def test_committed_schemas_match_the_live_models():
    live = export_schemas()
    stale = []
    missing = []
    for key, schema in live.items():
        path = SCHEMAS_DIR / schema_filename(key)
        if not path.exists():
            missing.append(path.name)
            continue
        committed = json.loads(path.read_text(encoding="utf-8"))
        if committed != schema:
            stale.append(path.name)

    assert not missing, (
        f"missing committed schema file(s): {missing} -- run `prisma schema export`"
    )
    assert not stale, (
        f"committed schema file(s) out of date: {stale} -- run `prisma schema export` and commit the result"
    )


def test_no_orphaned_committed_schema_files():
    live_filenames = {schema_filename(key) for key in export_schemas()}
    on_disk = {p.name for p in SCHEMAS_DIR.glob("*.schema.json")}
    orphaned = on_disk - live_filenames
    assert not orphaned, f"committed schema file(s) no longer exported by any model: {orphaned}"


def test_path_is_not_required_in_node_schemas():
    # VaultNodeBase.path is populated at load time (derived from the file's
    # actual location), never part of a stored file's own content -- a real
    # on-disk file validated against the schema must not fail on a
    # correctly-absent field. See schema_export._drop_path_from_required.
    schemas = export_schemas()
    for key in ("NodeType.note", "NodeType.source", "NodeType.chat", "NodeType.stream"):
        required = schemas[key].get("required", [])
        assert "path" not in required, f"{key}: path should not be required"
