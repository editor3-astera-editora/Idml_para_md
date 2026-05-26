"""Testes das partes puras de ``idml_to_md.pdf_anchors``.

Cobre normalização, detecção de running header, extração de page numbers
e o helper de localização do PDF irmão. Não toca ``extract_anchors`` end-to-end
(esse precisa de PDF real — coberto pelo smoke test em Input/).
"""

from __future__ import annotations

from pathlib import Path

from idml_to_md.pdf_anchors import (
    _detect_running_header_from_pages,
    _extract_candidate_page_numbers,
    _first_significant_words,
    _strip_running_header,
    anchor_search_key,
    find_pdf_sibling,
    normalize_for_search,
)

# ---------------------------------------------------------------------------
# normalize_for_search
# ---------------------------------------------------------------------------


class TestNormalizeForSearch:
    def test_lowercase_no_accents(self) -> None:
        assert normalize_for_search("Ação Conceitual") == "acao conceitual"

    def test_collapses_punctuation_to_space(self) -> None:
        assert normalize_for_search("Olá, mundo!") == "ola mundo"

    def test_strips_markdown_bold_without_inserting_space(self) -> None:
        """``**Condut****ores**`` (formatação Markdown quebrada) → ``condutores`` (junto)."""
        assert (
            normalize_for_search("**Condut****ores**, Isolantes")
            == "condutores isolantes"
        )

    def test_strips_italic_underscores(self) -> None:
        assert normalize_for_search("__bold__ e _italic_") == "bold e italic"

    def test_intraword_hyphen_collapsed(self) -> None:
        # Hifenização tipográfica entre letras some — vira palavra única
        assert normalize_for_search("co-nhecimento") == "conhecimento"

    def test_handles_curly_quotes(self) -> None:
        assert normalize_for_search('"aspas"') == "aspas"

    def test_empty_input(self) -> None:
        assert normalize_for_search("") == ""

    def test_only_punctuation_becomes_empty(self) -> None:
        assert normalize_for_search("--- *** ___") == ""


# ---------------------------------------------------------------------------
# _detect_running_header_from_pages
# ---------------------------------------------------------------------------


class TestDetectRunningHeader:
    def test_finds_common_line_across_many_pages(self) -> None:
        # Header "Anatomia humana" aparece em todas as 10 páginas como 1ª linha.
        pages = [f"Anatomia humana\n{i}\nConteúdo da página {i}" for i in range(10)]
        header = _detect_running_header_from_pages(pages)
        assert header == ["anatomia", "humana"]

    def test_returns_empty_when_no_repeated_line(self) -> None:
        # Cada página tem palavras únicas — após normalize não há linhas repetidas.
        pages = [f"Conteudo unico {chr(ord('a') + i)} aqui" for i in range(10)]
        header = _detect_running_header_from_pages(pages)
        assert header == []

    def test_requires_minimum_threshold(self) -> None:
        # Apenas 2 ocorrências da única linha repetida (mínimo é max(5, 30%)).
        pages = ["Header X\nconteúdo"] * 2
        header = _detect_running_header_from_pages(pages)
        assert header == []


# ---------------------------------------------------------------------------
# _strip_running_header
# ---------------------------------------------------------------------------


class TestStripRunningHeader:
    def test_removes_matching_prefix(self) -> None:
        anchor = "gestao da qualidade conceito da qualidade"
        out = _strip_running_header(anchor, ["gestao", "da", "qualidade"])
        assert out == "conceito da qualidade"

    def test_leaves_anchor_alone_when_no_match(self) -> None:
        anchor = "outra coisa qualquer"
        out = _strip_running_header(anchor, ["gestao", "da", "qualidade"])
        assert out == "outra coisa qualquer"

    def test_empty_header_returns_anchor(self) -> None:
        assert _strip_running_header("abc", []) == "abc"


# ---------------------------------------------------------------------------
# _extract_candidate_page_numbers
# ---------------------------------------------------------------------------


class TestExtractCandidatePageNumbers:
    def test_finds_lone_number_in_top_lines(self) -> None:
        text = "Header\n7\n\nConteúdo da página\nMais texto"
        nums = _extract_candidate_page_numbers(text)
        assert 7 in nums

    def test_finds_lone_number_in_bottom_lines(self) -> None:
        text = "Conteúdo\n" * 10 + "42"
        nums = _extract_candidate_page_numbers(text)
        assert 42 in nums

    def test_ignores_numbers_inside_text(self) -> None:
        text = "Cap 42 sobre números"  # número embedded, não em linha isolada
        nums = _extract_candidate_page_numbers(text)
        assert nums == []


# ---------------------------------------------------------------------------
# _first_significant_words
# ---------------------------------------------------------------------------


class TestFirstSignificantWords:
    def test_skips_lone_page_numbers(self) -> None:
        text = "Cabeçalho\n7\nConteúdo principal aqui"
        words = _first_significant_words(text, n=10).split()
        assert "7" not in words  # filtrado por ser só dígito

    def test_n_limits_output(self) -> None:
        text = "uma duas três quatro cinco seis sete oito nove dez"
        out = _first_significant_words(text, n=3).split()
        assert len(out) == 3

    def test_normalizes_to_lowercase_no_accents(self) -> None:
        text = "Introdução à Anatomia"
        out = _first_significant_words(text, n=5)
        assert "introducao" in out
        assert "anatomia" in out


# ---------------------------------------------------------------------------
# anchor_search_key
# ---------------------------------------------------------------------------


class TestAnchorSearchKey:
    def test_reduces_to_first_n_words(self) -> None:
        # Anchor já normalizado, vamos pegar primeiras 8 palavras
        anchor = "a b c d e f g h i j k l"
        key = anchor_search_key(anchor)
        assert len(key.split()) == 8


# ---------------------------------------------------------------------------
# find_pdf_sibling
# ---------------------------------------------------------------------------


class TestFindPdfSibling:
    def test_returns_largest_pdf_in_same_dir(self, tmp_path: Path) -> None:
        idml = tmp_path / "livro.idml"
        idml.write_bytes(b"fake")
        small = tmp_path / "small.pdf"
        small.write_bytes(b"x" * 100)
        big = tmp_path / "miolo.pdf"
        big.write_bytes(b"x" * 10_000)
        assert find_pdf_sibling(idml) == big

    def test_returns_none_when_no_pdf(self, tmp_path: Path) -> None:
        idml = tmp_path / "livro.idml"
        idml.write_bytes(b"fake")
        assert find_pdf_sibling(idml) is None

    def test_ignores_pdfs_in_subfolders(self, tmp_path: Path) -> None:
        idml = tmp_path / "livro.idml"
        idml.write_bytes(b"fake")
        sub = tmp_path / "Links"
        sub.mkdir()
        (sub / "figura.pdf").write_bytes(b"x" * 1000)
        assert find_pdf_sibling(idml) is None
