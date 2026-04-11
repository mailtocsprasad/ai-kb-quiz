# Epic 10: End-to-End User Journeys

Full user journeys spanning multiple epics, from first setup to completed quiz session.

## Journey 1 — First-time setup and quiz run (hybrid mode)

```gherkin
Feature: First-time user setup and quiz
  As a new user
  I want to go from a fresh clone to a completed quiz session
  So that I can verify the system works end-to-end

  Scenario: Complete first-time setup flow
    Given I have cloned the repo
    And Ollama is installed with phi4-mini pulled
    And I have a valid Claude-Key.txt in the project root

    # Step 1: Configure
    When I run: cp config/config.example.yaml config/config.yaml
    And I set mode to "hybrid" and local_model to "phi4-mini"
    And I set api_key_file to "Claude-Key.txt"

    # Step 2: Install dependencies
    When I run: pip install -r requirements.txt
    Then all dependencies install without error

    # Step 3: Build KB index
    When I run: python cli/main.py kb index
    Then the KB files are chunked and embedded
    And I see a summary of files indexed and chunks created

    # Step 4: Run a quiz
    When I run: python cli/main.py quiz --topic "EDR architecture" --questions 3
    Then I am presented with 3 questions (mix of conceptual, code, fill_in)
    And I can answer each question interactively
    And after each wrong answer the correct answer is shown
    And after completion I see a score summary with token savings stats
```

## Journey 2 — Add a new KB topic and quiz on it

```gherkin
Feature: Expand KB and quiz on new topic
  As a user
  I want to add a new knowledge domain and immediately quiz on it
  So that the system grows with my learning

  Scenario: Add dynamic programming topic and quiz
    Given the system is already set up and indexed

    # Step 1: Create new KB file
    When I create kb/dynamic-programming.md with content about DP algorithms
    And I run: python cli/main.py kb add kb/dynamic-programming.md

    # Step 2: Update index
    When I run: python cli/main.py kb index
    Then only dynamic-programming.md is newly indexed
    And existing topics are unchanged

    # Step 3: Verify searchability
    When I run: python cli/main.py kb search "memoization overlapping subproblems" --top 3
    Then results from dynamic-programming.md appear in the top results

    # Step 4: Quiz on new topic
    When I run: python cli/main.py quiz --topic "dynamic programming" --questions 5
    Then questions are generated from the new KB content
    And I receive correct answers and explanations for wrong responses
    And a score summary is shown at the end
```

## Journey 3 — Local-only mode (no API key, zero cost)

```gherkin
Feature: Local-only quiz with no premium model
  As a user on a restricted network or without an API key
  I want to run a full quiz session using only the local model
  So that I can use the system at zero API cost

  Scenario: Quiz runs entirely on local model
    Given config.yaml sets mode to "local"
    And local_model is set to "phi4-mini"
    And no ANTHROPIC_API_KEY is set
    And no Claude-Key.txt exists

    When I run: python cli/main.py quiz --topic "kernel data structures" --questions 3
    Then the engine initializes without error
    And all question generation, evaluation, and scoring uses the local model
    And no network calls to Anthropic are made
    And I receive a score summary at the end
    And the summary shows "Models used: local only (phi4-mini)"
```

## Journey 4 — Code question end-to-end

```gherkin
Feature: Code question journey
  As a user
  I want to answer a programming question and get meaningful code feedback
  So that I can improve my coding skills on technical topics

  Scenario: Submit code answer and receive evaluation
    Given I am in a quiz session with question_types including "code"
    And a code question is displayed:
      """
      Write a C function to traverse a Windows kernel doubly-linked LIST_ENTRY
      and print each entry's address.
      """

    When I enter my code at the multi-line prompt (>>> ending with blank line):
      """
      void TraverseList(LIST_ENTRY* head) {
          LIST_ENTRY* entry = head->Flink;
          while (entry != head) {
              DbgPrint("Entry: %p\n", entry);
              entry = entry->Flink;
          }
      }
      """
    And I submit with a blank line

    Then the premium model evaluates my code via Programmable Tool Calling
    And I receive feedback covering:
      | aspect                        |
      | correctness of traversal logic |
      | termination condition          |
      | missing null checks (if any)  |
      | reference implementation       |
    And a score of 0.0 / 0.5 / 1.0 is awarded
    And the session log records premium tokens used for this evaluation
```

## Journey 5 — Review missed topics after quiz

```gherkin
Feature: Post-quiz review
  As a user
  I want to see which topics I missed and where to find them in the KB
  So that I can go back and study before retrying

  Scenario: Zero score triggers KB review suggestions
    Given I complete a quiz session with 2 incorrect answers
    When the score summary is displayed
    Then each incorrect question shows:
      | field           |
      | correct answer  |
      | source KB file  |
      | source heading  |
    And a tip is shown: "Run 'python cli/main.py kb search <topic>' to explore further"
```
