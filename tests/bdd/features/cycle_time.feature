Feature: Cycle time percentiles

  Scenario: Median cycle time of completed items
    Given completed product backlog items with cycle times of 2, 4 and 6 days
    When cycle time percentiles are computed
    Then the 50th percentile cycle time is 4.0 days

  Scenario: Unfinished items do not distort the percentiles
    Given 2 completed items with cycle times of 3 and 5 days
    And 1 item still in progress without a cycle time
    When cycle time percentiles are computed
    Then the percentile population counts 2 items
