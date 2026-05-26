"""Extrai o manifesto canônico de unidades/capítulos a partir do TOC do IDML.

Cada livro da coleção tem, na ordem de leitura:

- 4 parágrafos ``Sumario:SUMARIO UNIDADE`` com texto ``"Unidade 1"``…``"Unidade 4"``.
- Após cada um, parágrafos ``Sumario:SUMARIO`` (ou ``Sumario:Item 1`` em coleções
  mais antigas) cujo texto concatena ``<título>\\t<página>`` para cada capítulo.

Exemplos reais (extraídos via inspeção dos IDMLs em ``Input/``)::

    "CAPÍTULO 1 – Conceito da Qualidade\\t7CAPÍTULO 2 – Contribuições…\\t16…"
    "Introdução à Anatomia Humana\\t7Pele e anexos\\t13Sistema esquelético\\t18…"
    "SOFTWARE PROPRIETÁRIO\\t7SOFTWARE LIVRE X SOFTWARE PROPRIETÁRIO\\t10…"

O parser tolera os três formatos. O número de página vem **colado** ao próximo
título (não há separador), então o token regex usa lookahead para parar no
primeiro caracter não-numérico.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from loguru import logger

from idml_to_md.style_mapper import normalize_style_name
from idml_to_md.thread_resolver import resolve_reading_order

if TYPE_CHECKING:
    from idml_to_md.idml_reader import IDMLDocument


_UNIT_STYLE = "Sumario:SUMARIO UNIDADE"
_CHAPTER_STYLES = ("Sumario:SUMARIO", "Sumario:Item 1")
# Regex para extrair pares (título, página) numa string concatenada
# "<title>\t<page>" repetidos. Lookahead `(?=\D|$)` segura o número no menor
# match possível. O ``[.,;:]?`` opcional tolera um caracter de pontuação
# espúrio antes do número de página — caso real observado em 041 ENFERMAGEM
# onde o TOC tem ``\t.124`` em vez de ``\t124``.
_TOC_ENTRY_RE = re.compile(r"(.+?)\t[.,;:]?(\d+)(?=\D|$)", re.DOTALL)
# Strip opcional de prefixo "CAPÍTULO N –" do título.
_CHAPTER_PREFIX_RE = re.compile(
    r"^\s*CAP[ÍI]TULO\s+\d+\s*[–\-—]\s*", re.IGNORECASE
)
# Caracteres especiais InDesign (line/paragraph separator) que precisamos
# normalizar para whitespace na hora de coletar o texto bruto do TOC.
_INLINE_SEP_RE = re.compile(r"[  ]+")
# Estilos de parágrafos do sumário que devem ser CONSIDERADOS como referência
# (não viram capítulo, mas marcam o fim útil do sumário). Útil quando o TOC
# inclui uma linha final "REFERÊNCIAS\t<page>".
_REFERENCES_TITLES = {"REFERENCIAS", "REFERÊNCIAS"}

# Número de unidades / capítulos por unidade exigidos pelo padrão editorial.
EXPECTED_UNITS = 4
EXPECTED_CHAPTERS_PER_UNIT = 4
EXPECTED_TOTAL_CHAPTERS = EXPECTED_UNITS * EXPECTED_CHAPTERS_PER_UNIT


class TocParseError(ValueError):
    """O TOC do IDML não pôde ser parseado no formato esperado 4×4."""


@dataclass(frozen=True, slots=True)
class ChapterManifest:
    """Uma entrada do manifesto canônico extraído do TOC."""

    unit_index: int  # 1..EXPECTED_UNITS
    chap_index: int  # 1..EXPECTED_CHAPTERS_PER_UNIT (dentro da unidade)
    title: str  # já normalizado (sem prefixo "CAPÍTULO N – ")
    start_page: int  # número de página IMPRESSA do livro


@dataclass(frozen=True, slots=True)
class BookManifest:
    """Manifesto completo do livro: exatamente 16 capítulos + página de refs."""

    chapters: tuple[ChapterManifest, ...]
    references_start_page: int | None  # ``None`` quando o TOC não tem entrada de Refs


# ---------------------------------------------------------------------------
# API pública
# ---------------------------------------------------------------------------


def parse_toc(doc: IDMLDocument) -> BookManifest:
    """Lê o TOC do IDML e devolve o ``BookManifest`` validado.

    Levanta ``TocParseError`` se o TOC não tiver exatamente 4 unidades, ou se
    qualquer unidade não tiver exatamente 4 capítulos, ou se as páginas não
    forem estritamente crescentes.
    """
    raw_entries = _collect_toc_entries(doc)
    if not raw_entries:
        msg = "Nenhum parágrafo Sumario:* encontrado no IDML"
        raise TocParseError(msg)

    units = _group_by_unit(raw_entries)
    if len(units) != EXPECTED_UNITS:
        msg = (
            f"TOC tem {len(units)} unidades, esperado {EXPECTED_UNITS}. "
            f"Textos das entradas de unidade: {[u.unit_text for u in units]}"
        )
        raise TocParseError(msg)

    chapters: list[ChapterManifest] = []
    references_page: int | None = None

    for unit_idx, unit in enumerate(units, start=1):
        pairs = _tokenize_unit(unit.payload_text)
        if not pairs:
            msg = (
                f"Unidade {unit_idx} ({unit.unit_text!r}) não tem entradas "
                f"<título>\\t<página> parseáveis. Payload bruto: {unit.payload_text!r}"
            )
            raise TocParseError(msg)

        # Detectar e separar entry de "REFERÊNCIAS" se vier junto da última unidade.
        non_ref_pairs: list[tuple[str, int]] = []
        for title, page in pairs:
            normalized = _normalize_title(title)
            if normalized.upper().strip() in _REFERENCES_TITLES:
                references_page = page
                continue
            non_ref_pairs.append((normalized, page))

        if len(non_ref_pairs) != EXPECTED_CHAPTERS_PER_UNIT:
            msg = (
                f"Unidade {unit_idx} tem {len(non_ref_pairs)} capítulos no TOC, "
                f"esperado {EXPECTED_CHAPTERS_PER_UNIT}. Titulos achados: "
                f"{[t for t, _ in non_ref_pairs]}"
            )
            raise TocParseError(msg)

        for chap_idx, (title, page) in enumerate(non_ref_pairs, start=1):
            chapters.append(
                ChapterManifest(
                    unit_index=unit_idx,
                    chap_index=chap_idx,
                    title=title,
                    start_page=page,
                )
            )

    # Páginas estritamente crescentes
    for prev, curr in zip(chapters, chapters[1:], strict=False):
        if curr.start_page <= prev.start_page:
            msg = (
                f"Páginas não estritamente crescentes: cap. {prev.unit_index}.{prev.chap_index} "
                f"(p. {prev.start_page}) → cap. {curr.unit_index}.{curr.chap_index} "
                f"(p. {curr.start_page})"
            )
            raise TocParseError(msg)

    if references_page is not None and references_page <= chapters[-1].start_page:
        msg = (
            f"Página de referências ({references_page}) deve ser depois do último "
            f"capítulo (p. {chapters[-1].start_page})"
        )
        raise TocParseError(msg)

    logger.info(
        "TOC parseado: {} capítulos, refs na p. {}",
        len(chapters),
        references_page if references_page is not None else "?",
    )
    return BookManifest(
        chapters=tuple(chapters),
        references_start_page=references_page,
    )


# ---------------------------------------------------------------------------
# Internos: coleta dos parágrafos crus
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class _RawTocEntry:
    """Um parágrafo Sumario:* na ordem de leitura."""

    style: str
    text: str


@dataclass(slots=True)
class _UnitGroup:
    """Uma unidade do TOC: o parágrafo de cabeçalho + o payload de capítulos."""

    unit_text: str  # "Unidade 1", "Unidade 01", …
    payload_text: str  # concatenação dos `Sumario:SUMARIO` / `Sumario:Item 1`


def _collect_toc_entries(doc: IDMLDocument) -> list[_RawTocEntry]:
    """Percorre stories em ordem de leitura coletando parágrafos do sumário."""
    order = resolve_reading_order(doc)
    out: list[_RawTocEntry] = []
    target_styles = {_UNIT_STYLE, *_CHAPTER_STYLES}

    for entry in order:
        root = doc.get_story_root(entry.story_id)
        if root is None:
            continue
        for psr in root.iter("ParagraphStyleRange"):
            style = normalize_style_name(psr.get("AppliedParagraphStyle") or "")
            if style not in target_styles:
                continue
            text = _extract_psr_text(psr)
            if text:
                out.append(_RawTocEntry(style=style, text=text))
    return out


def _extract_psr_text(psr) -> str:  # type: ignore[no-untyped-def]
    """Concatena todo o texto de um ParagraphStyleRange."""
    bits: list[str] = []
    for content in psr.iter("Content"):
        if content.text:
            bits.append(content.text)
    raw = "".join(bits)
    # InDesign usa U+2028/U+2029 como quebras dentro de um parágrafo;
    # normalizamos para espaço único.
    return _INLINE_SEP_RE.sub(" ", raw).strip()


def _group_by_unit(entries: list[_RawTocEntry]) -> list[_UnitGroup]:
    """Agrupa: cada SUMARIO UNIDADE inicia uma unidade; SUMARIO/Item 1 anexam."""
    units: list[_UnitGroup] = []
    for entry in entries:
        if entry.style == _UNIT_STYLE:
            units.append(_UnitGroup(unit_text=entry.text, payload_text=""))
        elif units:  # ignora SUMARIO sem UNIDADE anterior (raro / front matter)
            # Anexa com tab garantido entre fragmentos para o tokenizer não fundir
            # "10\tTítulo X" do fragmento anterior com "100\tTítulo Y" do próximo.
            sep = "" if not units[-1].payload_text else "\t"
            units[-1].payload_text += sep + entry.text
    return units


def _tokenize_unit(payload: str) -> list[tuple[str, int]]:
    """Quebra um payload ``"título\\tpágina título\\tpágina…"`` em pares."""
    pairs: list[tuple[str, int]] = []
    for match in _TOC_ENTRY_RE.finditer(payload):
        title = match.group(1).strip()
        page = int(match.group(2))
        if title:
            pairs.append((title, page))
    return pairs


def _normalize_title(raw: str) -> str:
    """Remove prefixo "CAPÍTULO N – " e colapsa whitespace interno."""
    stripped = _CHAPTER_PREFIX_RE.sub("", raw)
    return re.sub(r"\s+", " ", stripped).strip()
