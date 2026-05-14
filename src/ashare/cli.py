"""Command-line interface for ashare-research-lab."""

from typing import Any

import typer

app = typer.Typer(help="A-share research assistant CLI.")


def _echo_todo(command: str, **params: Any) -> None:
    typer.echo(f"{command}: TODO")
    typer.echo(f"params: {params}")


@app.command(name="ingest")
def ingest(
    universe: str = typer.Option("hs300", "--universe"),
    from_: str | None = typer.Option(None, "--from"),
    to: str | None = typer.Option(None, "--to"),
) -> None:
    """Print ingest parameters without fetching data."""
    _echo_todo("ingest", universe=universe, from_=from_, to=to)


@app.command(name="validate-factors")
def validate_factors(
    universe: str = typer.Option("hs300", "--universe"),
    from_: str | None = typer.Option(None, "--from"),
    to: str | None = typer.Option(None, "--to"),
    horizon: str = typer.Option("20,60,120", "--horizon"),
) -> None:
    """Print factor-validation parameters without calculating factors."""
    _echo_todo("validate-factors", universe=universe, from_=from_, to=to, horizon=horizon)


@app.command(name="event-study")
def event_study(
    event: str = typer.Option(..., "--event"),
    from_: str | None = typer.Option(None, "--from"),
    to: str | None = typer.Option(None, "--to"),
    horizon: str = typer.Option("5,20,60", "--horizon"),
) -> None:
    """Print event-study parameters without running an event study."""
    _echo_todo("event-study", event=event, from_=from_, to=to, horizon=horizon)


@app.command(name="scan")
def scan(
    as_of: str = typer.Option(..., "--as-of"),
    universe: str = typer.Option("hs300", "--universe"),
    top: int = typer.Option(20, "--top"),
) -> None:
    """Print scan parameters without generating candidates."""
    _echo_todo("scan", as_of=as_of, universe=universe, top=top)


@app.command(name="backtest")
def backtest(
    strategy: str = typer.Option("base_score", "--strategy"),
    from_: str | None = typer.Option(None, "--from"),
    to: str | None = typer.Option(None, "--to"),
) -> None:
    """Print backtest parameters without running a backtest."""
    _echo_todo("backtest", strategy=strategy, from_=from_, to=to)


@app.command(name="report")
def report(as_of: str = typer.Option(..., "--as-of")) -> None:
    """Print report parameters without writing reports."""
    _echo_todo("report", as_of=as_of)


@app.command(name="stock-report")
def stock_report(
    code: str = typer.Option(..., "--code"),
    as_of: str = typer.Option(..., "--as-of"),
) -> None:
    """Print stock-report parameters without writing reports."""
    _echo_todo("stock-report", code=code, as_of=as_of)

