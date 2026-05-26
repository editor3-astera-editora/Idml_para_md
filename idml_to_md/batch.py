"""Fila de conversão IDML → 16 arquivos Markdown em paralelo.

Orquestra a conversão de múltiplos livros descobertos em uma pasta ``Input/``:

- Cada subpasta de ``Input/`` deve conter um arquivo ``.idml`` + o PDF do
  miolo (irmão direto) + a pasta ``Links/`` com assets vinculados.
- Em sucesso, o livro vai para ``FEITOS/<book>/`` e o output fica em
  ``Output/<slug>/unidade_<N>/capitulo_<M>.md`` (16 arquivos por livro) +
  ``Output/<slug>/assets/`` compartilhado.
- Em falha, o livro vai para ``ERROS/<book>/`` com ``_batch_error.json``
  contendo o traceback completo.
- Livros cujo destino já existe (em ``Output``, ``FEITOS`` ou ``ERROS``) são
  pulados — a fila é idempotente.

API principal: :func:`run_batch`. Pensado para ser invocado pelo subcomando
``idml2md batch``.
"""

from __future__ import annotations

import json
import shutil
import sys
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from loguru import logger

from idml_to_md.pipeline import convert_idml
from idml_to_md.utils.slugify import slugify

BatchStatus = Literal["done", "error", "skipped"]


@dataclass(slots=True)
class BatchTask:
    """Uma unidade de trabalho da fila: um livro a ser convertido."""

    book_dir: Path
    idml_path: Path
    slug: str


@dataclass(slots=True)
class BatchResult:
    """Resultado de processar (ou pular) um livro."""

    book_name: str
    slug: str
    status: BatchStatus
    error: str | None = None
    traceback: str | None = None
    report_path: Path | None = None


# ---------------------------------------------------------------------------
# Descoberta
# ---------------------------------------------------------------------------


def discover_books(input_dir: Path) -> list[BatchTask]:
    """Lista livros conversíveis em ``input_dir``.

    Cada subpasta direta deve conter exatamente um ``.idml``. Subpastas sem
    ``.idml`` são puladas com warning. Pastas com mais de um ``.idml`` usam o
    primeiro em ordem alfabética e logam aviso.
    """
    if not input_dir.exists() or not input_dir.is_dir():
        logger.warning("Pasta de input não existe: {}", input_dir)
        return []

    tasks: list[BatchTask] = []
    seen_slugs: dict[str, Path] = {}

    for child in sorted(input_dir.iterdir()):
        if not child.is_dir():
            continue
        idmls = sorted(child.glob("*.idml"))
        if not idmls:
            logger.warning("Pulando '{}': nenhum arquivo .idml encontrado", child.name)
            continue
        if len(idmls) > 1:
            logger.warning(
                "Pasta '{}' contém {} arquivos .idml; usando '{}'",
                child.name,
                len(idmls),
                idmls[0].name,
            )
        idml = idmls[0]
        slug = slugify(idml.stem.replace("_", " ").strip())
        if slug in seen_slugs:
            logger.error(
                "Colisão de slug '{}': '{}' e '{}'. Pulando o segundo.",
                slug,
                seen_slugs[slug].name,
                child.name,
            )
            continue
        seen_slugs[slug] = child
        tasks.append(BatchTask(book_dir=child, idml_path=idml, slug=slug))

    return tasks


def filter_already_done(
    tasks: list[BatchTask],
    output_dir: Path,
    done_dir: Path,
    errors_dir: Path,
) -> tuple[list[BatchTask], list[BatchResult]]:
    """Separa tasks novas dos livros já processados.

    Um livro é considerado "já feito" se qualquer um destes existir:
    - ``output_dir/<slug>/unidade_1/capitulo_1.md`` (qualquer dos 16 arquivos
      finais — usamos o primeiro como sentinela)
    - ``done_dir/<book_dir.name>/``
    - ``errors_dir/<book_dir.name>/``
    """
    pending: list[BatchTask] = []
    skipped: list[BatchResult] = []
    for task in tasks:
        md_target = output_dir / task.slug / "unidade_1" / "capitulo_1.md"
        done_target = done_dir / task.book_dir.name
        error_target = errors_dir / task.book_dir.name
        if md_target.exists():
            reason = f"Output/{task.slug}/ já existe"
        elif done_target.exists():
            reason = f"FEITOS/{task.book_dir.name}/ já existe"
        elif error_target.exists():
            reason = f"ERROS/{task.book_dir.name}/ já existe"
        else:
            pending.append(task)
            continue
        logger.warning("Pulando '{}': {}", task.book_dir.name, reason)
        skipped.append(
            BatchResult(
                book_name=task.book_dir.name,
                slug=task.slug,
                status="skipped",
                error=reason,
            )
        )
    return pending, skipped


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------


def _setup_worker_logging() -> None:
    """Configura loguru no processo worker (sinks não são herdados)."""
    logger.remove()
    logger.add(
        sys.stderr,
        level="INFO",
        format="<level>{level: <7}</level> | [worker] {message}",
    )


