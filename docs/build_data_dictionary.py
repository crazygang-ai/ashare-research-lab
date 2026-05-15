"""Build docs/data_dictionary.md from configs/data_dictionary.yaml."""

from pathlib import Path

import yaml


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    config_path = root / "configs" / "data_dictionary.yaml"
    output_path = Path(__file__).with_name("data_dictionary.md")
    with config_path.open(encoding="utf-8") as file:
        config = yaml.safe_load(file) or {}

    fields = config.get("fields", {})
    lines = [
        "# Data Dictionary",
        "",
        "This file is generated from `configs/data_dictionary.yaml` by "
        "`docs/build_data_dictionary.py`.",
        "Do not maintain this Markdown file by hand.",
        "",
    ]
    for name in sorted(fields):
        entry = fields[name]
        lines.extend(
            [
                f"## {name}",
                "",
                f"- type: {entry.get('type', '')}",
                f"- source: {entry.get('source', '')}",
                f"- raw_fields: {', '.join(entry.get('raw_fields', []))}",
                f"- formula: {entry.get('formula', '')}",
                f"- unit: {entry.get('unit', '')}",
                f"- frequency: {entry.get('frequency', '')}",
                f"- effective_date: {entry.get('effective_date', '')}",
                f"- direction: {entry.get('direction', '')}",
                f"- missing: {entry.get('missing', '')}",
                f"- hard_filter: {entry.get('hard_filter', '')}",
                f"- soft_penalty: {entry.get('soft_penalty', '')}",
                f"- description: {entry.get('description', '')}",
                "",
            ]
        )

    output_path.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
