"""ai-kb-quiz CLI — KB management and interactive study commands."""
import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional

import typer
import yaml

from engine.embedder import make_embed_fn
from engine.retriever import Retriever, IndexNotFoundError

app = typer.Typer(help="ai-kb-quiz — KB-grounded quiz and interactive learning")
kb_app = typer.Typer(help="KB management commands")
app.add_typer(kb_app, name="kb")

_DEFAULT_CONFIG = Path("config/config.yaml")

_LEARN_SYSTEM_PROMPT = (
    "You are a technical tutor explaining concepts from a knowledge base. "
    "Give a thorough, well-structured explanation. "
    "Use numbered steps or bullet points where they aid clarity. "
    "Include specific technical details, values, and examples from the content. "
    "Do not summarise — teach."
)


def _load_config(config_path: Path = _DEFAULT_CONFIG) -> dict:
    if not config_path.exists():
        typer.echo(
            f"Config not found: {config_path}. "
            f"Copy config/config.example.yaml to {config_path}."
        )
        raise typer.Exit(code=1)
    return yaml.safe_load(config_path.read_text(encoding="utf-8"))


def _gemini_api_key(cfg: dict) -> str:
    import os
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        key_file = Path(cfg.get("gemini_api_key_file", "Gemini-Key.txt"))
        if key_file.exists():
            lines = key_file.read_text().splitlines()
            key = next((l.strip() for l in lines if l.strip().startswith("AIza")), "")
    if not key:
        raise EnvironmentError(
            "No Gemini API key found for embedding. "
            "Set GEMINI_API_KEY or configure gemini_api_key_file in config.yaml."
        )
    return key


def _detect_embedding_backend(cfg: dict) -> tuple[str, str, int | None]:
    """Probe available backends in priority order: gemini → ollama → sentence-transformers.

    Returns (backend, model, dimensions). dimensions is None for non-gemini backends
    because their output size is fixed by the model, not a configurable parameter.
    """
    import os
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        key_file = Path(cfg.get("gemini_api_key_file", "Gemini-Key.txt"))
        if key_file.exists():
            lines = key_file.read_text().splitlines()
            key = next((l.strip() for l in lines if l.strip().startswith("AIza")), "")
    if key:
        return (
            "gemini",
            cfg.get("gemini_embedding_model", "gemini-embedding-001"),
            cfg.get("embedding_dimensions", 768),
        )

    try:
        import httpx
        resp = httpx.get("http://localhost:11434/api/tags", timeout=2.0)
        if resp.status_code == 200:
            return ("ollama", cfg.get("embedding_model", "nomic-embed-text"), None)
    except Exception:
        pass

    return ("sentence-transformers", cfg.get("embedding_model", "all-MiniLM-L6-v2"), None)


def _resolve_backend(cfg: dict) -> dict:
    """If embedding_backend is 'auto', resolve to a concrete backend via the lock file.

    Reads the lock if it exists. Detects and writes the lock on first call.
    Returns a cfg dict with embedding_backend set to a concrete value.
    """
    if cfg.get("embedding_backend") != "auto":
        return cfg

    from engine.backend_lock import read_lock, write_lock
    lock = read_lock()
    if not lock:
        backend, model, dims = _detect_embedding_backend(cfg)
        write_lock(backend, model, dims)
        lock = {"backend": backend, "model": model, "dimensions": dims}
        typer.echo(f"[auto] Embedding backend: {backend} ({model})")

    resolved = dict(cfg)
    resolved["embedding_backend"] = lock["backend"]
    if lock["backend"] == "gemini":
        resolved["gemini_embedding_model"] = lock["model"]
        resolved["embedding_dimensions"] = lock["dimensions"]
    else:
        resolved["embedding_model"] = lock["model"]
    return resolved


