# Epic 6: Quiz Session

## Story 6.1 — Run a quiz session

```gherkin
Feature: Quiz session
  As a user
  I want to answer questions about KB topics
  So that I can test and reinforce my knowledge

  Scenario: Start a quiz session
    Given the quiz engine is configured
    And the topic is "EDR architecture"
    When I run: python cli/main.py quiz --topic "EDR architecture"
    Then I am presented with question 1 of 5 (default)
    And the question is grounded in KB content about EDR architecture
    And the question type (conceptual / code / fill_in) is shown

  Scenario: Correct conceptual answer
    Given I am on a conceptual question
    When I submit a correct answer
    Then I receive a score of 1.0 for that question
    And feedback confirms what I got right
    And the relevant KB excerpt is shown

  Scenario: Incorrect conceptual answer
    Given I am on a conceptual question
    When I submit an incorrect answer
    Then I receive a score of 0.0 for that question
    And the correct answer is displayed clearly
    And an explanation of why it is correct is shown
    And the relevant KB excerpt is shown

  Scenario: Partially correct conceptual answer
    Given a conceptual question expects multiple key concepts
    When I submit an answer covering only some concepts
    Then I receive a partial score (e.g. 0.5)
    And feedback lists which concepts I got right
    And which concepts were missing
    And the full correct answer is shown

  Scenario: Code question presented
    Given a code question is generated
    When the question is displayed
    Then I see a multi-line input prompt (>>>)
    And I can submit multiple lines ending with a blank line
    And a note reminds me the code is evaluated but not executed

  Scenario: Code answer evaluated by premium model
    Given I submit a code answer
    When the premium model evaluates it via Programmable Tool Calling
    Then I receive a score (0.0 / 0.5 / 1.0)
    And feedback explains correctness, logic, and any missing edge cases
    And a reference implementation is shown

  Scenario: Fill-in question
    Given a fill-in question is presented
    When I submit a short answer
    Then the local model scores it via fuzzy / exact match
    And the correct answer is shown regardless of score

  Scenario: Empty KB for topic
    Given the topic is "quantum computing"
    When I start a quiz session
    Then the engine prints "No KB content found for this topic"
    And exits cleanly without error
```

## Story 6.2 — Configurable question count

```gherkin
Feature: Configurable quiz length

  Scenario: Default question count from config
    Given config.yaml sets default_questions to 5
    When I run: python cli/main.py quiz --topic "EDR architecture"
    Then exactly 5 questions are asked

  Scenario: Override question count at runtime
    Given config.yaml sets default_questions to 5
    When I run: python cli/main.py quiz --topic "EDR architecture" --questions 3
    Then exactly 3 questions are asked

  Scenario: Filter question types at runtime
    When I run: python cli/main.py quiz --topic "kernel" --types code,conceptual
    Then only code and fill_in questions are generated
    And fill_in questions are excluded

  Scenario: Requested count exceeds available KB chunks
    Given the topic "eBPF" has only 4 retrievable chunks
    When I run: python cli/main.py quiz --topic "eBPF" --questions 10
    Then the engine generates at most 4 questions
    And prints "Only 4 questions available for this topic"

  Scenario: Invalid question count
    When I run: python cli/main.py quiz --topic "EDR" --questions 0
    Then the CLI prints "Question count must be at least 1"
    And exits with a non-zero code
```

## Story 6.3 — End-of-quiz score summary

```gherkin
Feature: Quiz score summary

  Scenario: Full score summary displayed
    Given I have completed all questions in the session
    Then the CLI displays a per-question table:
      | #  | type        | topic excerpt    | correct | score |
      | 1  | conceptual  | SSDT hooking     | yes     | 1.0   |
      | 2  | code        | LIST_ENTRY walk  | partial | 0.5   |
      | 3  | fill_in     | ETW flags        | no      | 0.0   |
    And a final summary line shows:
      """
      Final Score  : 1.5 / 3  (50%)
      Token savings: 83% via PTC + Programmable Tool Calling
      Models used  : hybrid (local: phi4-mini | premium: claude-sonnet-4-6)
      """

  Scenario: Perfect score
    Given all answers are correct
    Then the summary shows 100% and a congratulatory message

  Scenario: Zero score
    Given all answers are incorrect
    Then the summary shows 0%
    And lists each missed topic with its source KB file for review
```
