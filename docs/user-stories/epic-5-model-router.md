# Epic 5: Model Router

## Story 5.1 — Route tasks by complexity and type

```gherkin
Feature: Model routing
  As the quiz engine
  I want to route each subtask to the appropriate model
  So that simple tasks use free local inference and complex tasks use premium

  Scenario: Route chunk summarization to local
    Given mode is "hybrid"
    And the task type is "summarize_chunk"
    When the router classifies the task
    Then it returns "local"

  Scenario: Route conceptual question generation to premium
    Given mode is "hybrid"
    And the task type is "generate_question" with question_type "conceptual"
    When the router classifies the task
    Then it returns "premium"

  Scenario: Route code question generation to premium
    Given mode is "hybrid"
    And the task type is "generate_question" with question_type "code"
    When the router classifies the task
    Then it returns "premium"

  Scenario: Route fill-in question generation to local
    Given mode is "hybrid"
    And the task type is "generate_question" with question_type "fill_in"
    When the router classifies the task
    Then it returns "local"

  Scenario: Route code answer evaluation to premium
    Given mode is "hybrid"
    And the task type is "evaluate_answer" with question_type "code"
    When the router classifies the task
    Then it returns "premium"

  Scenario: Route conceptual answer evaluation to premium
    Given mode is "hybrid"
    And the task type is "evaluate_answer" with question_type "conceptual"
    When the router classifies the task
    Then it returns "premium"

  Scenario: Route fill-in answer scoring to local
    Given mode is "hybrid"
    And the task type is "score_answer" with question_type "fill_in"
    When the router classifies the task
    Then it returns "local"

  Scenario: All tasks go local in local-only mode
    Given mode is "local"
    When the router classifies any task type
    Then it always returns "local"

  Scenario: All tasks go premium in premium-only mode
    Given mode is "premium"
    When the router classifies any task type
    Then it always returns "premium"
```
