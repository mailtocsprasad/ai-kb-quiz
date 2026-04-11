# Epic 1: Configuration & Model Setup

## Story 1.1 — Configure model mode

```gherkin
Feature: Model configuration
  As a user
  I want to configure which models are active
  So that I can run the system with local-only, premium-only, or hybrid setup

  Scenario: Local-only mode
    Given config.yaml sets mode to "local"
    And a local model name is specified
    When the quiz engine initializes
    Then all tasks are routed to the local model
    And no premium API calls are made

  Scenario: Premium-only mode
    Given config.yaml sets mode to "premium"
    And an API key is resolvable (env var or key file)
    When the quiz engine initializes
    Then all tasks are routed to the premium model via Programmable Tool Calling
    And no Ollama calls are made

  Scenario: Hybrid mode
    Given config.yaml sets mode to "hybrid"
    And both local model and API key are configured
    When the quiz engine initializes
    Then simple tasks route to the local model
    And complex tasks route to the premium model via Programmable Tool Calling

  Scenario: Missing local model in hybrid mode
    Given config.yaml sets mode to "hybrid"
    And no local model is configured
    When the quiz engine initializes
    Then the engine logs a warning
    And falls back to premium-only mode gracefully

  Scenario: Missing API key in premium mode
    Given config.yaml sets mode to "premium"
    And ANTHROPIC_API_KEY is not set
    And api_key_file does not exist
    When the quiz engine initializes
    Then initialization fails with a clear error message
    And suggests setting ANTHROPIC_API_KEY or creating Claude-Key.txt
```

## Story 1.2 — API key resolution

```gherkin
Feature: API key resolution
  As a user
  I want the API key loaded from env var or a key file
  So that I never hardcode secrets and can reuse a shared key file

  Scenario: Key loaded from environment variable
    Given ANTHROPIC_API_KEY is set in the environment
    When the premium adapter initializes
    Then the key from the environment variable is used
    And api_key_file is not read

  Scenario: Key loaded from configured file path
    Given ANTHROPIC_API_KEY is not set
    And config.yaml sets api_key_file to "C:\Code\ai-kd\Claude-Key.txt"
    And that file contains a valid key
    When the premium adapter initializes
    Then the key from the file is used

  Scenario: Key file path is relative
    Given api_key_file is set to "Claude-Key.txt"
    When the premium adapter initializes
    Then the path is resolved relative to the project root

  Scenario: Neither env var nor key file present
    Given ANTHROPIC_API_KEY is not set
    And the api_key_file does not exist
    When the premium adapter initializes
    Then it raises a clear error listing both resolution methods
```
