# Architecture

## Why this shape

Azure DevOps only holds work items and a wiki for this team; code lives in
GitLab, which isn't reachable yet. The system is split into three layers so
that (a) nothing is lost if a transform or metric formula is wrong, and (b)
GitLab code metrics can be added later without a redesign.

```
Azure DevOps ──sync──▶ Raw layer (gzip JSON) ──load──▶ DuckDB (source of truth)
                                                              │
                                                    export (historical timestamps)
                                                              ▼
                                    VictoriaMetrics (TSDB) ◀──PromQL── Perses dashboards
```

- **Raw layer** (`data/raw/azdo/<entity>/<run_id>/<sprint>.json.gz`): verbatim
  API responses. Lets you replay a transform (e.g. after fixing a bug in the
  storage adapter) without hitting Azure DevOps again, and doubles as an
  audit trail.
- **DuckDB** (`data/metrics.duckdb`): the source of truth. Analytical
  queries (window functions for rolling velocity, `QUANTILE_CONT` for cycle
  time percentiles) run well here, and it's a single file — easy to back up,
  inspect with `duckdb data/metrics.duckdb` and ad-hoc SQL, or wipe and
  rebuild from the raw layer.
- **VictoriaMetrics**: a Prometheus-compatible time-series store. It exists
  only because Perses (the dashboard tool) speaks PromQL, not SQL. The
  export step renders DuckDB's metric views as Prometheus exposition lines
  with the *actual historical timestamp* of each data point (VictoriaMetrics'
  import API accepts arbitrary past timestamps directly, no backfill
  workaround needed), and re-exporting is idempotent — identical
  `(metric, labels, timestamp)` samples just overwrite via VM's dedup.
- **Perses**: dashboards as YAML, checked into `perses/provisioning/`. Chosen
  over Streamlit/Grafana because the same dashboard format is intended for
  reuse later in OpenShift/ACM — only the datasource URL changes.

DuckDB stays authoritative. If VictoriaMetrics' data directory is deleted,
`metrics export` rebuilds it completely from DuckDB.

## Code organization: three bounded contexts, hexagonal per context

The pipeline above maps onto three top-level Python packages under
`src/metrics/`, named after what they do rather than the technology they use
("screaming architecture") — `ingestion`, `analytics`, `publishing` — plus a
`shared/duckdb` kernel (schema + connection factory) that `ingestion` writes
to and `analytics` reads from. `cli.py` is the *composition root*: it's the
only place that constructs concrete adapters (`AzdoWorkTrackingSource`,
`DuckDbSyncStore`, `FileRawArchive`, `DuckDbSprintMetricsRepository`,
`VictoriaMetricsSink`) and wires them into the use cases.

Each context follows the same hexagonal shape:

```
<context>/
├── domain/     # pure logic + dataclasses — no DB, no HTTP, no filesystem
├── ports.py    # typing.Protocol interfaces the service depends on
├── service.py  # the use case, written against ports only
└── adapters/   # concrete implementations of the ports
```

| Context | Use case | Port(s) | Adapter(s) |
|---|---|---|---|
| `ingestion` | `sync_sprints()` — fetch from Azure DevOps, archive raw responses, upsert into DuckDB | `WorkTrackingSource`, `RawArchive`, `SyncStore` | `AzdoWorkTrackingSource` (REST + OData clients), `FileRawArchive`, `DuckDbSyncStore` |
| `analytics` | `sprint_burndown()`/`sprint_velocity()`/`capacity_vs_velocity()`/`cycle_time_percentiles()`/`scope_change()` — compute metrics from stored data | `SprintMetricsRepository` | `DuckDbSprintMetricsRepository` (all the SQL lives here) |
| `publishing` | `publish_metrics()` — render metrics and push them to a sink | `MetricsSink` | `VictoriaMetricsSink` |

`publishing` depends on `analytics`'s domain dataclasses (a customer of that
context, not a peer); `ingestion` and `analytics` share only the DuckDB
schema — no context imports another context's adapters. Pure calendar and
classification logic (`analytics/domain/calendar.py`'s working-day
computation, `analytics/domain/burndown.py`'s ideal line,
`ingestion/domain/states.py`'s state classification,
`ingestion/domain/watermarks.py`'s incremental-sync date math) lives in each
context's `domain/` package and has no dependency on DuckDB, httpx, or the
filesystem — that's what makes it testable without any of them (see
"Testing" below).

## Data model

Dimensions (`projects`, `teams`, `iterations`) carry `project_id`/`team_id`
even though the current scope is one project and one team — this avoids a
schema change if a second team is added later.

Facts:
- `capacities`, `member_days_off`, `team_days_off` — per-sprint capacity
  input (hours/day per person, minus days off).
