# Epic 9: Observability

## Story 9.1 — Session logging

```gherkin
Feature: Session observability
  As a developer or user
  I want each session to produce a structured log
  So that I can audit model usage, token costs, and PTC efficiency

  Scenario: Log written after session
    Given a quiz session completes
    Then a JSON log file is written to logs/
    And it contains:
      | field                      |
      | session_id                 |
      | timestamp                  |
      | mode                       |
      | topic                      |
      | questions_asked            |
      | total_score                |
      | per_question_log           |
      | total_tokens_local         |
      | total_tokens_premium       |
      | ptc_compression_ratios     |
      | prog_tool_calling_stats    |

  Scenario: Log survives partial session
    Given a quiz session is in progress
    When an unhandled exception occurs on question 3
    Then questions 1 and 2 are already flushed to the log
    And the log entry for question 3 includes an error field

  Scenario: Token savings displayed after session
    Given a session used PTC and Programmable Tool Calling
    When the session summary is printed
    Then it shows estimated token savings percentage
    And breaks down local vs premium token usage
```
