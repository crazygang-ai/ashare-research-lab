"""Build docs/data_dictionary.md from configs/data_dictionary.yaml.

TODO: Render the YAML data dictionary into Markdown once the field schema is finalized.
"""

from pathlib import Path


def main() -> None:
    output_path = Path(__file__).with_name("data_dictionary.md")
    output_path.write_text(
        "# Data Dictionary\n\n"
        "This file is generated from `configs/data_dictionary.yaml` by "
        "`docs/build_data_dictionary.py`.\n"
        "Do not maintain this Markdown file by hand.\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()

