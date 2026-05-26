"""Extrai anchors textuais de páginas-fronteira do PDF do miolo.

Estratégia:

1. Detectar o **offset PDF↔TOC**. O TOC do IDML usa números de página IMPRESSOS
   (capa e folha de rosto não contam). O índice do PDF começa em 0 e inclui
   capa. Para descobrir o offset, escaneamos os números de página visíveis no
   header/footer das primeiras N páginas e elegemos o offset MAIS FREQUENTE —
   isso descarta naturalmente páginas de abertura de capítulo (que mostram um
   número de capítulo no lugar do número de página).

2. Para cada capítulo do manifesto, extrair as primeiras palavras significativas
   da sua página inicial (= anchor de início). O anchor é uma sequência de
   ~12 palavras normalizadas suficientemente única para localizar a posição
   correspondente no Markdown convertido.

3. O anchor de fim de um capítulo é o anchor de início do PRÓXIMO. Para o
   último capítulo, o anchor de fim é extraído da página de Referências
   (``BookManifest.references_start_page``) ou, se ausente, da última página
   do PDF.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from loguru import logger
from pypdf import PdfReader

from idml_to_md.toc_parser import BookManifest, ChapterManifest


# Quantas palavras significativas formam um anchor. Maior = mais específico
# (menos colisão), porém mais sensível a diferenças entre PDF e Markdown.
ANCHOR_WORD_COUNT = 12
# Quantas palavras significativas USAMOS PARA BUSCAR (matchamos um prefixo
# do anchor para tolerar pequenas perdas no fim por hifenização, etc.).
ANCHOR_SEARCH_WORDS = 8
# Tamanho da janela de scan (em páginas) para detectar o offset PDF↔TOC.
_OFFSET_DETECTION_SCAN_PAGES = 40
# Mínimo de votos para considerar um offset confiável.
_MIN_OFFSET_VOTES = 5
# Faixa razoável de números de página impressos para considerar como candidato
# (descarta números muito pequenos que provavelmente são números de capítulo).
_MIN_PRINTED_PAGE = 5

# Regex que captura linhas que são SÓ um número inteiro (1-4 dígitos).
_PAGE_NUM_LINE_RE = re.compile(r"^\s*(\d{1,4})\s*$")


class PdfAnchorError(ValueError):
    """O PDF não pôde ser usado para extrair anchors confiáveis."""


@dataclass(frozen=True, slots=True)
class ChapterAnchor:
    """Anchor de um capítulo: começo e (próximo começo / fim)."""

    chapter: ChapterManifest
    start_anchor: str  # primeiras ~12 palavras normalizadas da página inicial
    pdf_page_index: int  # índice 0-based no PDF


@dataclass(frozen=True, slots=True)
class BookAnchors:
    """Anchors de todos os 16 capítulos + offset detectado + sentinel de fim."""

    anchors: tuple[ChapterAnchor, ...]
    pdf_offset: int  # pdf_idx = printed_page + pdf_offset
    end_sentinel: str | None  # primeiras palavras da página de Referências


# ---------------------------------------------------------------------------
# API pública
# ---------------------------------------------------------------------------


def extract_anchors(manifest: BookManifest, pdf_path: Path) -> BookAnchors:
    """Abre o PDF e extrai anchors para todos os capítulos do ``manifest``."""
    reader = PdfReader(str(pdf_path))
    page_count = len(reader.pages)
    logger.info("Abrindo PDF '{}' ({} páginas)", pdf_path.name, page_count)

    page_texts = [_extract_page_text(reader, i) for i in range(page_count)]

    offset = _detect_offset(page_texts, manifest)
    logger.info("Offset PDF↔TOC detectado: {}", offset)

    # Running header: detecta uma vez, sobre o LIVRO INTEIRO (mais robusto que
    # inferir dos 16 anchors apenas).
    running_header_words = _detect_running_header_from_pages(page_texts)
    if running_header_words:
        logger.info(
            "Running header do PDF detectado: {!r} — será removido dos anchors",
            " ".join(running_header_words),
        )

    anchors: list[ChapterAnchor] = []
    for chap in manifest.chapters:
        pdf_idx = chap.start_page + offset
        if pdf_idx < 0 or pdf_idx >= page_count:
            msg = (
                f"Capítulo {chap.unit_index}.{chap.chap_index} (p. {chap.start_page}) "
                f"mapeia para pdf_idx={pdf_idx} fora do range [0, {page_count})"
            )
            raise PdfAnchorError(msg)
        raw_anchor = _first_significant_words(page_texts[pdf_idx], n=ANCHOR_WORD_COUNT * 2)
        if not raw_anchor:
            msg = (
                f"Anchor vazio para capítulo {chap.unit_index}.{chap.chap_index} "
                f"(p. {chap.start_page}, pdf_idx={pdf_idx})"
            )
            raise PdfAnchorError(msg)
        trimmed = _strip_running_header(raw_anchor, running_header_words)
        words = trimmed.split()[:ANCHOR_WORD_COUNT]
        if len(words) < ANCHOR_SEARCH_WORDS:
            msg = (
                f"Anchor do cap. {chap.unit_index}.{chap.chap_index} ficou curto demais "
                f"após remover header ({len(words)} palavras, mínimo {ANCHOR_SEARCH_WORDS}). "
                f"Anchor cru: {raw_anchor!r}"
            )
            raise PdfAnchorError(msg)
        anchors.append(
            ChapterAnchor(
                chapter=chap,
                start_anchor=" ".join(words),
                pdf_page_index=pdf_idx,
            )
        )

    end_sentinel: str | None = None
    if manifest.references_start_page is not None:
        ref_idx = manifest.references_start_page + offset
        if 0 <= ref_idx < page_count:
            raw_sentinel = _first_significant_words(
                page_texts[ref_idx], n=ANCHOR_WORD_COUNT * 2
            )
            if raw_sentinel:
                trimmed = _strip_running_header(raw_sentinel, running_header_words)
                words = trimmed.split()[:ANCHOR_WORD_COUNT]
                end_sentinel = " ".join(words) if words else None

    return BookAnchors(anchors=tuple(anchors), pdf_offset=offset, end_sentinel=end_sentinel)


def find_pdf_sibling(idml_path: Path) -> Path | None:
    """Localiza o PDF do miolo irmão do ``.idml``.

    Convenção: um arquivo ``.pdf`` na MESMA pasta do IDML (não dentro de
    ``Links/``, que tem PDFs de figuras pequenas). Se houver múltiplos PDFs,
    escolhe o maior em bytes (heurística: o miolo é dezenas de MB, figuras
    são KB).
    """
    parent = idml_path.parent
    candidates = [p for p in parent.glob("*.pdf") if p.is_file()]
    if not candidates:
        return None
    # Maior arquivo vence — o miolo é sempre o maior PDF da pasta do livro.
    candidates.sort(key=lambda p: p.stat().st_size, reverse=True)
    return candidates[0]


# ---------------------------------------------------------------------------
# Normalização e busca de anchors no Markdown
# ---------------------------------------------------------------------------


_INLINE_FORMAT_RE = re.compile(r"[*_`~]+")
_INTRA_WORD_HYPHEN_RE = re.compile(r"(?<=\w)[-­](?=\w)")


def normalize_for_search(text: str) -> str:
    """Lowercase, sem acentos, espaços colapsados — para busca robusta.

    Trata marcas de formatação Markdown (``**``, ``__``, ``~~``, ``\\``)
    como cola (descarta sem inserir espaço), para que ``**Condut**ores`` →
    ``condutores`` em vez de ``condut ores``. Também colapsa hífens
    intra-palavra (hifenizações entre linhas no PDF).
    """
    # 1. Decompõe e remove diacríticos (NFKD + filter combining).
    decomposed = unicodedata.normalize("NFKD", text)
    ascii_text = "".join(c for c in decomposed if not unicodedata.combining(c))
    lowered = ascii_text.lower()
    # 2. Descarta marcas Markdown inline e hifens intra-palavra (sem inserir
    #    espaço) ANTES de tratar o resto.
    no_format = _INLINE_FORMAT_RE.sub("", lowered)
    no_hyphen = _INTRA_WORD_HYPHEN_RE.sub("", no_format)
    # 3. Resto do não-alfanumérico vira espaço; colapsa runs.
    cleaned = re.sub(r"[^a-z0-9]+", " ", no_hyphen)
    return re.sub(r"\s+", " ", cleaned).strip()


def anchor_search_key(anchor: str) -> str:
    """Reduz o anchor para o prefixo usado em busca (mais tolerante)."""
    words = normalize_for_search(anchor).split()
    return " ".join(words[:ANCHOR_SEARCH_WORDS])


# ---------------------------------------------------------------------------
# Internos
# ---------------------------------------------------------------------------


def _extract_page_text(reader: PdfReader, idx: int) -> str:
    """Wrapper resiliente em torno de ``pypdf.PdfReader.pages[i].extract_text()``."""
    try:
        text = reader.pages[idx].extract_text() or ""
    except (KeyError, ValueError, AttributeError) as exc:
        logger.warning("Falha extraindo texto da página {} do PDF: {}", idx, exc)
        return ""
    return text


def _detect_offset(page_texts: list[str], manifest: BookManifest) -> int:
    """Detecta o offset PDF↔TOC por voto majoritário."""
    votes: Counter[int] = Counter()
    scan_to = min(_OFFSET_DETECTION_SCAN_PAGES, len(page_texts))

    for idx in range(scan_to):
        for num in _extract_candidate_page_numbers(page_texts[idx]):
            if num < _MIN_PRINTED_PAGE:
                continue
            candidate_offset = idx - num
            # Offsets razoáveis: capa + folha de rosto + sumário consomem 2 a 10
            # páginas físicas antes da página impressa "1". Logo o offset costuma
            # estar entre -10 e -2. Aceitamos -20 a +5 por margem.
            if -20 <= candidate_offset <= 5:
                votes[candidate_offset] += 1

    if not votes:
        # Estratégia B (fallback): casar o título do cap. 1 no texto do PDF.
        return _detect_offset_via_title_match(page_texts, manifest)

    best_offset, best_count = votes.most_common(1)[0]
    if best_count < _MIN_OFFSET_VOTES:
        logger.warning(
            "Offset detectado com apenas {} votos (mínimo {}). Tentando fallback por título.",
            best_count,
            _MIN_OFFSET_VOTES,
        )
        try:
            return _detect_offset_via_title_match(page_texts, manifest)
        except PdfAnchorError:
            logger.warning("Fallback falhou — usando offset {} mesmo assim", best_offset)
    return best_offset


def _detect_offset_via_title_match(page_texts: list[str], manifest: BookManifest) -> int:
    """Estratégia B: busca o título do cap. 1 nas primeiras páginas do PDF."""
    first_chap = manifest.chapters[0]
    needle = normalize_for_search(first_chap.title)
    if not needle:
        msg = "Capítulo 1 do TOC tem título vazio — não dá pra calibrar offset"
        raise PdfAnchorError(msg)

    scan_to = min(_OFFSET_DETECTION_SCAN_PAGES, len(page_texts))
    for idx in range(scan_to):
        haystack = normalize_for_search(page_texts[idx])
        if needle in haystack:
            offset = idx - first_chap.start_page
            logger.info(
                "Offset detectado via match de título (cap. 1 em pdf_idx={}, printed={}): {}",
                idx,
                first_chap.start_page,
                offset,
            )
            return offset

    msg = (
        f"Título do cap. 1 ({first_chap.title!r}) não encontrado nas primeiras "
        f"{scan_to} páginas do PDF — pipeline não consegue calibrar o offset"
    )
    raise PdfAnchorError(msg)


def _extract_candidate_page_numbers(text: str) -> list[int]:
    """Extrai linhas que são SÓ um inteiro (header/footer com page number)."""
    out: list[int] = []
    # Olhamos só as primeiras 5 e últimas 5 linhas — header/footer.
    lines = [ln for ln in text.splitlines() if ln.strip()]
    for ln in lines[:5] + lines[-5:]:
        m = _PAGE_NUM_LINE_RE.match(ln)
        if m:
            out.append(int(m.group(1)))
    return out


def _detect_running_header_from_pages(page_texts: list[str]) -> list[str]:
    """Detecta o running header escaneando linhas repetidas em muitas páginas.

    O running header (ex.: "Gestão da qualidade") aparece como linha curta
    no topo da maioria das páginas do livro. Detectamos contando linhas
    repetidas verbatim nas primeiras 3 linhas de cada página; a que aparece
    em ≥ 30 % das páginas é o header.

    Retorna a lista de PALAVRAS normalizadas do header (vazia se não houver).
    """
    if not page_texts:
        return []
    line_counts: Counter[str] = Counter()
    for text in page_texts:
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        for line in lines[:3]:
            normalized = normalize_for_search(line)
            # Headers típicos têm de 1 a 8 palavras significativas, não-numéricas
            words = [w for w in normalized.split() if not w.isdigit()]
            if 1 <= len(words) <= 8:
                line_counts[" ".join(words)] += 1

    if not line_counts:
        return []
    threshold = max(5, int(len(page_texts) * 0.3))
    most_line, most_count = line_counts.most_common(1)[0]
    if most_count < threshold:
        return []
    return most_line.split()


def _strip_running_header(anchor: str, header_words: list[str]) -> str:
    """Remove o prefixo ``header_words`` (já normalizado) de ``anchor`` se presente."""
    if not header_words:
        return anchor
    words = anchor.split()
    # Strip apenas se o header bate no INÍCIO; senão deixa como está.
    if len(words) > len(header_words) and words[: len(header_words)] == header_words:
        return " ".join(words[len(header_words) :])
    return anchor


def _first_significant_words(text: str, n: int) -> str:
    """Primeiras ``n`` palavras "significativas" da página.

    Pula:
    - Linhas que são só um número (page number ou chapter number).
    - Linhas vazias.
    Mantém a ordem original — o anchor é a sequência exata.
    """
    words: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if _PAGE_NUM_LINE_RE.match(stripped):
            continue
        for word in stripped.split():
            words.append(word)
            if len(words) >= n * 3:  # margem: vamos truncar via normalize depois
                break
        if len(words) >= n * 3:
            break

    # Re-normaliza e pega n palavras "significativas" finais.
    # Tokens que são SÓ dígitos são descartados — são page numbers e chapter
    # numbers visuais (ex.: "1", "47") que aparecem no PDF como linhas isoladas
    # mas viraram tokens depois do extract_text porque algumas vezes vêm coladas
    # ao texto principal por causa de columns/text frames.
    raw_text = " ".join(words)
    normalized_words = [
        w for w in normalize_for_search(raw_text).split() if not w.isdigit()
    ]
    if len(normalized_words) <= n:
        return " ".join(normalized_words)
    return " ".join(normalized_words[:n])
