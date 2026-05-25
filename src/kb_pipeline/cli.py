from __future__ import annotations

import json
from typing import Annotated

import typer

from kb_pipeline.models import PipelineMode, TriggerType
from kb_pipeline.pipelines.runner import PipelineRunner

app = typer.Typer(help="CLASS101 KB pipeline backend CLI")


@app.command()
def run(
    mode: Annotated[
        PipelineMode,
        typer.Option(help="smoke, backfill, or incremental"),
    ] = PipelineMode.SMOKE,
    write_mode: Annotated[str, typer.Option(help="dry-run or write")] = "dry-run",
    source: Annotated[list[str] | None, typer.Option(help="Target source filter")] = None,
    limit: Annotated[int | None, typer.Option(help="Optional item limit")] = None,
    lookback_hours: Annotated[
        int | None,
        typer.Option(help="Incremental Slack lookback window in hours"),
    ] = None,
    trigger_type: Annotated[
        TriggerType,
        typer.Option(help="manual, schedule, or slack_event"),
    ] = TriggerType.MANUAL,
) -> None:
    runner = PipelineRunner()
    result = runner.run(
        mode=mode,
        trigger_type=trigger_type,
        write_mode="write" if write_mode == "write" else "dry-run",
        target_sources=source,
        limit=limit,
        lookback_hours=lookback_hours,
    )
    typer.echo(json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2))


@app.command()
def scheduled(
    source: Annotated[
        list[str] | None,
        typer.Option(help="Target source filter"),
    ] = None,
    limit: Annotated[int | None, typer.Option(help="Optional item limit")] = None,
    lookback_hours: Annotated[
        int | None,
        typer.Option(help="Incremental Slack lookback window in hours"),
    ] = None,
    write_mode: Annotated[str, typer.Option(help="dry-run or write")] = "write",
) -> None:
    runner = PipelineRunner()
    result = runner.run(
        mode=PipelineMode.INCREMENTAL,
        trigger_type=TriggerType.SCHEDULE,
        write_mode="write" if write_mode == "write" else "dry-run",
        target_sources=source or ["slack", "event", "docbuilder", "terms"],
        limit=limit,
        lookback_hours=lookback_hours or 48,
    )
    typer.echo(json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2))


@app.command()
def health() -> None:
    from kb_pipeline.main import health as health_payload

    typer.echo(json.dumps(health_payload(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    app()
