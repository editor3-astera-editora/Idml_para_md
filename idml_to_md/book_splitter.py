"""Particiona o Markdown convertido em 16 chunks usando anchors do PDF.

Para cada anchor extraído (Fase 2), localizamos sua posição no Markdown
normalizado. As posições demarcam:

- Chunk i = bytes entre ``anchor[i].pos`` (inclusive) e ``anchor[i+1].pos``
  (exclusive).
- Conteúdo antes de ``anchor[0]`` (capa / sumário / introdução) é descartado.
- Conteúdo após o final do capítulo 16 (até ``end_sentinel`` ou EOF) é
  descartado — são as Referências.

A busca é **estritamente monotônica**: cada anchor é procurado a partir da
posição do anchor anterior. Se um anchor não for encontrado ou se anchors
adjacentes baterem na mesma posição, ``ChapterSplitError`` é levantado com
contexto suficiente para diagnóstico.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from loguru import logger

from idml_to_md.pdf_anchors import (
    ANCHOR_SEARCH_WORDS,
    BookAnchors,
    ChapterAnchor,
    normalize_for_search,
)

# Mínimo de palavras significativas (não-stopword) para usar o título do TOC
# como needle. Menos que isso e o título é genérico demais (ex.: "Conjuntos") —
# cai no PDF anchor.
_MIN_TITLE_WORDS = 2

# Regex que casa o início de um heading Markdown ATX (linhas iniciadas com #).
# Multiline para que ^ case início de linha.
_HEADING_START_RE = re.compile(r"^(#{1,6})\s+", re.MULTILINE)


class ChapterSplitError(ValueError):
    """Falha ao casar anchors com o Markdown convertido."""


@dataclass(frozen=True, slots=True)
class ChapterChunk:
    """Pedaço final do Markdown correspondente a um capítulo."""

    anchor: ChapterAnchor
    text: str  # já strip()-ado


def split_markdown(markdown: str, anchors: BookAnchors) -> list[ChapterChunk]:
    """Particiona ``markdown`` em chunks correspondentes a cada chapter anchor.

    Retorna lista na mesma ordem dos anchors (= ordem de leitura do livro).
    """
    norm_text, mapping = _normalize_with_mapping(markdown)

    # Extrai posições normalizadas de TODOS os headings Markdown. Usaremos isso
    # para forçar que cada chapter boundary caia num heading — evita matches
    # falsos em texto narrativo que cite o título do capítulo.
    heading_positions_norm = _heading_positions_in_norm(markdown, mapping)

    positions: list[int] = []
    cursor_norm = 0  # posição corrente na string normalizada
    for a in anchors.anchors:
        pos_norm, used_needle = _find_chapter_position(
            norm_text=norm_text,
            cursor_norm=cursor_norm,
            chapter_title=a.chapter.title,
            pdf_anchor=a.start_anchor,
            heading_positions=heading_positions_norm,
        )
        if pos_norm == -1:
            preview = (
                markdown[mapping[cursor_norm] : mapping[cursor_norm] + 200]
                if cursor_norm < len(mapping)
                else "(eof)"
            )
            msg = (
                f"Capítulo {a.chapter.unit_index}.{a.chapter.chap_index} não encontrado no Markdown "
                f"a partir da posição {cursor_norm}.\n"
                f"  Título (TOC): {a.chapter.title!r}\n"
                f"  Anchor (PDF): {a.start_anchor!r}\n"
                f"  PDF page: {a.pdf_page_index}, printed: {a.chapter.start_page}\n"
                f"  Trecho do Markdown nessa região: {preview!r}"
            )
            raise ChapterSplitError(msg)
        pos_orig = mapping[pos_norm]
        positions.append(pos_orig)
        cursor_norm = pos_norm + len(used_needle)

    # Determina o fim do último capítulo: usa end_sentinel se disponível, senão
    # vai até EOF.
    end_position = len(markdown)
    if anchors.end_sentinel:
        sentinel_needle = _anchor_to_needle(anchors.end_sentinel)
        if sentinel_needle:
            pos_norm = norm_text.find(sentinel_needle, cursor_norm)
            if pos_norm != -1:
                end_position = mapping[pos_norm]
            else:
                logger.warning(
                    "end_sentinel (Referências) não encontrado no Markdown; usando EOF como fim do cap. 16"
                )

    chunks: list[ChapterChunk] = []
    boundaries = [*positions, end_position]
    for anchor, start, end in zip(anchors.anchors, boundaries[:-1], boundaries[1:], strict=True):
        text = markdown[start:end].strip()
        if not text:
            msg = (
                f"Chunk do cap. {anchor.chapter.unit_index}.{anchor.chapter.chap_index} "
                f"ficou vazio após split (start={start}, end={end})"
            )
            raise ChapterSplitError(msg)
        chunks.append(ChapterChunk(anchor=anchor, text=text))

    return chunks


# ---------------------------------------------------------------------------
# Normalização com mapping reverso
# ---------------------------------------------------------------------------


_MARKDOWN_INLINE_CHARS = frozenset("*_`~")


def _normalize_with_mapping(text: str) -> tuple[str, list[int]]:
    """Normaliza ``text`` e devolve mapping ``norm_idx → orig_idx``.

    A regra é a mesma de :func:`pdf_anchors.normalize_for_search`: lowercase,
    sem acentos, marcas de formatação Markdown (``*``, ``_``, etc.) descartadas
    SEM inserir espaço (para que ``**Condut**ores`` → ``condutores``), hífens
    intra-palavra colapsados, runs de demais não-alfanuméricos viram 1 espaço.

    O ``mapping[i]`` aponta para o INÍCIO (no texto original) do caractere
    normalizado que ficou na posição ``i``. ``mapping[len(norm)]`` é uma
    sentinela igual a ``len(text)``.
    """
    norm_chars: list[str] = []
    mapping: list[int] = []
    last_was_space = True  # evita espaços iniciais
    n = len(text)

    for i, ch in enumerate(text):
        # 1. Marcas de formatação inline → descarta sem espaço.
        if ch in _MARKDOWN_INLINE_CHARS:
            continue

        # 2. Hífen ASCII ou soft-hyphen entre alfanuméricos → descarta.
        if ch in ("-", "­"):
            prev_alnum = (
                bool(norm_chars) and norm_chars[-1].isalnum()
            )
            next_alnum = (i + 1 < n) and _next_alnum_after_hyphen(text, i + 1)
            if prev_alnum and next_alnum:
                continue

        # 3. Decompõe Unicode + lowercase + filter combining.
        decomposed = unicodedata.normalize("NFKD", ch)
        for base in decomposed:
            if unicodedata.combining(base):
                continue
            base_low = base.lower()
            if base_low.isalnum():
                norm_chars.append(base_low)
                mapping.append(i)
                last_was_space = False
            elif not last_was_space:
                norm_chars.append(" ")
                mapping.append(i)
                last_was_space = True
            # senão: colapsa whitespace consecutivo, não emite

    mapping.append(n)
    raw = "".join(norm_chars)
    # Strip leading/trailing whitespace + ajusta mapping correspondentemente.
    leading = len(raw) - len(raw.lstrip())
    trailing = len(raw) - len(raw.rstrip())
    if leading:
        mapping = mapping[leading:]
    if trailing:
        mapping = mapping[: len(mapping) - trailing]
    return raw.strip(), mapping


def _next_alnum_after_hyphen(text: str, start: int) -> bool:
    """True se houver caracter alfanumérico antes do próximo whitespace/quebra."""
    for j in range(start, min(start + 4, len(text))):
        ch = text[j]
        if ch.isalnum():
            return True
        if ch in (" ", "\t", "\n", "\r"):
            return False
    return False


def _anchor_to_needle(anchor: str) -> str:
    """Reduz um anchor (já normalizado) ao prefixo de busca."""
    words = anchor.split()
    if not words:
        return ""
    return " ".join(words[:ANCHOR_SEARCH_WORDS])


def _find_chapter_position(
    norm_text: str,
    cursor_norm: int,
    chapter_title: str,
    pdf_anchor: str,
    heading_positions: list[int],
) -> tuple[int, str]:
    """Localiza início de capítulo, preferindo matches em posição de heading.

    Estratégia:
    1. Tentar TÍTULO do TOC casando exatamente NO INÍCIO de um heading
       (heading whose normalized text starts with the title). Este é o caso
       canônico — funciona em ~todos os capítulos onde o título do TOC bate
       com o T1 do IDML.
    2. Tentar PDF anchor (várias granularidades) no fluxo geral — útil
       quando o título do TOC difere do título no body (acentuação, quebras
       de linha, prefixos editoriais).
    3. Tentar TÍTULO do TOC no fluxo geral, sem restrição de heading.

    A restrição "tem que ser heading" evita matches falsos em texto narrativo
    (ex.: "custos da qualidade" mencionado nos OBJETIVOS antes do capítulo).
    """
    title_needle = normalize_for_search(chapter_title)
    anchor_words = _anchor_to_needle(pdf_anchor).split()

    # Tentativa 1: título do TOC, restrito a posições de heading.
    if title_needle and len(title_needle.split()) >= _MIN_TITLE_WORDS:
        for hpos in heading_positions:
            if hpos < cursor_norm:
                continue
            if norm_text.startswith(title_needle, hpos):
                return hpos, title_needle

    # Tentativa 2: PDF anchor com granularidade decrescente.
    for take in range(len(anchor_words), 3, -1):
        needle = " ".join(anchor_words[:take])
        pos = norm_text.find(needle, cursor_norm)
        if pos != -1:
            return pos, needle

    # Tentativa 3: título do TOC sem restrição de heading.
    if title_needle and len(title_needle.split()) >= _MIN_TITLE_WORDS:
        pos = norm_text.find(title_needle, cursor_norm)
        if pos != -1:
            return pos, title_needle

    return -1, ""


def _heading_positions_in_norm(markdown: str, mapping: list[int]) -> list[int]:
    """Posições NORMALIZADAS onde começa cada heading no Markdown.

    Cada `^#+\\s+` (ATX heading) é mapeado para a posição (em norm_text) do
    primeiro caracter do TÍTULO do heading (logo após o ``# ``).
    """
    # Inverso de mapping: para cada posição original, qual é a primeira posição
    # normalizada que aponta para ela. Vamos construir lazy.
    reverse: dict[int, int] = {}
    for norm_pos, orig_pos in enumerate(mapping):
        if orig_pos not in reverse:
            reverse[orig_pos] = norm_pos

    out: list[int] = []
    for m in _HEADING_START_RE.finditer(markdown):
        # Posição do primeiro caracter APÓS o "# " (= início do texto do heading)
        title_start_orig = m.end()
        # Encontra a posição normalizada correspondente (procura pelo menor
        # orig_pos >= title_start_orig que esteja no reverse).
        for orig in range(title_start_orig, len(markdown) + 1):
            if orig in reverse:
                out.append(reverse[orig])
                break
    return out
