"""Command-line wrapper for local fixture generation."""

from pathlib import Path

import typer

from ashare.fixtures.builder import build_fixtures


app = typer.Typer(help="Build local synthetic CSV fixtures.")


@app.command()
def main(
    output_dir: Path = typer.Option(
        Path("tests/fixtures/generated"),
        "--output-dir",
        help="Directory where fixture CSV files will be written.",
    ),
) -> None:
    """Build local synthetic fixture CSV files."""
    build_fixtures(output_dir)
    typer.echo(f"Built fixtures in: {output_dir}")


if __name__ == "__main__":
    app()
