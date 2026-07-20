Feature: Velocity with rolling average

  Scenario: Rolling average over the last three sprints
    Given three completed sprints with 4, 6 and 8 completed items
    And a rolling window of 3 sprints
    When the velocity is computed
    Then the rolling average for the third sprint is 6.0

  Scenario: Fewer sprints than the window still yield an average
    Given one completed sprint with 5 completed items
    And a rolling window of 3 sprints
    When the velocity is computed
    Then the rolling average for that sprint is 5.0