def _make_embed_fn(cfg: dict, task_type: str = "RETRIEVAL_DOCUMENT"):
    """Create an embed function from config. task_type only applies to the gemini backend."""
    cfg = _resolve_backend(cfg)
    backend = cfg.get("embedding_backend", "sentence-transformers")
    model = cfg.get("embedding_model", "all-MiniLM-L6-v2")
    if backend == "gemini":
        return make_embed_fn(
            model=cfg.get("gemini_embedding_model", "gemini-embedding-001"),
            backend="gemini",
            task_type=task_type,
            api_key=_gemini_api_key(cfg),
            output_dimensionality=cfg.get("embedding_dimensions", 768),
        )
    return make_embed_fn(model=model, backend=backend)


def _index_dir_for(cfg: dict) -> Path:
    """Per-backend index directory — switching backends never requires a rebuild."""
    slug = cfg.get("embedding_backend", "sentence-transformers").replace("-", "_")
    return Path("kb_index") / slug


def _make_retriever(cfg: dict) -> Retriever:
    cfg = _resolve_backend(cfg)
    # Queries use RETRIEVAL_QUERY so the vector hunts for answers, not similar phrasing.
    embed_fn = _make_embed_fn(cfg, task_type="RETRIEVAL_QUERY")
    return Retriever(index_dir=_index_dir_for(cfg), embed_fn=embed_fn)


# ---------------------------------------------------------------------------
# kb index
# ---------------------------------------------------------------------------

@kb_app.command("index")
def kb_index(rebuild: bool = typer.Option(False, "--rebuild", help="Force full rebuild")):
    """Build or update the KB vector index."""
    from engine.indexer import Indexer

    cfg = _resolve_backend(_load_config())
    # Indexing uses RETRIEVAL_DOCUMENT so chunks advertise their informational payload.
    embed_fn = _make_embed_fn(cfg, task_type="RETRIEVAL_DOCUMENT")
    kb_dir = Path("kb")
    kb_dir.mkdir(exist_ok=True)
    indexer = Indexer(kb_dir=kb_dir, index_dir=_index_dir_for(cfg), embed_fn=embed_fn)
    typer.echo("Building KB index...")
    if rebuild:
        indexer.build_full()
        typer.echo("Full rebuild complete.")
    else:
        indexer.build_incremental()
        typer.echo("Incremental index update complete.")


# ---------------------------------------------------------------------------
# kb list
# ---------------------------------------------------------------------------

@kb_app.command("list")
def kb_list():
    """List KB files and their index status."""
    import json

    kb_dir = Path("kb")
    if not kb_dir.exists():
        typer.echo("kb/ directory not found.")
        raise typer.Exit(code=1)

    cfg = _resolve_backend(_load_config())
    backend = cfg.get("embedding_backend", "sentence-transformers")
    manifest_path = _index_dir_for(cfg) / "manifest.json"
    indexed: set[str] = set()
    if manifest_path.exists():
        data = json.loads(manifest_path.read_text())
        for k in data:
            p = Path(k)
            try:
                indexed.add(str(p.relative_to(kb_dir)))
            except ValueError:
                indexed.add(p.name)

    typer.echo(f"[backend: {backend}]")
    typer.echo(f"{'File':<65} {'Indexed':<10} {'Last Modified'}")
    typer.echo("-" * 90)
    for f in sorted(kb_dir.rglob("*.md")):
        rel = str(f.relative_to(kb_dir))
        status = "yes" if rel in indexed else "no"
        mdate = datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d")
        warn = "" if status == "yes" else " ⚠"
        typer.echo(f"{rel:<65} {status:<10} {mdate}{warn}")


# ---------------------------------------------------------------------------
# kb add
# ---------------------------------------------------------------------------

