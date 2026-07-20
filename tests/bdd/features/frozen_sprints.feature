Feature: Closed sprints freeze after a grace period

  Scenario: A past sprint is skipped once the grace period has elapsed
    Given a sprint that ended on 2026-06-05 with timeframe "past"
    And a grace period of 3 days
    When a sync runs on 2026-06-10
    Then the sprint is skipped as frozen

  Scenario: A past sprint still syncs within the grace period
    Given a sprint that ended on 2026-06-05 with timeframe "past"
    And a grace period of 3 days
    When a sync runs on 2026-06-07
    Then the sprint is synced

  Scenario: A full sync re-fetches a frozen sprint
    Given a frozen sprint
    When a sync runs with the full option
    Then the sprint is synced
