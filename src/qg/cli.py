# The `qg` command line: entry point for the quality gate tools.

from pathlib import Path
from typing import Annotated

import typer
import yaml

from .benchmark import evaluate, report, run
from .generator.corpus import CorpusOptions, write_corpus
from .generator.spec import load_spec
from .traces import attach

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


@app.command()
def bench(
    corpus: Annotated[Path, typer.Option(exists=True, file_okay=False)],
    out: Annotated[Path, typer.Option(help="New run directory.")],
    base_url: Annotated[
        str, typer.Option(help="Loopback port-forward to Kramerius.")
    ] = "http://127.0.0.1:8080",
    iterations: Annotated[int, typer.Option(min=1)] = 10,
    concurrency: Annotated[int, typer.Option(min=1)] = 1,
    cache_state: Annotated[
        str, typer.Option(help="Record cold, warm, or explicit reset procedure.")
    ] = "warm",
    scenarios: Annotated[
        str, typer.Option(help="Comma-separated scenario names.")
    ] = "search,thumb",
    timeout: Annotated[float, typer.Option(min=0.1)] = 30.0,
    config: Annotated[Path | None, typer.Option(exists=True, dir_okay=False)] = Path(
        "local/values.yaml"
    ),
    gates: Annotated[Path | None, typer.Option(exists=True, dir_okay=False)] = None,
    kube_context: Annotated[str, typer.Option(help="Pinned local Kubernetes context.")] = "k3d-qg",
) -> None:
    """Run real HTTP requests through a local Kramerius port-forward."""
    try:
        result = run(
            corpus,
            base_url,
            out,
            iterations=iterations,
            concurrency=concurrency,
            cache_state=cache_state,
            scenarios=scenarios.split(","),
            timeout=timeout,
            config=config,
            kube_context=kube_context,
        )
        typer.echo(report(result))
        if gates:
            failures = evaluate(result, yaml.safe_load(gates.read_text()) or {})
            for failure in failures:
                typer.echo(f"FAIL: {failure}", err=True)
            if failures:
                raise typer.Exit(1)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc


@app.command()
def compare(
    baseline: Annotated[Path, typer.Argument(exists=True, dir_okay=False)],
    candidate: Annotated[Path, typer.Argument(exists=True, dir_okay=False)],
) -> None:
    """Compare two run.json files; environment differences are printed first."""
    import json

    before = json.loads(baseline.read_text())
    after = json.loads(candidate.read_text())
    for key in sorted(set(before["fingerprint"]) | set(after["fingerprint"])):
        if before["fingerprint"].get(key) != after["fingerprint"].get(key):
            typer.echo(f"fingerprint changed: {key}")
    typer.echo("| Scenario | Baseline p95 ms | Candidate p95 ms | Delta % |")
    typer.echo("|---|---:|---:|---:|")
    for name in sorted(set(before["summary"]) & set(after["summary"])):
        old = before["summary"][name]["p95_ms"]
        new = after["summary"][name]["p95_ms"]
        delta = f"{(new / old - 1) * 100:+.1f}" if old else "n/a"
        typer.echo(f"| {name} | {old} | {new} | {delta} |")


@app.command()
def traces(
    run_file: Annotated[Path, typer.Argument(exists=True, dir_okay=False)],
    otlp_jsonl: Annotated[Path, typer.Argument(exists=True, dir_okay=False)],
) -> None:
    """Attach collector spans to a run using request trace IDs."""
    result = attach(run_file, otlp_jsonl)
    typer.echo(
        f"matched {result['trace_coverage']['matched']} of {result['trace_coverage']['requests']} traces"
    )
