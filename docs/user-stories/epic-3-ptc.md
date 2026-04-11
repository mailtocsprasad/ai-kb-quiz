# Epic 3: PTC (Process-Then-Communicate)

PTC is a developer-authored pipeline that compresses large KB context before any model call.
Raw KB text is never passed directly to a model — always processed first.

## Story 3.1 — Compress KB context before any model call

```gherkin
Feature: PTC pipeline
  As the quiz engine
  I want to compress large KB context using developer-authored scripts
  So that token usage is minimized and models only receive compact, relevant input

  Scenario: PTC compresses chunks before local model call
    Given KB chunks totaling 6000 tokens are retrieved
    And a task description is "summarize key concepts about SSDT hooking"
    When the PTC pipeline runs
    Then a developer-authored extraction script is executed against the chunks
    And the output is under 800 tokens
    And that compact output is passed to the local model

  Scenario: PTC compresses chunks before premium model call
    Given KB chunks totaling 8000 tokens are retrieved
    And a task description is "generate a code question about LIST_ENTRY traversal"
    When the PTC pipeline runs
    Then the extraction script produces compact structured output
    And that output is handed to Programmable Tool Calling
    And the premium model never sees the raw chunks

  Scenario: PTC compression ratio logged
    Given a PTC pipeline run completes
    Then the session log records:
      | field             | example value |
      | raw_tokens        | 8000          |
      | compressed_tokens | 750           |
      | compression_ratio | 0.91          |
```

## Story 3.2 — PTC always runs before any model call

```gherkin
  Scenario: No model call bypasses PTC
    Given the router selects either local or premium model
    When the model adapter is invoked with KB content
    Then the call always passes through the PTC pipeline first
    And no model adapter ever receives raw KB markdown directly
```
