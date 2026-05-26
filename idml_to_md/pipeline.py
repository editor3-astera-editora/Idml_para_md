"""Orquestrador da conversão IDML → 16 arquivos Markdown (4 unidades × 4 capítulos).

Fluxo:

1. Abre o IDML.
2. Resolve a ordem de leitura das Stories (``thread_resolver``).
3. ``story_walker`` extrai blocos + front matter + referências.
4. ``asset_processor`` copia imagens raster e converte vetoriais.
5. ``md_writer`` serializa o ``Document`` em uma string Markdown ÚNICA.
6. ``toc_parser`` extrai do IDML o manifesto canônico (4 unidades × 4 capítulos).
7. ``pdf_anchors`` extrai do PDF do miolo as primeiras palavras de cada
   página inicial de capítulo (anchors).
8. ``book_splitter`` particiona a string Markdown nos 16 chunks.
9. Grava ``unidade_<N>/capitulo_<M>.md`` (16 arquivos) + ``_report.json``.

Capa, sumário e referências são DESCARTADOS — só os 16 chunks de capítulo
viram arquivo.

API:

>>> from pathlib import Path
>>> from idml_to_md.pipeline import convert_idml
>>> result = convert_idml(Path("livro.idml"), Path("out"))
>>> len(result.markdown_paths)
16
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from loguru import logger

from idml_to_md.asset_processor import process_raster_assets, process_vector_assets
from idml_to_md.book_splitter import ChapterSplitError, split_markdown
from idml_to_md.idml_reader import IDMLDocument
from idml_to_md.mathml_to_latex import EquationConverter
from idml_to_md.md_writer import render_document
from idml_to_md.models import Document, ImageBlock
from idml_to_md.pdf_anchors import (
    BookAnchors,
    PdfAnchorError,
    extract_anchors,
    find_pdf_sibling,
)
from idml_to_md.report import ConversionReport, build_report
from idml_to_md.story_walker import walk_story
from idml_to_md.style_mapper import build_style_map, normalize_style_name
from idml_to_md.thread_resolver import resolve_reading_order
from idml_to_md.toc_parser import BookManifest, TocParseError, parse_toc
from idml_to_md.utils.slugify import slugify

# Profundidade relativa dos .md em relação a book_out:
# book_out/unidade_<N>/capitulo_<M>.md → assets ficam 2 níveis acima.
_ASSETS_DEPTH = 2


@dataclass(slots=True)
class ConversionResult:
    """Caminhos finais e métricas da conversão."""

    markdown_paths: list[Path]  # exatamente 16 arquivos
    report_path: Path
    report: ConversionReport
    output_dir: Path  # book_out
    pdf_offset: int | None = None
    manifest_chapter_titles: list[str] = field(default_factory=list)


def convert_idml(
    idml_path: Path,
    output_dir: Path,
    overlay_path: Path | None = None,
    book_title: str | None = None,
    links_dir: Path | None = None,
    inkscape_path: Path | None = None,
    pdf_path: Path | None = None,
) -> ConversionResult:
    """Converte um arquivo .idml + PDF do miolo em 16 arquivos Markdown.

    Args:
        idml_path: caminho do .idml.
        output_dir: pasta-pai do output. Será criado ``output_dir/<slug>/``.
        overlay_path: YAML opcional de override sobre ``styles.default.yaml``.
        book_title: título do livro. Default: stem do arquivo .idml.
        links_dir: pasta ``Links/`` do projeto editorial. Default:
            ``idml_path.parent / "Links"``.
        inkscape_path: caminho explícito para ``inkscape.exe``. Default:
            env var ``IDML2MD_INKSCAPE_PATH``, PATH ou caminhos comuns.
        pdf_path: caminho explícito do PDF do miolo. Default: primeiro
            ``.pdf`` irmão do .idml (não dentro de ``Links/``).

    Raises:
        FileNotFoundError: se o PDF não for encontrado.
        TocParseError: se o TOC do IDML não tiver exatamente 4×4 entradas.
        PdfAnchorError: se anchors do PDF não puderem ser extraídos.
        ChapterSplitError: se os anchors não casarem no Markdown convertido.
    """
    idml_path = Path(idml_path).resolve()
    output_dir = Path(output_dir).resolve()
    links_dir = links_dir or (idml_path.parent / "Links")

    title = book_title or _derive_title(idml_path)
    slug = slugify(title)
    book_out = output_dir / slug
    book_out.mkdir(parents=True, exist_ok=True)
    raster_dir = book_out / "assets" / "img"
    vector_dir = book_out / "assets" / "vector"

    resolved_pdf = pdf_path or find_pdf_sibling(idml_path)
    if resolved_pdf is None:
        msg = (
            f"PDF do miolo não encontrado para '{idml_path.name}'. "
            f"Esperado ao lado do .idml ou via --pdf <path>."
        )
        raise FileNotFoundError(msg)
    logger.info("PDF do miolo: {}", resolved_pdf.name)

    style_map = build_style_map(overlay_path=overlay_path)
    cache_rel = style_map.equations_config.get("cache_dir") or ".cache/idml2md/equations"
    cache_dir = Path(cache_rel)
    converter = EquationConverter(cache_dir=cache_dir)

    logger.info("Abrindo IDML: {}", idml_path.name)
    with IDMLDocument(idml_path) as doc:
        # FASE: parse do TOC (precisa do IDML aberto)
        manifest = parse_toc(doc)

        order = resolve_reading_order(doc)
        logger.info("Stories em ordem: {}", len(order))

        document = Document(title=title, slug=slug)
        requested_rasters: list[str] = []
        requested_vectors: list[str] = []
        equation_count = 0
        failed_equations: list[str] = []

        for entry in order:
            story_root = doc.get_story_root(entry.story_id)
            if story_root is None:
                logger.warning("Story ausente: {}", entry.story_id)
                continue
            result = walk_story(
                story_root, style_map, converter=converter, links_dir=links_dir
            )
            document.front_matter.extend(result.front_matter)
            document.blocks.extend(result.body)
            document.references.extend(result.references)
            requested_rasters.extend(result.image_basenames)
            requested_vectors.extend(result.vector_basenames)
            equation_count += len(result.equation_basenames)
            failed_equations.extend(result.failed_equations)

        raster_map = process_raster_assets(
            requested_basenames=requested_rasters,
            links_dir=links_dir,
            output_assets_dir=raster_dir,
        )
        vector_map = process_vector_assets(
            requested_basenames=requested_vectors,
            links_dir=links_dir,
            output_vector_dir=vector_dir,
            inkscape_path=inkscape_path,
        )

    # FASE: rewrite dos paths de asset para subir 2 níveis (../../assets/...).
    combined_paths = {**raster_map.output_relative, **vector_map.output_relative}
    _rewrite_image_paths(document, combined_paths, depth=_ASSETS_DEPTH)

    # FASE: renderiza o Markdown completo (sem TOC global).
    markdown = render_document(document, include_toc=False)

    # FASE: extrai anchors do PDF e particiona o Markdown.
    anchors = extract_anchors(manifest, resolved_pdf)
    chunks = split_markdown(markdown, anchors)

    # FASE: emite os 16 arquivos.
    markdown_paths: list[Path] = []
    for chunk in chunks:
        unit_dir = book_out / f"unidade_{chunk.anchor.chapter.unit_index}"
        unit_dir.mkdir(exist_ok=True)
        out_path = unit_dir / f"capitulo_{chunk.anchor.chapter.chap_index}.md"
        out_path.write_text(chunk.text + "\n", encoding="utf-8")
        markdown_paths.append(out_path)

    chapters_per_unit = Counter(c.anchor.chapter.unit_index for c in chunks)

    report = build_report(
        doc=document,
        seen_paragraph=style_map.seen_paragraph_styles,
        unmapped_paragraph=style_map.unmapped_paragraph_styles,
        seen_character=style_map.seen_character_styles,
        unmapped_character=style_map.unmapped_character_styles,
        missing_assets=[*raster_map.missing, *vector_map.missing],
        copied_assets=len(raster_map.output_relative) + len(vector_map.output_relative),
        equations_total=equation_count,
        equations_failed=failed_equations,
        equation_cache_hits=converter.stats.cache_hits,
        equation_cache_misses=converter.stats.cache_misses,
        vector_converted=vector_map.vector_converted,
        vector_failed=vector_map.vector_failed,
        units_emitted=len(set(c.anchor.chapter.unit_index for c in chunks)),
        chapters_emitted_per_unit=[chapters_per_unit[i] for i in (1, 2, 3, 4)],
        manifest_chapter_titles=[c.title for c in manifest.chapters],
        pdf_offset_detected=anchors.pdf_offset,
        anchors_matched=len(chunks),
    )
    report_path = book_out / "_report.json"
    report.write(report_path)

    logger.info("Conversão concluída → {} arquivos em {}", len(markdown_paths), book_out)
    return ConversionResult(
        markdown_paths=markdown_paths,
        report_path=report_path,
        report=report,
        output_dir=book_out,
        pdf_offset=anchors.pdf_offset,
        manifest_chapter_titles=[c.title for c in manifest.chapters],
    )


def _derive_title(idml_path: Path) -> str:
    """Limpa o stem: remove prefixos numéricos comuns (``81_``, ``v3_``)."""
    stem = idml_path.stem
    return stem.replace("_", " ").strip()


def _rewrite_image_paths(
    document: Document,
    mapping: dict[str, str],
    depth: int = _ASSETS_DEPTH,
) -> None:
    """Substitui ``src`` dos ``ImageBlock`` pelo caminho relativo final.

    Os .md serão escritos em ``book_out/unidade_<N>/capitulo_<M>.md`` (= 2
    níveis abaixo de ``book_out``), então paths como ``assets/img/foo.jpg``
    viram ``../../assets/img/foo.jpg``.
    """
    prefix = "../" * depth
    for block in document.blocks:
        if isinstance(block, ImageBlock):
            final = mapping.get(block.src, block.src)
            if not final.startswith(("http://", "https://", "/")) and not final.startswith("../"):
                block.src = prefix + final
            else:
                block.src = final


def inspect_styles(idml_path: Path) -> Counter[str]:
    """Lista ParagraphStyles encontrados no IDML com contagem por uso real.

    Útil para diagnosticar coleções com estilos editoriais novos.
    """
    counter: Counter[str] = Counter()
    with IDMLDocument(Path(idml_path).resolve()) as doc:
        for path in doc.story_paths():
            story_id = path.removeprefix("Stories/Story_").removesuffix(".xml")
            root = doc.get_story_root(story_id)
            if root is None:
                continue
            for psr in root.iter("ParagraphStyleRange"):
                applied = psr.get("AppliedParagraphStyle") or ""
                counter[normalize_style_name(applied)] += 1
    return counter


# Re-export para uso pelo CLI e testes.
__all__ = [
    "BookAnchors",
    "BookManifest",
    "ChapterSplitError",
    "ConversionResult",
    "PdfAnchorError",
    "TocParseError",
    "convert_idml",
    "inspect_styles",
]
