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


def _load_config(config_path: Path = _DEFAULT_CONFIG) -> dict:
    if not config_path.exists():
        typer.echo(
            f"Config not found: {config_path}. "
            f"Copy config/config.example.yaml to {config_path}."
        )
        raise typer.Exit(code=1)
    return yaml.safe_load(config_path.read_text(encoding="utf-8"))


def _make_retriever(cfg: dict) -> Retriever:
    embed_fn = make_embed_fn(
        model=cfg.get("embedding_model", "all-MiniLM-L6-v2"),
        backend=cfg.get("embedding_backend", "sentence-transformers"),
    )
    return Retriever(index_dir=Path("kb_index"), embed_fn=embed_fn)


# ---------------------------------------------------------------------------
# kb index
# ---------------------------------------------------------------------------

@kb_app.command("index")
def kb_index(rebuild: bool = typer.Option(False, "--rebuild", help="Force full rebuild")):
    """Build or update the KB vector index."""
    from engine.indexer import Indexer

    cfg = _load_config()
    embed_fn = make_embed_fn(
        model=cfg.get("embedding_model", "all-MiniLM-L6-v2"),
        backend=cfg.get("embedding_backend", "sentence-transformers"),
    )
    kb_dir = Path("kb")
    kb_dir.mkdir(exist_ok=True)
    indexer = Indexer(kb_dir=kb_dir, index_dir=Path("kb_index"), embed_fn=embed_fn)
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

    manifest_path = Path("kb_index/manifest.json")
    indexed: set[str] = set()
    if manifest_path.exists():
        data = json.loads(manifest_path.read_text())
        indexed = {Path(k).name for k in data}

    typer.echo(f"{'File':<35} {'Indexed':<10} {'Last Modified'}")
    typer.echo("-" * 65)
    for f in sorted(kb_dir.glob("*.md")):
        status = "yes" if f.name in indexed else "no"
        mdate = datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d")
        warn = "" if status == "yes" else " ⚠"
        typer.echo(f"{f.name:<35} {status:<10} {mdate}{warn}")


# ---------------------------------------------------------------------------
# kb add
# ---------------------------------------------------------------------------

@kb_app.command("add")
def kb_add(filepath: str = typer.Argument(..., help="Path to .md file to add")):
    """Add a markdown file to the KB."""
    src = Path(filepath)
    if src.suffix != ".md":
        typer.echo("Only .md files are supported.")
        raise typer.Exit(code=1)
    kb_dir = Path("kb")
    kb_dir.mkdir(exist_ok=True)
    dest = kb_dir / src.name
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

    cfg = _load_config()
    embed_fn = make_embed_fn(
        model=cfg.get("embedding_model", "all-MiniLM-L6-v2"),
        backend=cfg.get("embedding_backend", "sentence-transformers"),
    )
    try:
        retriever = _make_retriever(cfg)
    except IndexNotFoundError:
        typer.echo("Index is empty. Run: python cli/main.py kb index")
        raise typer.Exit(code=1)

    local = LocalAdapter(model=cfg.get("local_model", "phi4-mini"))
    refine_adapter = None
    if depth == "deep":
        try:
            premium: object = PremiumAdapter.from_config(
                model=cfg.get("premium_model", "claude-sonnet-4-6"),
                api_key_file=Path(cfg.get("api_key_file", "Claude-Key.txt")),
            )
            refine_adapter = premium
        except EnvironmentError:
            typer.echo("Premium model unavailable — falling back to local.")
            premium = local
    else:
        premium = local

    store = VectorStore(Path("kb_index/chroma")) if refine_adapter else None

    session = LearnSession(
        topic=topic,
        retriever=retriever,
        adapter=premium,
        suggest_adapter=local,
        refine_adapter=refine_adapter,
        embed_fn=embed_fn if refine_adapter else None,
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
    typer.echo(f"\n{'─'*60}")
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
    typer.echo(f"\n{'─'*60}")
    typer.echo("Suggested follow-ups:")
    for i, s in enumerate(suggestions, 1):
        typer.echo(f"  [{i}] {s}")


if __name__ == "__main__":
    app()
