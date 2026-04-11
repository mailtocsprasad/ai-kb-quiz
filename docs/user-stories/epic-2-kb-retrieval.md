# Epic 2: KB Retrieval

## Story 2.1 — Retrieve relevant KB chunks

```gherkin
Feature: Knowledge base retrieval
  As the quiz engine
  I want to retrieve the most relevant KB chunks for a topic
  So that questions are grounded in actual KB content

  Scenario: Successful retrieval
    Given the KB vector index is built
    And the query is "Windows kernel callback mechanisms"
    When the retriever searches the index
    Then it returns the top 3 chunks ranked by similarity
    And each chunk includes its source file and section heading

  Scenario: Query with no close match
    Given the KB vector index is built
    And the query is "blockchain smart contracts"
    When the retriever searches the index
    Then it returns an empty result set
    And logs "no relevant KB content found for query"

  Scenario: KB index not built
    Given the KB vector index does not exist
    When the retriever is initialized
    Then it raises a clear error
    And prints instructions to run: python cli/main.py kb index
```
