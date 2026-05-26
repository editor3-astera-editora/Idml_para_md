"""Testes do particionador ``idml_to_md.book_splitter``.

Foco nas partes puras: normalização-com-mapping, extração de heading
positions e particionamento monotônico. ``split_markdown`` é testado
com BookAnchors sintéticos.
"""

from __future__ import annotations

import pytest

from idml_to_md.book_splitter import (
    ChapterSplitError,
    _heading_positions_in_norm,
    _normalize_with_mapping,
    split_markdown,
)
from idml_to_md.pdf_anchors import BookAnchors, ChapterAnchor
from idml_to_md.toc_parser import ChapterManifest

# ---------------------------------------------------------------------------
# _normalize_with_mapping
# ---------------------------------------------------------------------------


class TestNormalizeWithMapping:
    def test_mapping_correctness(self) -> None:
        text = "Olá MUNDO"
        norm, mapping = _normalize_with_mapping(text)
        assert norm == "ola mundo"
        # 'o' (norm 0) → 'O' (orig 0)
        assert text[mapping[0]] == "O"
        # 'm' (norm 4) → 'M' (orig 4)
        m_pos = norm.index("m")
        assert text[mapping[m_pos]] == "M"

    def test_strips_markdown_inline_chars(self) -> None:
        text = "**negrito**"
        norm, _ = _normalize_with_mapping(text)
        assert norm == "negrito"

    def test_consistent_with_normalize_for_search(self) -> None:
        """Garante que _normalize_with_mapping produz o MESMO output que
        normalize_for_search — caso contrário busca de needle quebra."""
        from idml_to_md.pdf_anchors import normalize_for_search

        samples = [
            "**Condut****ores**, Isolantes e semicondutores",
            "Olá, **mundo** maravilhoso! 123.",
            "Co-\nnhecimento sustentável",
            "# Título com *itálico*",
            "Múltiplas    espaços   colapsam",
        ]
        for s in samples:
            a = normalize_for_search(s)
            b, _ = _normalize_with_mapping(s)
            assert a == b, f"mismatch on {s!r}: norm={a!r} vs map={b!r}"


# ---------------------------------------------------------------------------
# _heading_positions_in_norm
# ---------------------------------------------------------------------------


class TestHeadingPositions:
    def test_finds_h1_and_h2(self) -> None:
        md = "# Um\n\n## Dois\n\nTexto."
        _, mapping = _normalize_with_mapping(md)
        positions = _heading_positions_in_norm(md, mapping)
        assert len(positions) == 2

    def test_returns_empty_when_no_headings(self) -> None:
        md = "Texto puro sem nenhum heading.\n\nOutro parágrafo."
        _, mapping = _normalize_with_mapping(md)
        positions = _heading_positions_in_norm(md, mapping)
        assert positions == []


# ---------------------------------------------------------------------------
# split_markdown
# ---------------------------------------------------------------------------


def _make_anchors(chapters: list[tuple[int, int, str, str]]) -> BookAnchors:
    """chapters: list of (unit_idx, chap_idx, title, anchor_text)."""
    anchor_list = []
    for unit_idx, chap_idx, title, anchor_text in chapters:
        cm = ChapterManifest(
            unit_index=unit_idx, chap_index=chap_idx, title=title, start_page=10 * len(anchor_list) + 1
        )
        ca = ChapterAnchor(chapter=cm, start_anchor=anchor_text, pdf_page_index=0)
        anchor_list.append(ca)
    return BookAnchors(anchors=tuple(anchor_list), pdf_offset=0, end_sentinel=None)


class TestSplitMarkdown:
    def test_simple_three_chunks(self) -> None:
        # Anchors longos (~6-8 palavras) refletem o uso real do pipeline.
        md = (
            "# Capítulo Primeiro\n\nConteúdo do primeiro capítulo aqui com bastante texto.\n\n"
            "# Capítulo Segundo\n\nDesenvolvimento do segundo capítulo do livro.\n\n"
            "# Capítulo Terceiro\n\nFinal do livro com texto adicional aqui."
        )
        anchors = _make_anchors(
            [
                (1, 1, "Capítulo Primeiro", "capitulo primeiro conteudo do primeiro capitulo aqui com bastante"),
                (1, 2, "Capítulo Segundo", "capitulo segundo desenvolvimento do segundo capitulo do livro"),
                (1, 3, "Capítulo Terceiro", "capitulo terceiro final do livro com texto adicional"),
            ]
        )
        chunks = split_markdown(md, anchors)
        assert len(chunks) == 3
        assert "Capítulo Primeiro" in chunks[0].text
        assert "Capítulo Segundo" in chunks[1].text
        assert "Capítulo Terceiro" in chunks[2].text

    def test_raises_when_anchor_not_found(self) -> None:
        md = "# Capítulo Existente\n\nConteúdo que está presente no Markdown."
        anchors = _make_anchors(
            [
                (1, 1, "Capítulo Existente", "capitulo existente conteudo que esta presente no markdown"),
                (1, 2, "Capítulo Inexistente", "frase totalmente diferente que jamais aparece"),
            ]
        )
        with pytest.raises(ChapterSplitError, match="não encontrado"):
            split_markdown(md, anchors)

    def test_strips_chunk_whitespace(self) -> None:
        md = "# Alfa\n\nTexto do alfa aqui completo.\n\n\n\n# Beta\n\nMais texto do beta."
        anchors = _make_anchors(
            [
                (1, 1, "Alfa", "alfa texto do alfa aqui completo"),
                (1, 2, "Beta", "beta mais texto do beta"),
            ]
        )
        chunks = split_markdown(md, anchors)
        for c in chunks:
            assert c.text == c.text.strip()

    def test_chunk_ends_just_before_next_anchor(self) -> None:
        md = (
            "# Primeiro\n\nAAA texto exclusivo do primeiro.\n\n"
            "# Segundo\n\nBBB texto exclusivo do segundo."
        )
        anchors = _make_anchors(
            [
                (1, 1, "Primeiro", "primeiro aaa texto exclusivo do primeiro"),
                (1, 2, "Segundo", "segundo bbb texto exclusivo do segundo"),
            ]
        )
        chunks = split_markdown(md, anchors)
        assert "BBB" not in chunks[0].text  # cap 1 não invade cap 2
        assert "AAA" not in chunks[1].text

    def test_monotonic_search_order(self) -> None:
        """Se um anchor existe no markdown ANTES do cursor, não pode bater retroativamente."""
        md = (
            "# Conceito Inicial\n\nIntrodução conceitual aqui.\n\n"
            "# Conceito Avançado\n\nDesenvolvimento avançado do tema completo.\n\n"
            "# Conclusão Geral\n\nFinal conclusivo do livro."
        )
        anchors = _make_anchors(
            [
                (1, 1, "Conceito Inicial", "conceito inicial introducao conceitual aqui"),
                (1, 2, "Conceito Avançado", "conceito avancado desenvolvimento avancado do tema completo"),
                (1, 3, "Conclusão Geral", "conclusao geral final conclusivo do livro"),
            ]
        )
        chunks = split_markdown(md, anchors)
        assert len(chunks) == 3
        assert "Conceito Avançado" in chunks[1].text
