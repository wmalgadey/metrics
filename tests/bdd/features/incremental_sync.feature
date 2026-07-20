Feature: Incremental sync via watermarks

  Scenario: The second sync only asks for changes after the watermark
    Given a successful work-items sync recorded the watermark 2026-06-03T10:00:00Z
    When an incremental sync runs
    Then the work tracking source is queried for changes since 2026-06-03

  Scenario: Snapshot fetching resumes the day after the watermark
    Given a sprint from 2026-06-01 to 2026-06-12
    And a snapshot watermark of 2026-06-04
    When the snapshot date range is computed on 2026-06-08
    Then snapshots are fetched from 2026-06-05 through 2026-06-08

  Scenario: A full sync ignores the watermark
    Given a successful work-items sync recorded a watermark
    When an incremental sync runs with the full option
    Then the work tracking source is queried without a change filter
