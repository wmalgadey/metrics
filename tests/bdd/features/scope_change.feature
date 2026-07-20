Feature: Sprint scope change detection

  Scenario: An item added mid-sprint increases the scope line
    Given a synced sprint whose day-one snapshot contains 3 product backlog items
    And a fourth item appears in the daily snapshots from 2026-06-03 on
    When the burndown is computed
    Then the scope on 2026-06-01 is 3 items
    And the scope on 2026-06-03 is 4 items

  Scenario: A removed item leaves both scope and open work
    Given a synced sprint with 3 items open on day one
    And item 2 is moved to state "Removed" in the snapshot of 2026-06-04
    When the burndown is computed
    Then the scope on 2026-06-04 is 2 items
    And the open items on 2026-06-04 are 2