- `work_items` — current state of each item (type, state, effort, cycle/lead
  time from Analytics).
- `work_item_snapshots` — **daily** state per item, the backbone for
  burndown, scope-change detection, and (future) cumulative flow diagrams.
- `sync_log` — one row per (entity, sprint) sync attempt, with the watermark
  used for incremental fetches. `source` is already `'azdo'` vs. reserved
  `'gitlab'` so a future GitLab sync can log into the same table.

See `src/metrics/shared/duckdb/schema.sql` for the full DDL and the metric
views (`v_sprint_burndown`, `v_velocity`, `v_capacity`, `v_cycle_time`,
`v_scope_change`).

## Measurement basis: item counts, not Effort

Burndown and velocity are computed primarily from **item counts per work
item type** (dynamically discovered — no fixed type list), not from the
`Effort` field. In this team, Effort isn't reliably maintained, so an
Effort-based burndown would be misleading. Effort is still captured and
exported as an optional secondary series wherever it has values, in case
that changes later. `config.yaml`'s `metrics.excluded_types` can filter out
noise types (e.g. "Test Case") from the counts.

## Cycle time classification

Azure DevOps' Analytics `StateCategory` (Proposed/InProgress/Completed/
Removed) is the default classification, but `config.yaml`'s
`metrics.states` mapping can override it per literal state name — useful if
a custom workflow state isn't categorized the way you'd expect.
`classify_state` (`ingestion/domain/states.py`, pure) applies config first,
falling back to Analytics' own category.

## Testing: unit/integration tests + a BDD living specification

`tests/*.py` are the technical test suite: API clients against recorded
fixtures (`tests/fixtures/azdo/`, via `respx`), storage/loader idempotency,
metric math, export rendering, CLI error paths, and two end-to-end tests
that drive the actual CLI through `sync → DuckDB → export` with mocked
HTTP.

`tests/bdd/` is a parallel, business-readable specification of the
system's core rules, written with `pytest-bdd` — English Gherkin feature
files under `tests/bdd/features/`, step definitions under
`tests/bdd/steps/`. It exists so the *behavior* (not the implementation) of
things like "the burndown ideal line stays flat over a weekend" or "a
sprint past its grace period is skipped" is documented in a form a
non-programmer can read and that fails loudly if that behavior changes.
Pure-domain scenarios (ideal line, frozen sprints, watermark ranges) call
domain functions directly with no DB; view-backed scenarios (scope change,
velocity, cycle time) seed an in-memory DuckDB through the real storage
adapter and read through the real repository adapter — deliberately *not*
a fake, since the business rules for those scenarios live in SQL views and
a fake would only test itself.

## Adding GitLab code metrics later

The `sync_log.source` column and the `'azdo'` constant in
`ingestion/service.py` already anticipate a second source. To add GitLab:

1. Add an `ingestion/adapters/gitlab/` package implementing the
   `WorkTrackingSource` protocol (or a parallel port, if GitLab's shape
   doesn't fit it) — mirroring `ingestion/adapters/azdo/`.
2. Add `gitlab_*` tables to `schema.sql` (e.g. `gitlab_merge_requests`,
   `gitlab_commits`) with a `merged_at`/`committed_at` timestamp column.
3. Join to sprints by date: `WHERE gitlab_merge_requests.merged_at BETWEEN
   iterations.start_date AND iterations.end_date` — no changes needed to the
   existing `iterations` table.
4. Add `gitlab_*` fields to `analytics`'s `SprintMetricsRepository` port (or
   a new `CodeMetricsRepository` port, if code metrics don't fit the sprint
   shape) and render new Prometheus series in `publishing/domain/
   exposition.py` the same way Azure DevOps metrics are rendered today, then
   add panels/dashboards for them.

## Known limitations

- Analytics OData is pinned at `v4.0-preview` (practically stable for years,
  but still preview-labeled upstream) — isolated entirely in
  `ingestion/adapters/azdo/odata.py`.
- Analytics ingestion has latency (minutes to hours); "today" in a burndown
  chart may lag slightly behind Azure DevOps' own UI.
- Capacity is hours/day; velocity is item counts. The "Capacity vs.
  Velocity" dashboard is a normalized *trend* (items per capacity-hour), not
  an absolute ratio — the dashboard says so explicitly.
- Perses has no native box-plot panel, so cycle/lead time percentiles
  (P50/P85/P95) are rendered as separate time series instead.
- Perses' dashboard YAML schema is still evolving upstream. The dashboards
  under `perses/provisioning/dashboards/` were written against the schema
  documented at the time this system was built; if Perses rejects one on
  startup, check its logs (`podman logs azdo-metrics-perses`) and adjust
  `kind`/`plugin.kind` fields to match your installed Perses version.
