# Epic 8: Vector Index Management

## Story 8.1 — Build the vector index

```gherkin
Feature: Vector index management
  As a user
  I want KB markdown files converted to vector embeddings
  So that the quiz engine can perform semantic search over topics

  Scenario: Full index build
    Given kb/ contains 5 markdown files
    And no index exists at kb_index/
    When I run: python cli/main.py kb index --rebuild
    Then each file is chunked by heading (H2/H3 boundaries)
    And each chunk is embedded using the local embedding model
    And all vectors are saved to kb_index/
    And a summary prints:
      | field         | value            |
      | files indexed | 5                |
      | total chunks  | 47               |
      | model used    | all-MiniLM-L6-v2 |
      | time taken    | 12.3s            |

  Scenario: Incremental index update
    Given an index exists with 4 files indexed
    And kb/dynamic-programming.md was added and is not yet indexed
    When I run: python cli/main.py kb index
    Then only dynamic-programming.md is embedded and added to the index
    And existing entries are not recomputed
    And the summary shows "1 file added, 4 unchanged"

  Scenario: Index is stale (file modified after indexing)
    Given kb/edr-architecture.md was modified after last index build
    When I run: python cli/main.py kb index
    Then the CLI detects the mtime difference
    And re-indexes only edr-architecture.md
    And prints "1 file updated, 4 unchanged"

  Scenario: Force full rebuild
    Given an index already exists
    When I run: python cli/main.py kb index --rebuild
    Then all files are re-embedded regardless of mtime
    And the old index is replaced atomically (write to temp dir, then swap)

  Scenario: Embedding model not available
    Given the embedding model is not downloaded
    When I run: python cli/main.py kb index
    Then the CLI prints the model name and download instructions
    And exits with a non-zero code

  Scenario: Index build interrupted mid-way
    Given indexing starts for 5 files
    When the process is killed after 3 files
    Then the partial index is discarded (atomic write not committed)
    And a clean re-run indexes all 5 files successfully
```

## Story 8.2 — Semantic search over KB

```gherkin
Feature: Semantic KB search

  Scenario: Semantic query matches related content
    Given the KB is indexed
    And the query is "how EDR hooks system calls"
    When the retriever runs a semantic search
    Then results include chunks about SSDT hooking and kernel callbacks
    Even if those chunks do not contain the exact phrase "hooks system calls"
    And results are ranked by cosine similarity score

  Scenario: Search with top-K parameter
    Given the KB is indexed
    When I run: python cli/main.py kb search "process injection" --top 5
    Then exactly 5 chunks are returned
    And each result shows:
      | field       |
      | rank        |
      | score       |
      | source file |
      | heading     |
      | excerpt     |

  Scenario: Search when index is empty
    Given no files have been indexed
    When I run: python cli/main.py kb search "any query"
    Then the CLI prints "Index is empty. Run: python cli/main.py kb index"
```