def _convert_one(
    book_dir: Path,
    idml_path: Path,
    slug: str,
    output_dir: Path,
    overlay_path: Path | None,
    inkscape_path: Path | None,
) -> BatchResult:
    """Função executada no ProcessPool: converte um único livro.

    O pipeline novo já escreve direto em ``output_dir/<slug>/`` com a estrutura
    final ``unidade_<N>/capitulo_<M>.md`` + ``assets/``. O worker só precisa
    chamar o pipeline e mover o ``_report.json`` para ``FEITOS/<book>/`` no
    final.

    Em qualquer exceção, retorna ``BatchResult(status="error", ...)`` com o
    traceback completo — não levanta para fora do worker.
    """
    _setup_worker_logging()
    try:
        result = convert_idml(
            idml_path=idml_path,
            output_dir=output_dir,
            overlay_path=overlay_path,
            inkscape_path=inkscape_path,
        )

        # O report fica dentro da pasta do livro; vamos copiar para uma área
        # temporária acessível ao orquestrador (para mover para FEITOS depois
        # de a pasta-fonte ser movida).
        report_keep: Path | None = None
        if result.report_path.exists():
            report_keep = output_dir / ".tmp" / f"{slug}_report.json"
            report_keep.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(result.report_path), str(report_keep))

        return BatchResult(
            book_name=book_dir.name,
            slug=slug,
            status="done",
            report_path=report_keep,
        )
    except Exception as exc:  # capturamos tudo de propósito (worker boundary)
        tb = traceback.format_exc()
        logger.error("Falha convertendo '{}': {}", book_dir.name, exc)
        # Limpa output parcial — não queremos meio-livro em Output/.
        partial_out = output_dir / slug
        if partial_out.exists():
            shutil.rmtree(partial_out, ignore_errors=True)
        return BatchResult(
            book_name=book_dir.name,
            slug=slug,
            status="error",
            error=str(exc) or exc.__class__.__name__,
            traceback=tb,
        )


# ---------------------------------------------------------------------------
# Orquestrador
# ---------------------------------------------------------------------------


def run_batch(
    input_dir: Path,
    output_dir: Path,
    done_dir: Path,
    errors_dir: Path,
    overlay_path: Path | None = None,
    workers: int | None = None,
    inkscape_path: Path | None = None,
) -> list[BatchResult]:
    """Roda a fila completa.

    Args:
        input_dir: pasta com subpastas-livro a converter.
        output_dir: destino dos ``.md`` e ``<slug>_assets/``.
        done_dir: destino das pastas-livro convertidas com sucesso.
        errors_dir: destino das pastas-livro que falharam.
        overlay_path: YAML opcional de overlay de estilos.
        workers: número de processos paralelos. Default: ``os.cpu_count()``.
        inkscape_path: caminho explícito do ``inkscape.exe``.

    Returns:
        Lista de :class:`BatchResult` — uma entrada por livro, incluindo os
        pulados.
    """
    input_dir = Path(input_dir).resolve()
    output_dir = Path(output_dir).resolve()
    done_dir = Path(done_dir).resolve()
    errors_dir = Path(errors_dir).resolve()

    output_dir.mkdir(parents=True, exist_ok=True)
    done_dir.mkdir(parents=True, exist_ok=True)
    errors_dir.mkdir(parents=True, exist_ok=True)

    discovered = discover_books(input_dir)
    if not discovered:
        logger.info("Nenhum livro encontrado em {}", input_dir)
        return []

    pending, skipped = filter_already_done(discovered, output_dir, done_dir, errors_dir)
    logger.info(
        "Descoberta: {} livros, {} novos, {} pulados",
        len(discovered),
        len(pending),
        len(skipped),
    )

    results: list[BatchResult] = list(skipped)
    if not pending:
        return results

    max_workers = workers if workers and workers > 0 else None
    logger.info("Iniciando pool com {} worker(s)", max_workers or "auto")

    with ProcessPoolExecutor(max_workers=max_workers) as pool:
        future_to_task = {
            pool.submit(
                _convert_one,
                task.book_dir,
                task.idml_path,
                task.slug,
                output_dir,
                overlay_path,
                inkscape_path,
            ): task
            for task in pending
        }
        for fut in as_completed(future_to_task):
            task = future_to_task[fut]
            try:
                result = fut.result()
            except Exception as exc:  # proteção contra worker quebrado
                tb = traceback.format_exc()
                logger.error("Worker crashou em '{}': {}", task.book_dir.name, exc)
                result = BatchResult(
                    book_name=task.book_dir.name,
                    slug=task.slug,
                    status="error",
                    error=str(exc) or exc.__class__.__name__,
                    traceback=tb,
                )

            _finalize_book(task, result, done_dir, errors_dir)
            results.append(result)

    return results


def _finalize_book(
    task: BatchTask,
    result: BatchResult,
    done_dir: Path,
    errors_dir: Path,
) -> None:
    """Move a pasta-fonte do livro para FEITOS ou ERROS e persiste metadados.

    Roda **sempre no processo principal** depois que o future do worker
    completa — isso evita race conditions de filesystem entre workers.
    """
    if result.status == "done":
        target = done_dir / task.book_dir.name
        if target.exists():
            logger.warning(
                "FEITOS/{} já existe — não vou sobrescrever; livro permanece em Input/",
                task.book_dir.name,
            )
            return
        shutil.move(str(task.book_dir), str(target))
        if result.report_path and result.report_path.exists():
            shutil.move(str(result.report_path), str(target / "_report.json"))
        logger.info("OK  '{}' → FEITOS", task.book_dir.name)
    elif result.status == "error":
        target = errors_dir / task.book_dir.name
        if target.exists():
            logger.warning(
                "ERROS/{} já existe — não vou sobrescrever; livro permanece em Input/",
                task.book_dir.name,
            )
            return
        shutil.move(str(task.book_dir), str(target))
        error_log = target / "_batch_error.json"
        error_log.write_text(
            json.dumps(
                {
                    "book": task.book_dir.name,
                    "idml": task.idml_path.name,
                    "slug": task.slug,
                    "error": result.error,
                    "traceback": result.traceback,
                    "timestamp": datetime.now(UTC).isoformat(),
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        logger.error("ERR '{}' → ERROS ({})", task.book_dir.name, result.error)