@kb_app.command("add")
def kb_add(
    filepath: str = typer.Argument(..., help="Path to .md file to add"),
    subdir: Optional[str] = typer.Option(None, "--subdir", help="Subdirectory within kb/ (e.g. windows-kernel)"),
):
    """Add a markdown file to the KB."""
    src = Path(filepath)
    if src.suffix != ".md":
        typer.echo("Only .md files are supported.")
        raise typer.Exit(code=1)
    kb_dir = Path("kb")
    kb_dir.mkdir(exist_ok=True)
    target_dir = kb_dir / subdir if subdir else kb_dir
    target_dir.mkdir(parents=True, exist_ok=True)
    dest = target_dir / src.name
    if dest.exists():
        if not typer.confirm(f"{dest} already exists. Overwrite?", default=False):
            raise typer.Exit(code=0)
    shutil.copy2(src, dest)
    typer.echo(f"Added {dest}. Run 'python cli/main.py kb index' to index it.")


# ---------------------------------------------------------------------------
# kb remove
# ---------------------------------------------------------------------------

@kb_app.command("remove")
def kb_remove(filename: str = typer.Argument(..., help="Filename to remove from kb/")):
    """Remove a KB file (index will need a rebuild to reflect deletion)."""
    target = Path("kb") / filename
    if not target.exists():
        typer.echo(f"{target} not found.")
        raise typer.Exit(code=1)
    if not typer.confirm(
        f"Remove {target} and its index entries?", default=False
    ):
        raise typer.Exit(code=0)
    target.unlink()
    typer.echo(f"Removed {target}. Run 'python cli/main.py kb index --rebuild' to update index.")


# ---------------------------------------------------------------------------
# kb search
# ---------------------------------------------------------------------------

@kb_app.command("search")
def kb_search(
    query: str = typer.Argument(...),
    top: int = typer.Option(5, "--top", help="Number of results"),
):
    """Semantic search over the KB."""
    cfg = _load_config()
    try:
        retriever = _make_retriever(cfg)
    except IndexNotFoundError:
        typer.echo("Index is empty. Run: python cli/main.py kb index")
        raise typer.Exit(code=1)

    results = retriever.search(query, top_k=top)
    if not results:
        typer.echo("No results found.")
        return
    for i, chunk in enumerate(results, 1):
        typer.echo(f"\n[{i}] {chunk.source_file} — {chunk.heading}")
        typer.echo(f"    {chunk.text[:200]}...")


# ---------------------------------------------------------------------------
# kb learn
# ---------------------------------------------------------------------------

