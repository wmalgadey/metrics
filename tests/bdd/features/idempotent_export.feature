Feature: Idempotent export to the metrics sink

  Scenario: Exporting twice produces identical samples
    Given a synced sprint in the local store
    When the metrics are exported twice
    Then both pushes contain exactly the same sample lines

  Scenario: Burndown samples carry the historical day as timestamp
    Given a synced sprint with snapshots for 2026-06-01
    When the metrics are exported
    Then every burndown sample for 2026-06-01 has the timestamp of that day at midnight UTC
