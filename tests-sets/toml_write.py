"""Minimal dict -> TOML serializer, test-only.

Just enough to cover this test suite's config fixture shapes (nested dicts
become tables, values are str/bool/int/float/list[str]) -- not a general
TOML writer. stdlib only has tomllib (read-only), so something has to fill
this gap for tests that build a config from a plain dict rather than a
hand-written literal.
"""
from __future__ import annotations


def dict_to_toml(data: dict) -> str:
    lines: list[str] = []
    scalars = {k: v for k, v in data.items() if not isinstance(v, dict)}
    tables = {k: v for k, v in data.items() if isinstance(v, dict)}
    for key, value in scalars.items():
        lines.append(f"{key} = {_toml_value(value)}")
    for key, value in tables.items():
        if lines:
            lines.append("")
        lines.extend(_toml_table(key, value))
    return "\n".join(lines) + "\n"


def _toml_table(prefix: str, table: dict) -> list[str]:
    lines = [f"[{prefix}]"]
    scalars = {k: v for k, v in table.items() if not isinstance(v, dict)}
    nested = {k: v for k, v in table.items() if isinstance(v, dict)}
    for key, value in scalars.items():
        lines.append(f"{key} = {_toml_value(value)}")
    for key, value in nested.items():
        lines.append("")
        lines.extend(_toml_table(f"{prefix}.{key}", value))
    return lines


def _toml_value(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    if isinstance(value, list):
        return "[" + ", ".join(_toml_value(v) for v in value) + "]"
    raise TypeError(f"unsupported TOML value type: {type(value)!r}")
