# azdo-metrics

Fetches sprint metrics from Azure DevOps, stores them locally in DuckDB, and
exports them to VictoriaMetrics for Perses dashboards. Runs on Podman.

Tracks **one team's dedicated set of sprints** (past and current) so you can
see, per sprint:

- **Burndown** — open items per day (per work item type), against a
  calendar-aware ideal line, a scope line that exposes mid-sprint
  additions, and a remaining-capacity line (hours still available until
  sprint end, days off excluded) — plus Azure-DevOps-style stat tiles
  (items remaining, % completed, scope increase, average burndown,
  planned capacity).
- **Velocity** — planned vs. completed items per sprint, with a rolling
  average.
- **Capacity vs. velocity** — a normalized trend (items per capacity-hour),
  not an absolute ratio (capacity is hours, velocity is item counts).
- **Cycle/lead time** — P50/P85/P95 per work item type.
- **Sprint comparison** — one bar per sprint for planned capacity,
  planned vs. completed items, completion rate, scope increase and
  average burndown, so you can see under which conditions (how much
  planned capacity) each sprint's burndown was achieved.

Item **counts** per work item type are the primary measure, not Effort — see
[docs/architecture.md](docs/architecture.md#measurement-basis-item-counts-not-effort)
for why. Azure DevOps here holds only work items and a wiki; code lives in
GitLab (no access yet). The codebase is organized into three bounded
contexts (ingestion, analytics, publishing) behind ports, so GitLab code
metrics can be added as a new adapter later — see
[docs/architecture.md](docs/architecture.md#adding-gitlab-code-metrics-later).

## Prerequisites

- [Podman](https://podman.io/) (rootless) and `podman-compose`, or Podman
  ≥ 4 with the built-in `podman compose`.
- An Azure DevOps **Personal Access Token** with scopes: **Work Items
  (Read)** and **Analytics (Read)**. Create one at
  `https://dev.azure.com/<org>/_usersSettings/tokens`.

## Quick start

```sh
git clone <this repo>
cd metrics
cp .env.example .env        # then edit .env and set AZDO_PAT
./metrics.sh build          # build the CLI image (first run only)
./metrics.sh init           # validate the PAT, pick sprints, write config.yaml
./metrics.sh dashboard up   # start VictoriaMetrics + Perses
./metrics.sh sync           # fetch data, store it, export to VictoriaMetrics
```

Open Perses at <http://localhost:8080>. VictoriaMetrics' own UI is at
<http://localhost:8428/vmui>.

Run `./metrics.sh sync` again any time to pick up new data — it's
incremental (only fetches what changed since the last run) unless you pass
`--full`.

## Commands

`./metrics.sh <command> [args...]` runs `metrics <command> [args...]` inside
the CLI container, with `./data` and `./config.yaml` mounted:

| Command | What it does |
|---|---|
| `init` | Validates the PAT, lists the team's iterations, lets you pick which sprints to track, writes `config.yaml` and creates the DB. |
| `sync [--sprint PATH]... [--full] [--no-export]` | Fetches iterations, capacities, work items and daily snapshots for the selected (or given) sprints; exports to VictoriaMetrics afterwards unless `--no-export`. |
| `export [--sprint PATH]...` | Recomputes metrics from the local DB and (re-)pushes them to VictoriaMetrics, without touching Azure DevOps. Useful after changing `config.yaml`'s state mapping or rolling window. |
| `sprints list [--remote]` | Lists known sprints and whether they're selected/synced. `--remote` queries Azure DevOps live instead of the local DB. |
| `status` | Shows recent sync runs (`sync_log`). |

Other `metrics.sh` subcommands: `shell` (drop into the CLI image), `build`
(rebuild the image), `dashboard up|down` (start/stop VictoriaMetrics +
Perses).

## Selecting sprints

`metrics init` lists all iterations for the configured team and lets you
pick which ones to track by index. The selection is dedicated and explicit —
edit `sprints.selected` in `config.yaml` by hand at any time (a list of
iteration paths, e.g. `MyProject\Sprint 23`) and re-run `metrics sync`.

## Configuration

`config.yaml` (gitignored — copy from `config.example.yaml` or let `init`
write it) holds the non-secret settings: organization/project/team, the
selected sprints, the state-name-to-category mapping (which states count as
"done" for burndown/velocity and mark the start of "in progress" for cycle
time — falls back to Azure DevOps' own `StateCategory` if a state isn't
listed), the velocity rolling-window size, and the VictoriaMetrics URL.

`.env` (gitignored) holds only `AZDO_PAT`.

## Podman/rootless notes

- Bind mounts use the `:Z` SELinux label so Podman relabels them for the
  container — omit it if you're not on an SELinux host and it causes issues.
- `metrics.sh` runs the CLI container with
  `--userns=keep-id:uid=1000,gid=1000`, mapping your host user to the
  container's non-root `metrics` user (baked in as UID 1000 in the
  `Containerfile`) — files written under `./data` end up owned by you, not
  root, regardless of your host UID.
- It also runs with `--network host` so the container can reach
  VictoriaMetrics via `localhost:8428` (published by `dashboard up`) and
  Azure DevOps over the internet, without depending on Podman's compose
  network naming.

## Development (without containers)

```sh
uv sync --all-groups
uv run pytest
uv run ruff check src tests
uv run metrics --help
```

Tests run fully offline against recorded fixtures (`tests/fixtures/azdo/`,
via `respx`) and an in-memory DuckDB — no PAT or containers needed.
`tests/bdd/` is a parallel English-Gherkin specification (via `pytest-bdd`)
of the system's core rules (burndown ideal line, scope changes, velocity,
frozen sprints, incremental sync, cycle time, idempotent export) — read
`tests/bdd/features/*.feature` for a business-readable tour of what this
system actually guarantees.

## Architecture

See [docs/architecture.md](docs/architecture.md) for the raw layer → DuckDB
→ VictoriaMetrics → Perses pipeline, the DB schema, the ingestion/analytics/
publishing bounded contexts and their ports/adapters, and how to extend this
with GitLab code metrics.