@kb_app.command("learn")
def kb_learn(
    topic: str = typer.Argument(..., help="Topic to learn about"),
    depth: str = typer.Option("shallow", "--depth", help="shallow (local) or deep (premium)"),
    top: int = typer.Option(5, "--top", help="Number of KB chunks to retrieve"),
    debug: bool = typer.Option(False, "--debug", help="Show timing debug logs"),
):
    """Interactive study session: explanation + follow-up REPL.

    User story: 7.4 — Explain a KB topic then enter a REPL for follow-up
    questions. Choose numbered suggestions, type your own question, 'quiz',
    or 'quit' to exit.
    """
    if debug:
        logging.basicConfig(
            level=logging.DEBUG,
            format="  %(name)s %(message)s",
        )

    from engine.learn import LearnSession
    from engine.models.local_adapter import LocalAdapter
    from engine.models.premium_adapter import PremiumAdapter
    from engine.store import VectorStore

    cfg = _resolve_backend(_load_config())
    try:
        retriever = _make_retriever(cfg)
    except IndexNotFoundError:
        typer.echo("Index is empty. Run: python cli/main.py kb index")
        raise typer.Exit(code=1)

    local = LocalAdapter(model=cfg.get("local_model", "phi4-mini"))
    is_deep = False
    if depth == "deep":
        provider = cfg.get("premium_provider", "anthropic")
        try:
            if provider == "gemini":
                from engine.models.gemini_adapter import GeminiAdapter
                premium: object = GeminiAdapter.from_config(
                    model=cfg.get("gemini_model", "gemini-2.5-flash"),
                    api_key_file=Path(cfg.get("gemini_api_key_file", "Gemini-Key.txt")),
                    system_prompt=_LEARN_SYSTEM_PROMPT,
                )
            else:
                premium = PremiumAdapter.from_config(
                    model=cfg.get("premium_model", "claude-sonnet-4-6"),
                    api_key_file=Path(cfg.get("api_key_file", "Claude-Key.txt")),
                    system_prompt=_LEARN_SYSTEM_PROMPT,
                )
            is_deep = True
        except EnvironmentError as e:
            typer.echo(f"Premium model unavailable ({e}) — falling back to local.")
            premium = local
    else:
        premium = local

    # Storage embed fn uses RETRIEVAL_DOCUMENT — generated chunks go back into the index.
    # Only created in deep mode to avoid an unnecessary API client in local mode.
    store_embed_fn = _make_embed_fn(cfg, task_type="RETRIEVAL_DOCUMENT") if is_deep else None
    store = VectorStore(_index_dir_for(cfg) / "chroma") if is_deep else None

    session = LearnSession(
        topic=topic,
        retriever=retriever,
        adapter=premium,
        suggest_adapter=local,
        refine_adapter=None,
        embed_fn=store_embed_fn,
        store=store,
    )

    typer.echo(f"\n{'='*60}")
    typer.echo(f"  Topic: {topic}  [{depth}]")
    typer.echo(f"{'='*60}\n")

    explanation, chunks = session.explain(top_k=top)
    if not explanation:
        typer.echo(f"No KB content found for '{topic}'.")
        raise typer.Exit(code=0)

    model_tag = "(premium)" if depth == "deep" else "(local)"
    typer.echo(f"{explanation}\n{model_tag}")
    _print_sources(chunks)

    last_chunks = chunks
    last_query = topic
    last_answer = explanation
    tokens_used = len(explanation) // 4

    try:
        while True:
            suggestions = session.suggest(last_chunks, last_query, context=last_answer)
            _print_suggestions(suggestions)

            raw = typer.prompt("\nAsk a follow-up (1-3, your own question, 'quiz', or 'quit')")
            user_input = raw.strip()

            if user_input.lower() in ("quit", "exit", "q"):
                typer.echo(f"\nSession ended. Tokens used (approx): {tokens_used}")
                break

            if user_input.lower() == "quiz":
                typer.echo(f"\nQuiz yourself: python cli/main.py quiz --topic '{topic}'")
                break

            if user_input.isdigit():
                idx = int(user_input) - 1
                if suggestions and 0 <= idx < len(suggestions):
                    user_input = suggestions[idx]
                    typer.echo(f"  → {user_input}")
                else:
                    typer.echo(f"  Please enter a number between 1 and {len(suggestions) or 1}.")
                    continue

            answer, new_chunks = session.follow_up(user_input)
            if not answer:
                typer.echo("No KB content found for that question. Try a different phrasing.")
                continue

            typer.echo(f"\n{answer}\n{model_tag}")
            _print_sources(new_chunks)
            tokens_used += len(answer) // 4
            last_chunks = new_chunks
            last_query = user_input
            last_answer = answer

    except KeyboardInterrupt:
        typer.echo(f"\n\nSession ended. Tokens used (approx): {tokens_used}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _print_sources(chunks) -> None:
    if not chunks:
        return
    typer.echo(f"\n{'-'*60}")
    typer.echo("Sources:")
    seen: set[str] = set()
    for c in chunks:
        key = f"{c.source_file} › {c.heading}"
        if key not in seen:
            typer.echo(f"  • {key}")
            seen.add(key)


def _print_suggestions(suggestions: list[str]) -> None:
    if not suggestions:
        return
    typer.echo(f"\n{'-'*60}")
    typer.echo("Suggested follow-ups:")
    for i, s in enumerate(suggestions, 1):
        typer.echo(f"  [{i}] {s}")


if __name__ == "__main__":
    app()
