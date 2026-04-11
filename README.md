# ai-kb-quiz

> A showcase of hybrid multi-model AI engineering patterns applied to a knowledge base quiz app.

## What it demonstrates

- **Hybrid model routing** — routes tasks to a local CPU model (Ollama) or premium model (Claude) based on complexity and config
- **PTC (Process-Then-Communicate)** — developer-authored scripts compress large KB context before any model call; raw KB text never reaches a premium model
- **Programmable Tool Calling** — premium model generates Python extraction scripts at runtime, executed in a sandbox; only compact output is returned
- **Vectorized KB semantic search** — markdown knowledge base converted to vector embeddings for meaning-based retrieval
- **Optional models** — runs in `local`, `premium`, or `hybrid` mode; graceful degradation if either is absent
- **Extensible KB** — add markdown files, regenerate the index, quiz questions update automatically

## Quick start

```bash
# Install dependencies
pip install -r requirements.txt

# Configure models
cp config/config.example.yaml config/config.yaml
# Edit config.yaml: set mode, local_model, api key env var

# Build the KB vector index
python cli/main.py kb index

# Run a quiz
python cli/main.py quiz --topic "EDR architecture"

# Search the KB
python cli/main.py kb search "kernel callbacks" --top 5
```

## Project layout

```
ai-kb-quiz/
  kb/                    # Markdown knowledge base files
  kb_index/              # Vector index (auto-generated, gitignored)
  engine/
    retriever.py         # Semantic search over KB
    ptc.py               # PTC pipeline: developer-authored extraction scripts
    prog_tool_calling.py # Programmable Tool Calling: model-generated scripts + sandbox exec
    router.py            # Routes tasks to local or premium model
    quiz.py              # Quiz session orchestration
    models/
      adapter.py         # ModelAdapter interface
      local_adapter.py   # Ollama HTTP API
      premium_adapter.py # Anthropic SDK
  cli/
    main.py              # CLI entry point (kb, quiz subcommands)
  config/
    config.example.yaml  # Reference config
  docs/
    specs/               # Design spec (ADD + ATAM)
    patterns/            # PTC and Programmable Tool Calling pattern docs
    user-stories/        # Gherkin user stories by epic
  examples/              # Standalone demos
  tests/                 # Pytest suite (all mockable, no live APIs needed)
  logs/                  # Session JSON logs (gitignored)
```

## Architecture

See [`docs/specs/`](docs/specs/) for the full ADD + ATAM design.

## Patterns documented

- [`docs/patterns/ptc-pattern.md`](docs/patterns/ptc-pattern.md) — Process-Then-Communicate
- [`docs/patterns/programmable-tool-calling.md`](docs/patterns/programmable-tool-calling.md) — Programmable Tool Calling

## Status

- [ ] Design spec (ADD + ATAM)
- [ ] User stories
- [ ] Engine core (retriever, PTC, Programmable Tool Calling, router, quiz)
- [ ] CLI
- [ ] Tests
- [ ] KB content
- [ ] Pattern docs

## License

MIT
