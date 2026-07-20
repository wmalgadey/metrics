-- DuckDB schema for azdo-metrics.
-- Item counts per work item type are the primary measure; Effort is stored
-- as an optional secondary field (may be NULL if not tracked by the team).
-- Idempotent: safe to run against an existing database.

CREATE TABLE IF NOT EXISTS projects (
    project_id   VARCHAR PRIMARY KEY,   -- Azure DevOps project name (unique within an org)
    organization VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS teams (
    team_id    VARCHAR PRIMARY KEY,     -- "{project}/{team}"
    project_id VARCHAR NOT NULL REFERENCES projects(project_id),
    name       VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS iterations (
    iteration_id   VARCHAR PRIMARY KEY,  -- REST GUID
    iteration_sk   VARCHAR,              -- Analytics surrogate key, joins WorkItems/Snapshots
    project_id     VARCHAR NOT NULL REFERENCES projects(project_id),
    team_id        VARCHAR NOT NULL REFERENCES teams(team_id),
    name           VARCHAR NOT NULL,
    path           VARCHAR NOT NULL,
    start_date     DATE,
    end_date       DATE,
    timeframe      VARCHAR,              -- past | current | future
    is_selected    BOOLEAN NOT NULL DEFAULT FALSE,
    UNIQUE (team_id, path)
);

CREATE TABLE IF NOT EXISTS capacities (
    iteration_id        VARCHAR NOT NULL REFERENCES iterations(iteration_id),
    team_id              VARCHAR NOT NULL,
    team_member_id       VARCHAR NOT NULL,
    member_name          VARCHAR,
    activity             VARCHAR NOT NULL DEFAULT '',
    capacity_per_day_hours DOUBLE NOT NULL DEFAULT 0,
    PRIMARY KEY (iteration_id, team_member_id, activity)
);

CREATE TABLE IF NOT EXISTS member_days_off (
    iteration_id   VARCHAR NOT NULL REFERENCES iterations(iteration_id),
    team_member_id VARCHAR NOT NULL,
    start_date     DATE NOT NULL,
    end_date       DATE NOT NULL
);

CREATE TABLE IF NOT EXISTS team_days_off (
    iteration_id VARCHAR NOT NULL REFERENCES iterations(iteration_id),
    team_id      VARCHAR NOT NULL,
    start_date   DATE NOT NULL,
    end_date     DATE NOT NULL
);

CREATE TABLE IF NOT EXISTS work_items (
    work_item_id     BIGINT PRIMARY KEY,
    project_id       VARCHAR NOT NULL REFERENCES projects(project_id),
    work_item_type   VARCHAR NOT NULL,
    title            VARCHAR,
    state            VARCHAR NOT NULL,
    state_category   VARCHAR NOT NULL,   -- raw Analytics StateCategory
    effective_category VARCHAR NOT NULL, -- Completed | Removed | InProgress | Other, config-adjusted
    iteration_path   VARCHAR,
    iteration_sk     VARCHAR,
    effort           DOUBLE,             -- optional secondary measure
    created_date     TIMESTAMP,
    activated_date   TIMESTAMP,
    closed_date      TIMESTAMP,
    completed_date   TIMESTAMP,
    changed_date     TIMESTAMP,
    cycle_time_days  DOUBLE,
    lead_time_days   DOUBLE,
    parent_id        BIGINT,
    tags             VARCHAR
);

CREATE TABLE IF NOT EXISTS work_item_snapshots (
    work_item_id       BIGINT NOT NULL,
    snapshot_date       DATE NOT NULL,
    work_item_type      VARCHAR NOT NULL,
    state                VARCHAR NOT NULL,
    state_category       VARCHAR NOT NULL,
    effective_category   VARCHAR NOT NULL,
    effort               DOUBLE,
    remaining_work       DOUBLE,
    iteration_sk         VARCHAR,
    iteration_path       VARCHAR NOT NULL,
    PRIMARY KEY (work_item_id, snapshot_date)
);

CREATE SEQUENCE IF NOT EXISTS sync_log_id_seq START 1;

CREATE TABLE IF NOT EXISTS sync_log (
    id          BIGINT PRIMARY KEY DEFAULT nextval('sync_log_id_seq'),
    run_id      VARCHAR NOT NULL,
    started_at  TIMESTAMP NOT NULL,
    finished_at TIMESTAMP,
    source      VARCHAR NOT NULL,   -- 'azdo' | 'gitlab' (future)
    entity      VARCHAR NOT NULL,   -- iterations | capacities | work_items | work_item_snapshots
    scope       VARCHAR NOT NULL,   -- iteration path, or 'global'
    watermark   VARCHAR,            -- max ChangedDate / DateValue observed
    row_count   INTEGER,
    status      VARCHAR NOT NULL,   -- ok | error
    error       VARCHAR,
    raw_path    VARCHAR
);

-- ---------------------------------------------------------------------------
-- Metric views. Downstream Python (metrics/*.py) adds calendar-aware bits
-- (ideal burndown line, rolling velocity average) that don't belong in SQL.
-- ---------------------------------------------------------------------------

-- Daily item counts per sprint & work item type — the burndown backbone.
CREATE OR REPLACE VIEW v_sprint_burndown AS
SELECT
    s.iteration_path,
    i.team_id,
    s.work_item_type,
    s.snapshot_date,
    COUNT(*) FILTER (WHERE s.effective_category NOT IN ('Completed', 'Removed')) AS open_items,
    COUNT(*) FILTER (WHERE s.effective_category <> 'Removed')                     AS scope_items,
    COUNT(*) FILTER (WHERE s.effective_category = 'Completed')                    AS done_items,
    SUM(s.effort) FILTER (WHERE s.effective_category NOT IN ('Completed', 'Removed')) AS remaining_effort,
    SUM(s.effort) FILTER (WHERE s.effective_category <> 'Removed')                     AS scope_effort,
    SUM(s.effort) FILTER (WHERE s.effective_category = 'Completed')                    AS completed_effort
FROM work_item_snapshots s
JOIN iterations i ON i.path = s.iteration_path
GROUP BY 1, 2, 3, 4;

-- Per-sprint planned (day-1 scope) vs completed (last snapshot day) item counts.
CREATE OR REPLACE VIEW v_velocity AS
WITH bounds AS (
    SELECT iteration_path, MIN(snapshot_date) AS day1, MAX(snapshot_date) AS last_day
    FROM work_item_snapshots
    GROUP BY 1
)
SELECT
    b.iteration_path,
    i.team_id,
    i.start_date,
    i.end_date,
    p.work_item_type,
    p.scope_items  AS planned_items,
    l.done_items   AS completed_items,
    p.scope_effort AS planned_effort,
    l.completed_effort
FROM bounds b
JOIN iterations i ON i.path = b.iteration_path
JOIN v_sprint_burndown p ON p.iteration_path = b.iteration_path AND p.snapshot_date = b.day1
JOIN v_sprint_burndown l
    ON l.iteration_path = b.iteration_path
    AND l.snapshot_date = b.last_day
    AND l.work_item_type = p.work_item_type;

-- Net capacity hours per sprint: capacity_per_day * working days present,
-- excluding weekends, member days off and team days off.
CREATE OR REPLACE VIEW v_capacity AS
WITH iteration_days AS (
    SELECT i.iteration_id, i.path AS iteration_path, i.team_id, d.day::DATE AS day
    FROM iterations i,
         LATERAL generate_series(i.start_date, i.end_date, INTERVAL 1 DAY) AS d(day)
    WHERE i.start_date IS NOT NULL AND i.end_date IS NOT NULL
      AND isodow(d.day) NOT IN (6, 7)
),
member_available_days AS (
    SELECT itd.iteration_id, itd.iteration_path, itd.team_id, itd.day, c.team_member_id, c.capacity_per_day_hours
    FROM iteration_days itd
    JOIN capacities c ON c.iteration_id = itd.iteration_id
    WHERE NOT EXISTS (
        SELECT 1 FROM member_days_off m
        WHERE m.iteration_id = itd.iteration_id
          AND m.team_member_id = c.team_member_id
          AND itd.day BETWEEN m.start_date AND m.end_date
    )
    AND NOT EXISTS (
        SELECT 1 FROM team_days_off t
        WHERE t.iteration_id = itd.iteration_id
          AND itd.day BETWEEN t.start_date AND t.end_date
    )
)
SELECT iteration_path, team_id, SUM(capacity_per_day_hours) AS capacity_hours
FROM member_available_days
GROUP BY 1, 2;

-- Completed work items with cycle/lead time, for percentile aggregation per type.
CREATE OR REPLACE VIEW v_cycle_time AS
SELECT
    work_item_id,
    work_item_type,
    iteration_path,
    completed_date,
    cycle_time_days,
    lead_time_days
FROM work_items
WHERE effective_category = 'Completed'
  AND cycle_time_days IS NOT NULL;
