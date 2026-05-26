"""Testes da máquina de parsing do TOC (``idml_to_md.toc_parser``).

Foco nas partes puras (regex de tokenização, normalização, validação 4×4)
sem dependência de IDMLDocument real.
"""

from __future__ import annotations

import pytest

from idml_to_md.toc_parser import (
    BookManifest,
    TocParseError,
    _group_by_unit,
    _normalize_title,
    _RawTocEntry,
    _tokenize_unit,
    parse_toc,
)

# ---------------------------------------------------------------------------
# _tokenize_unit
# ---------------------------------------------------------------------------


class TestTokenizeUnit:
    def test_simple_four_chapters(self) -> None:
        payload = "Cap A\t7Cap B\t14Cap C\t21Cap D\t28"
        pairs = _tokenize_unit(payload)
        assert pairs == [("Cap A", 7), ("Cap B", 14), ("Cap C", 21), ("Cap D", 28)]

    def test_with_capitulo_prefix(self) -> None:
        payload = "CAPÍTULO 1 – Conceito\t7CAPÍTULO 2 – Análise\t16"
        pairs = _tokenize_unit(payload)
        assert pairs == [("CAPÍTULO 1 – Conceito", 7), ("CAPÍTULO 2 – Análise", 16)]

    def test_trailing_whitespace_around_tab(self) -> None:
        payload = "Cap A  \t7Cap B \t14"
        pairs = _tokenize_unit(payload)
        # ``.strip()`` é aplicado em _tokenize_unit
        assert pairs[0][0] == "Cap A"
        assert pairs[1][0] == "Cap B"

    def test_punctuation_before_page_number(self) -> None:
        """Tolera ponto/vírgula antes do número (caso observado em 041 Enfermagem)."""
        payload = "Cap A\t.124Cap B\t132"
        pairs = _tokenize_unit(payload)
        assert pairs == [("Cap A", 124), ("Cap B", 132)]

    def test_empty_payload_returns_empty(self) -> None:
        assert _tokenize_unit("") == []

    def test_ignores_entry_without_page(self) -> None:
        payload = "Cap A sem pagina"
        assert _tokenize_unit(payload) == []


# ---------------------------------------------------------------------------
# _normalize_title
# ---------------------------------------------------------------------------


class TestNormalizeTitle:
    def test_strips_capitulo_prefix(self) -> None:
        assert _normalize_title("CAPÍTULO 1 – Conceito da Qualidade") == "Conceito da Qualidade"

    def test_strips_with_dash_variants(self) -> None:
        assert _normalize_title("CAPÍTULO 2 - X") == "X"
        assert _normalize_title("CAPÍTULO 3 — Y") == "Y"

    def test_collapses_internal_whitespace(self) -> None:
        assert _normalize_title("Título  com   espaços   extras") == "Título com espaços extras"

    def test_no_prefix_kept_as_is(self) -> None:
        assert _normalize_title("Pele e anexos") == "Pele e anexos"


# ---------------------------------------------------------------------------
# _group_by_unit
# ---------------------------------------------------------------------------


def _entry(style: str, text: str) -> _RawTocEntry:
    return _RawTocEntry(style=style, text=text)


class TestGroupByUnit:
    def test_one_unit_one_payload(self) -> None:
        entries = [
            _entry("Sumario:SUMARIO UNIDADE", "Unidade 1"),
            _entry("Sumario:SUMARIO", "Cap A\t7"),
        ]
        units = _group_by_unit(entries)
        assert len(units) == 1
        assert units[0].unit_text == "Unidade 1"
        assert units[0].payload_text == "Cap A\t7"

    def test_payload_split_across_multiple_sumario_entries(self) -> None:
        """Múltiplos Sumario:SUMARIO dentro da mesma unidade são concatenados."""
        entries = [
            _entry("Sumario:SUMARIO UNIDADE", "Unidade 1"),
            _entry("Sumario:SUMARIO", "Cap A\t7"),
            _entry("Sumario:SUMARIO", "Cap B\t14"),
        ]
        units = _group_by_unit(entries)
        assert len(units) == 1
        # Tab inserido entre os dois fragments para o tokenizer não fundir o
        # "7Cap B" do início do segundo com o "7" do fim do primeiro.
        assert units[0].payload_text == "Cap A\t7\tCap B\t14"

    def test_multiple_units(self) -> None:
        entries = [
            _entry("Sumario:SUMARIO UNIDADE", "Unidade 1"),
            _entry("Sumario:SUMARIO", "A\t7"),
            _entry("Sumario:SUMARIO UNIDADE", "Unidade 2"),
            _entry("Sumario:SUMARIO", "B\t20"),
        ]
        units = _group_by_unit(entries)
        assert len(units) == 2
        assert units[0].unit_text == "Unidade 1"
        assert units[1].unit_text == "Unidade 2"

    def test_ignores_sumario_without_unidade_prefix(self) -> None:
        # Esses Sumarios não têm UNIDADE antes — vêm do front matter (sumário-mestre).
        entries = [
            _entry("Sumario:SUMARIO", "lista solta"),
            _entry("Sumario:SUMARIO UNIDADE", "Unidade 1"),
            _entry("Sumario:SUMARIO", "Real\t7"),
        ]
        units = _group_by_unit(entries)
        assert len(units) == 1
        assert "lista solta" not in units[0].payload_text


