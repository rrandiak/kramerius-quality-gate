# The `qg` command line: entry point for the quality gate tools.

from pathlib import Path
from typing import Annotated

import typer

from .generator.corpus import CorpusOptions, write_corpus
from .generator.spec import load_spec

app = typer.Typer(no_args_is_help=True, help="Kramerius quality gate.")


@app.callback()
def main() -> None:
    """Kramerius quality gate."""


@app.command()
def gen(
    spec: Annotated[Path, typer.Option(exists=True, dir_okay=False, help="Corpus spec (YAML).")],
    pages: Annotated[int, typer.Option(min=1, help="Page budget.")],
    out: Annotated[Path, typer.Option(file_okay=False, help="Output directory (new or empty).")],
    seed: Annotated[int, typer.Option(help="Corpus seed.")] = 1,
    created: Annotated[
        str, typer.Option(help="Timestamp written into every object.")
    ] = "2026-01-01T00:00:00.000Z",
) -> None:
    """Generate a synthetic FOXML corpus."""
    summary = write_corpus(
        load_spec(spec), CorpusOptions(seed=seed, pages=pages, created=created), out
    )
    typer.echo(
        f"{summary.pages} pages in {summary.roots} roots, "
        f"{sum(summary.objects.values())} objects -> {out}"
    )
