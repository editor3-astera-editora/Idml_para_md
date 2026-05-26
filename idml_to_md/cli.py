"""Entry-point CLI (Typer)."""

from __future__ import annotations

import sys
from pathlib import Path

import typer
from loguru import logger
from rich.console import Console
from rich.table import Table

from idml_to_md import __version__
from idml_to_md.batch import BatchResult, run_batch
from idml_to_md.pipeline import convert_idml, inspect_styles

app = typer.Typer(
    name="idml2md",
    help="Converte livros do Adobe InDesign (.idml) para Markdown estruturado.",
    no_args_is_help=True,
)
console = Console()


def _setup_logging(verbose: bool) -> None:
    logger.remove()
    level = "DEBUG" if verbose else "INFO"
    logger.add(sys.stderr, level=level, format="<level>{level: <7}</level> | {message}")


@app.command()
def version() -> None:
    """Mostra a versão instalada."""
    typer.echo(__version__)


@app.command()
def convert(
    idml_path: Path = typer.Argument(..., exists=True, dir_okay=False, readable=True),
    output_dir: Path = typer.Option(
        Path("out"), "--output", "-o", file_okay=False, help="Pasta-pai do output."
    ),
    overlay: Path | None = typer.Option(
        None, "--config", "-c", exists=True, dir_okay=False, help="YAML overlay de estilos."
    ),
    title: str | None = typer.Option(
        None, "--title", "-t", help="Título do livro. Default: nome do arquivo."
    ),
    links: Path | None = typer.Option(
        None, "--links", file_okay=False, help='Pasta Links/. Default: "<idml>/../Links".'
    ),
    inkscape: Path | None = typer.Option(
        None,
        "--inkscape",
        exists=True,
        dir_okay=False,
        help="Caminho do inkscape.exe (override de PATH e IDML2MD_INKSCAPE_PATH).",
    ),
    pdf: Path | None = typer.Option(
        None,
        "--pdf",
        exists=True,
        dir_okay=False,
        readable=True,
        help='PDF do miolo. Default: primeiro ".pdf" irmão do .idml.',
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Converte um IDML + PDF em 16 arquivos Markdown (4 unidades × 4 capítulos)."""
    _setup_logging(verbose)
    result = convert_idml(
        idml_path=idml_path,
        output_dir=output_dir,
        overlay_path=overlay,
        book_title=title,
        links_dir=links,
        inkscape_path=inkscape,
        pdf_path=pdf,
    )
    console.print(f"[green]OK[/] {len(result.markdown_paths)} arquivos em {result.output_dir}")
    console.print(f"[dim]report:[/] {result.report_path}")
    console.print(f"[dim]pdf offset:[/] {result.pdf_offset}")
    if result.report.unmapped_paragraph_styles:
        n = len(result.report.unmapped_paragraph_styles)
        console.print(f"[yellow]Aviso:[/] {n} ParagraphStyles não mapeados (ver report)")
    if result.report.missing_assets:
        console.print(f"[yellow]Aviso:[/] {len(result.report.missing_assets)} assets faltando")


@app.command()
def inspect(
    idml_path: Path = typer.Argument(..., exists=True, dir_okay=False, readable=True),
    top: int = typer.Option(0, "--top", help="Mostrar apenas os N mais usados. 0 = todos."),
) -> None:
    """Lista ParagraphStyles encontrados no IDML, com contagem de uso."""
    counts = inspect_styles(idml_path)
    items = counts.most_common(top or None)

    table = Table(title=f"ParagraphStyles em {idml_path.name}")
    table.add_column("Estilo", overflow="fold")
    table.add_column("Uso", justify="right")
    for name, n in items:
        table.add_row(name, str(n))
    console.print(table)
    console.print(f"[dim]Total de estilos distintos:[/] {len(counts)}")


@app.command()
def batch(
    input_dir: Path = typer.Option(
        Path("Input"), "--input", "-i", file_okay=False, help="Pasta com subpastas-livro."
    ),
    output_dir: Path = typer.Option(
        Path("Output"),
        "--output",
        "-o",
        file_okay=False,
        help="Destino dos .md e <slug>_assets/.",
    ),
    done_dir: Path = typer.Option(
        Path("FEITOS"),
        "--done",
        file_okay=False,
        help="Destino das pastas-livro convertidas com sucesso.",
    ),
    errors_dir: Path = typer.Option(
        Path("ERROS"),
        "--errors",
        file_okay=False,
        help="Destino das pastas-livro que falharam.",
    ),
    overlay: Path | None = typer.Option(
        None, "--config", "-c", exists=True, dir_okay=False, help="YAML overlay de estilos."
    ),
    workers: int | None = typer.Option(
        None, "--workers", "-w", help="Processos paralelos. Default: nº de CPUs."
    ),
    inkscape: Path | None = typer.Option(
        None,
        "--inkscape",
        exists=True,
        dir_okay=False,
        help="Caminho explícito do inkscape.exe.",
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Converte todos os livros de uma pasta em paralelo (fila idempotente)."""
    _setup_logging(verbose)
    results = run_batch(
        input_dir=input_dir,
        output_dir=output_dir,
        done_dir=done_dir,
        errors_dir=errors_dir,
        overlay_path=overlay,
        workers=workers,
        inkscape_path=inkscape,
    )
    _print_batch_summary(results)
    has_errors = any(r.status == "error" for r in results)
    raise typer.Exit(code=1 if has_errors else 0)


def _print_batch_summary(results: list[BatchResult]) -> None:
    """Imprime tabela Rich com o resumo da fila."""
    if not results:
        console.print("[yellow]Nenhum livro processado.[/]")
        return

    table = Table(title="Resumo da fila")
    table.add_column("Livro", overflow="fold")
    table.add_column("Status")
    table.add_column("Detalhe", overflow="fold")

    style_for = {"done": "green", "error": "red", "skipped": "yellow"}
    label_for = {"done": "OK", "error": "ERRO", "skipped": "SKIP"}

    for r in sorted(results, key=lambda x: (x.status, x.book_name)):
        detail = r.error or ""
        table.add_row(
            r.book_name,
            f"[{style_for[r.status]}]{label_for[r.status]}[/]",
            detail,
        )

    console.print(table)
    totals = {
        "done": sum(1 for r in results if r.status == "done"),
        "error": sum(1 for r in results if r.status == "error"),
        "skipped": sum(1 for r in results if r.status == "skipped"),
    }
    console.print(
        f"[green]{totals['done']} OK[/]  "
        f"[red]{totals['error']} erros[/]  "
        f"[yellow]{totals['skipped']} pulados[/]"
    )


if __name__ == "__main__":  # pragma: no cover
    app()
