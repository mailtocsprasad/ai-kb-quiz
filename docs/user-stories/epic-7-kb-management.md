# Epic 7: KB Content Management

## Story 7.1 — Add a new KB topic

```gherkin
Feature: KB content management
  As a user
  I want to add new markdown files to the KB
  So that quiz questions can cover new topics over time

  Scenario: Add a new topic file
    Given I create kb/dynamic-programming.md with valid markdown content
    When I run: python cli/main.py kb add kb/dynamic-programming.md
    Then the file is validated (non-empty, valid markdown)
    And a success message confirms the file is ready to index
    And kb list shows the file as "not yet indexed"

  Scenario: Add a file that already exists
    Given kb/edr-architecture.md already exists
    When I run: python cli/main.py kb add kb/edr-architecture.md
    Then the CLI asks "File already exists. Overwrite? [y/N]"
    And proceeds or aborts based on user input

  Scenario: Add a file with unsupported format
    Given I provide a .pdf file path
    When I run: python cli/main.py kb add notes.pdf
    Then the CLI prints "Only .md files are supported"
    And exits with a non-zero code
```

## Story 7.2 — List KB topics

```gherkin
  Scenario: List all topics with index status
    Given the KB contains 5 markdown files
    When I run: python cli/main.py kb list
    Then I see a table:
      | file                      | indexed | chunks | last_modified |
      | edr-architecture.md       | yes     | 12     | 2026-04-10    |
      | windows-internals.md      | yes     | 18     | 2026-03-28    |
      | dynamic-programming.md    | no      | —      | 2026-04-11    |
    And unindexed files are highlighted with a warning
```

## Story 7.3 — Remove a KB topic

```gherkin
  Scenario: Remove a topic
    Given kb/old-topic.md exists and is indexed
    When I run: python cli/main.py kb remove old-topic.md
    Then the CLI asks "This will remove the file and its index entries. Continue? [y/N]"
    And on confirmation the file is deleted
    And its vectors are removed from the index without requiring a full rebuild
```
