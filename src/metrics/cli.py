"""Typer CLI: init, sync, sprints, status."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from .azdo.http import AzdoHttpError, make_client
from .azdo.rest import RestClient
from .config import (
    DEFAULT_CONFIG_FILE,
    AppConfig,
    AzureDevOpsConfig,
    MetricsConfig,
    Settings,
    SprintsConfig,
)
from .storage.db import connect

app = typer.Typer(
    add_completion=False, help="Fetch Azure DevOps sprint metrics and store them locally."
)
sprints_app = typer.Typer(help="Inspect sprints (iterations).")
app.add_typer(sprints_app, name="sprints")

console = Console()


def _require_pat() -> str:
    settings = Settings()
    if not settings.azdo_pat:
        console.print(
            "[red]No AZDO_PAT configured.[/red] Copy .env.example to .env and set your "
            "Personal Access Token (scopes: Work Items Read, Analytics Read)."
        )
        raise typer.Exit(1)
    return settings.azdo_pat


def _load_config(path: Path) -> AppConfig:
    try:
        return AppConfig.load(path)
    except FileNotFoundError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from None


@app.command()
def init(
    organization: str = typer.Option(..., prompt=True, help="Azure DevOps organization"),
    project: str = typer.Option(..., prompt=True, help="Azure DevOps project name"),
    team: str = typer.Option(..., prompt=True, help="The one team whose sprints are analyzed"),
    sprints: str = typer.Option(
        "", help="Comma-separated iteration paths to select non-interactively"
    ),
    config_path: Path = typer.Option(
        DEFAULT_CONFIG_FILE, "--config", help="Where to write config.yaml"
    ),
) -> None:
    """Validate the PAT, discover iterations, select sprints, scaffold config.yaml + the DB."""
    pat = _require_pat()
    azdo_cfg = AzureDevOpsConfig(organization=organization, project=project, team=team)

    with make_client(pat) as client:
        rest = RestClient(client, azdo_cfg)
        try:
            iterations = rest.list_iterations()
        except AzdoHttpError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1) from None

    if not iterations:
        console.print(
            f"[yellow]No iterations found for team '{project}/{team}'.[/yellow] "
            "Check the team name and that it has sprints configured in Azure DevOps."
        )

    for i, it in enumerate(iterations):
        attrs = it.get("attributes", {})
        console.print(
            f"  [{i}] {it['path']}  ({attrs.get('timeFrame', '?')}, "
            f"{attrs.get('startDate', '?')[:10]}..{attrs.get('finishDate', '?')[:10]})"
        )

    if sprints:
        selected_paths = [s.strip() for s in sprints.split(",") if s.strip()]
    else:
        default_idx = [
            str(i) for i, it in enumerate(iterations)
            if it.get("attributes", {}).get("timeFrame") == "current"
        ]
        raw_choice = typer.prompt(
            "Select sprints to track (comma-separated indices)", default=",".join(default_idx)
        )
        indices = [int(x.strip()) for x in raw_choice.split(",") if x.strip()]
        selected_paths = [iterations[i]["path"] for i in indices if 0 <= i < len(iterations)]

    config = AppConfig(
        azure_devops=azdo_cfg,
        sprints=SprintsConfig(selected=selected_paths),
        metrics=MetricsConfig(),
    )
    config.dump(config_path)
    console.print(
        f"[green]Wrote {config_path}[/green] with {len(selected_paths)} selected sprint(s)."
    )

    conn = connect(config.db_path)
    conn.close()
    console.print(f"[green]Initialized database at {config.db_path}[/green]")
    console.print("\nNext: run [bold]metrics sync[/bold] to fetch data.")


@app.command()
def sync(
    sprint: list[str] = typer.Option(
        [],
        "--sprint",
        help="Iteration path to sync (repeatable). Defaults to config.yaml sprints.selected.",
    ),
    full: bool = typer.Option(False, "--full", help="Ignore watermarks and re-fetch everything."),
    config_path: Path = typer.Option(DEFAULT_CONFIG_FILE, "--config"),
) -> None:
    """Fetch iterations, capacities, work items and daily snapshots for the selected sprints."""
    from .sync.pipeline import run_sync

    pat = _require_pat()
    config = _load_config(config_path)
    conn = connect(config.db_path)
    try:
        results = run_sync(config, pat, conn, sprints=sprint or None, full=full)
    finally:
        conn.close()

    table = Table(title="Sync results")
    table.add_column("Entity")
    table.add_column("Scope")
    table.add_column("Status")
    table.add_column("Rows", justify="right")
    had_error = False
    for r in results:
        style = {"ok": "green", "error": "red", "skipped-frozen": "yellow"}.get(r.status, "")
        status_text = f"[{style}]{r.status}[/{style}]" if style else r.status
        table.add_row(r.entity, r.scope, status_text, str(r.row_count))
        if r.status == "error":
            had_error = True
            console.print(f"[red]  {r.entity}/{r.scope}: {r.error}[/red]")
    console.print(table)
    if had_error:
        raise typer.Exit(1)


@sprints_app.command("list")
def sprints_list(
    remote: bool = typer.Option(
        False, "--remote", help="Query Azure DevOps live instead of the local DB."
    ),
    config_path: Path = typer.Option(DEFAULT_CONFIG_FILE, "--config"),
) -> None:
    """List known iterations, whether they're selected, and their last sync status."""
    config = _load_config(config_path)
    table = Table()
    table.add_column("Path")
    table.add_column("Timeframe")
    table.add_column("Start")
    table.add_column("End")
    table.add_column("Selected")

    if remote:
        pat = _require_pat()
        with make_client(pat) as client:
            rest = RestClient(client, config.azure_devops)
            iterations = rest.list_iterations()
        selected = set(config.sprints.selected)
        for it in iterations:
            attrs = it.get("attributes", {})
            table.add_row(
                it["path"], attrs.get("timeFrame", ""), (attrs.get("startDate") or "")[:10],
                (attrs.get("finishDate") or "")[:10], "yes" if it["path"] in selected else "",
            )
    else:
        conn = connect(config.db_path, read_only=True)
        rows = conn.execute(
            "SELECT path, timeframe, start_date, end_date, is_selected FROM iterations "
            "WHERE team_id = ? ORDER BY start_date",
            [f"{config.azure_devops.project}/{config.azure_devops.team}"],
        ).fetchall()
        conn.close()
        for path, timeframe, start, end, is_selected in rows:
            table.add_row(
                path, timeframe or "", str(start or ""), str(end or ""),
                "yes" if is_selected else "",
            )

    console.print(table)


@app.command()
def status(
    limit: int = typer.Option(20, help="Number of recent sync_log entries to show"),
    config_path: Path = typer.Option(DEFAULT_CONFIG_FILE, "--config"),
) -> None:
    """Show recent sync runs."""
    config = _load_config(config_path)
    conn = connect(config.db_path, read_only=True)
    rows = conn.execute(
        "SELECT run_id, entity, scope, status, row_count, finished_at FROM sync_log "
        "ORDER BY finished_at DESC NULLS LAST LIMIT ?",
        [limit],
    ).fetchall()
    conn.close()

    table = Table(title="Recent sync runs")
    for col in ["Run", "Entity", "Scope", "Status", "Rows", "Finished"]:
        table.add_column(col)
    for run_id, entity, scope, run_status, row_count, finished_at in rows:
        style = {"ok": "green", "error": "red"}.get(run_status, "")
        status_text = f"[{style}]{run_status}[/{style}]" if style else run_status
        table.add_row(run_id, entity, scope, status_text, str(row_count), str(finished_at or ""))
    console.print(table)


if __name__ == "__main__":
    app()
