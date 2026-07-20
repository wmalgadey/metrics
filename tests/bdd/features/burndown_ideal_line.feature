Feature: Sprint burndown ideal line
  The ideal line falls linearly across working days and stays flat over
  weekends and team days off, so real progress is compared to a fair target.

  Scenario: Linear descent over a five-day sprint
    Given a sprint from Monday 2026-06-01 to Friday 2026-06-05 with no days off
    And a day-one scope of 4 items
    When the ideal burndown line is computed
    Then the ideal value on 2026-06-01 is 4.0
    And the ideal value on 2026-06-03 is 2.0
    And the ideal value on 2026-06-05 is 0.0

  Scenario: The line stays flat over a weekend
    Given a sprint from Thursday 2026-06-04 to Monday 2026-06-08 with no days off
    And a day-one scope of 3 items
    When the ideal burndown line is computed
    Then the ideal value on Saturday 2026-06-06 equals the value on Friday 2026-06-05

  Scenario: A team day off does not burn work
    Given a sprint from Monday 2026-06-01 to Friday 2026-06-05
    And the whole team is off on 2026-06-03
    And a day-one scope of 3 items
    When the ideal burndown line is computed
    Then the ideal value on 2026-06-03 equals the value on 2026-06-02
    And the ideal value on 2026-06-05 is 0.0