# ---------------------------------------------------------------------------
# parse_toc — testado indirectamente via fixture que monta entries crus
# ---------------------------------------------------------------------------


class _FakeDoc:
    """Mock mínimo que simula um IDMLDocument para parse_toc.

    Implementa apenas o necessário: get_story_root retornando árvores XML
    com ParagraphStyleRanges nos estilos de TOC.
    """

    def __init__(self, raw_entries: list[tuple[str, str]]) -> None:
        # raw_entries: lista de (style, text), na ordem de leitura.
        self._raw = raw_entries

    # interface que resolve_reading_order chama:
    def iter_text_frames(self, include_masters: bool = False):  # noqa: ARG002
        # Único story = "s1"
        from idml_to_md.idml_reader import TextFrameInfo

        yield TextFrameInfo(
            self_id="f1",
            parent_story="s1",
            previous_text_frame="n",
            next_text_frame="n",
            spread_index=0,
            order_in_spread=0,
        )

    def get_story_root(self, story_id: str):  # noqa: ARG002
        from lxml import etree

        root = etree.Element("Story")
        for style, text in self._raw:
            psr = etree.SubElement(
                root, "ParagraphStyleRange", AppliedParagraphStyle=f"ParagraphStyle/{style}"
            )
            content = etree.SubElement(psr, "Content")
            content.text = text
        return root


def _build_valid_book_entries() -> list[tuple[str, str]]:
    """Constrói uma sequência de entries representando um TOC 4×4 válido."""
    out: list[tuple[str, str]] = []
    page = 7
    for u in range(1, 5):
        out.append(("Sumario:SUMARIO UNIDADE", f"Unidade {u}"))
        chapters_payload = ""
        for c in range(1, 5):
            chapters_payload += f"Cap U{u}.C{c}\t{page}"
            page += 10
        out.append(("Sumario:SUMARIO", chapters_payload))
    return out


class TestParseToc:
    def test_valid_4x4(self) -> None:
        doc = _FakeDoc(_build_valid_book_entries())
        manifest: BookManifest = parse_toc(doc)  # type: ignore[arg-type]
        assert len(manifest.chapters) == 16
        # Primeiro: u1.c1 página 7
        assert manifest.chapters[0].unit_index == 1
        assert manifest.chapters[0].chap_index == 1
        assert manifest.chapters[0].start_page == 7
        # Último: u4.c4
        assert manifest.chapters[-1].unit_index == 4
        assert manifest.chapters[-1].chap_index == 4

    def test_fails_with_three_units(self) -> None:
        entries = _build_valid_book_entries()
        # remove a 4ª unidade (entries 6 e 7)
        entries = entries[:6]
        doc = _FakeDoc(entries)
        with pytest.raises(TocParseError, match="3 unidades"):
            parse_toc(doc)  # type: ignore[arg-type]

    def test_fails_with_five_chapters_in_a_unit(self) -> None:
        entries = _build_valid_book_entries()
        # injeta um 5º cap na unidade 1
        entries[1] = ("Sumario:SUMARIO", entries[1][1] + "Cap extra\t60")
        # mas precisamos manter páginas crescentes — bumpa todas as posteriores
        # para evitar o erro de páginas crescentes mascarar o de contagem.
        # ajusta unidade 2 começando em 100:
        entries[3] = ("Sumario:SUMARIO", "Cap U2.C1\t100Cap U2.C2\t110Cap U2.C3\t120Cap U2.C4\t130")
        entries[5] = ("Sumario:SUMARIO", "Cap U3.C1\t150Cap U3.C2\t160Cap U3.C3\t170Cap U3.C4\t180")
        entries[7] = ("Sumario:SUMARIO", "Cap U4.C1\t200Cap U4.C2\t210Cap U4.C3\t220Cap U4.C4\t230")
        doc = _FakeDoc(entries)
        with pytest.raises(TocParseError, match="5 capítulos"):
            parse_toc(doc)  # type: ignore[arg-type]

    def test_detects_references_page(self) -> None:
        entries = _build_valid_book_entries()
        entries.append(("Sumario:SUMARIO", "REFERÊNCIAS\t200"))
        # tem que estar dentro da última unidade — adiciona ao payload da U4
        entries[7] = (
            "Sumario:SUMARIO",
            entries[7][1] + "REFERÊNCIAS\t200",
        )
        # remove o anterior, foi duplicado
        entries.pop()
        doc = _FakeDoc(entries)
        manifest = parse_toc(doc)  # type: ignore[arg-type]
        assert manifest.references_start_page == 200
