"""Render data dictionary Markdown files from configs/data_dictionary.yaml."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml


GENERATED_NOTICE = (
    "This file is generated from configs/data_dictionary.yaml by docs/build_data_dictionary.py."
)
DO_NOT_EDIT_NOTICE = "Do not edit by hand."


def render_data_dictionary(config: dict[str, object]) -> str:
    """Render docs/data_dictionary.md without reading or writing files."""
    schema_fields = _mapping(config.get("schema_fields"))
    factors = _mapping(config.get("factors"))
    lines = [
        "# Data Dictionary",
        "",
        GENERATED_NOTICE,
        DO_NOT_EDIT_NOTICE,
        "",
    ]

    for name in sorted(schema_fields):
        entry = _mapping(schema_fields[name])
        lines.extend(_render_entry(f"## {name}", "schema_fields", entry))

    for name in sorted(factors):
        entry = _mapping(factors[name])
        lines.extend(_render_entry(f"## {name}", "factors", entry))

    return _finish(lines)


def render_factor_definitions(config: dict[str, object]) -> str:
    """Render docs/factor_definitions.md without reading or writing files."""
    factors = _mapping(config.get("factors"))
    factor_entries = {
        name: _mapping(entry)
        for name, entry in factors.items()
        if _mapping(entry).get("type") in {"factor", "hard_filter"}
    }
    groups = sorted(
        {
            str(entry.get("score_group", "ungrouped"))
            for entry in factor_entries.values()
        }
    )

    lines = [
        "# Factor Definitions",
        "",
        GENERATED_NOTICE,
        DO_NOT_EDIT_NOTICE,
        "",
    ]
    for group in groups:
        lines.extend([f"## {group}", ""])
        for name in sorted(
            key
            for key, entry in factor_entries.items()
            if str(entry.get("score_group", "ungrouped")) == group
        ):
            lines.extend(_render_entry(f"### {name}", None, factor_entries[name]))

    return _finish(lines)


def main() -> None:
    """Read the YAML source of truth and write generated Markdown artifacts."""
    root = Path(__file__).resolve().parents[1]
    config_path = root / "configs" / "data_dictionary.yaml"
    data_dictionary_path = root / "docs" / "data_dictionary.md"
    factor_definitions_path = root / "docs" / "factor_definitions.md"

    with config_path.open(encoding="utf-8") as file:
        config = yaml.safe_load(file) or {}

    data_dictionary_path.write_text(
        render_data_dictionary(config),
        encoding="utf-8",
    )
    factor_definitions_path.write_text(
        render_factor_definitions(config),
        encoding="utf-8",
    )


def _render_entry(
    heading: str,
    section: str | None,
    entry: Mapping[str, Any],
) -> list[str]:
    lines = [heading, ""]
    if section is not None:
        lines.append(f"- section: {section}")
    for key in sorted(entry):
        lines.append(f"- {key}: {_format_value(entry[key])}")
    lines.append("")
    return lines


def _format_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return ""
    if isinstance(value, Mapping):
        if not value:
            return "{}"
        pairs = [f"{key}: {_format_value(value[key])}" for key in sorted(value)]
        return "{" + ", ".join(pairs) + "}"
    if isinstance(value, list):
        return ", ".join(_format_value(item) for item in value)
    return str(value)


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _finish(lines: list[str]) -> str:
    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
