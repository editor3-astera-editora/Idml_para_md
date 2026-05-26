"""Testes unitários do orquestrador de fila (``idml_to_md.batch``)."""

from __future__ import annotations

from pathlib import Path

from idml_to_md.batch import (
    BatchTask,
    _rewrite_asset_paths,
    discover_books,
    filter_already_done,
)

# ---------------------------------------------------------------------------
# discover_books
# ---------------------------------------------------------------------------


def _make_book(parent: Path, name: str, idml_names: list[str]) -> Path:
    book = parent / name
    book.mkdir(parents=True)
    for n in idml_names:
        (book / n).write_bytes(b"fake idml")
    (book / "Links").mkdir()
    return book


def test_discover_books_finds_idml_in_each_subdir(tmp_path: Path) -> None:
    _make_book(tmp_path, "Anatomia humana", ["006. ANATOMIA HUMANA_P4.idml"])
    _make_book(tmp_path, "Matemática", ["81_Matemática Financeira.idml"])
    _make_book(tmp_path, "Sistemas", ["FIC2 SOP.idml"])

    tasks = discover_books(tmp_path)

    assert len(tasks) == 3
    names = {t.book_dir.name for t in tasks}
    assert names == {"Anatomia humana", "Matemática", "Sistemas"}
    # cada task aponta para o .idml correto
    for t in tasks:
        assert t.idml_path.exists()
        assert t.idml_path.suffix == ".idml"
        assert t.slug  # não-vazio


def test_discover_books_skips_subdir_without_idml(tmp_path: Path) -> None:
    _make_book(tmp_path, "ComIDML", ["a.idml"])
    (tmp_path / "SemIDML").mkdir()
    (tmp_path / "SemIDML" / "Links").mkdir()

    tasks = discover_books(tmp_path)

    assert len(tasks) == 1
    assert tasks[0].book_dir.name == "ComIDML"


def test_discover_books_warns_on_multiple_idml(tmp_path: Path) -> None:
    _make_book(tmp_path, "Duplo", ["a.idml", "b.idml"])
    tasks = discover_books(tmp_path)
    assert len(tasks) == 1
    # usa o primeiro em ordem alfabética
    assert tasks[0].idml_path.name == "a.idml"


def test_discover_books_ignores_loose_files(tmp_path: Path) -> None:
    _make_book(tmp_path, "Livro", ["x.idml"])
    (tmp_path / "README.md").write_text("nope")
    (tmp_path / "stray.idml").write_bytes(b"not a book")

    tasks = discover_books(tmp_path)
    assert len(tasks) == 1
    assert tasks[0].book_dir.name == "Livro"


def test_discover_books_returns_empty_when_input_missing(tmp_path: Path) -> None:
    tasks = discover_books(tmp_path / "doesnotexist")
    assert tasks == []


def test_discover_books_skips_slug_collision(tmp_path: Path) -> None:
    # dois livros com nomes diferentes mas slug idêntico
    _make_book(tmp_path, "A", ["Livro Único.idml"])
    _make_book(tmp_path, "B", ["livro-unico.idml"])

    tasks = discover_books(tmp_path)
    assert len(tasks) == 1


# ---------------------------------------------------------------------------
# filter_already_done
# ---------------------------------------------------------------------------


def test_filter_already_done_skips_existing_output(tmp_path: Path) -> None:
    book = _make_book(tmp_path / "Input", "Livro", ["x.idml"])
    task = BatchTask(book_dir=book, idml_path=book / "x.idml", slug="livro")
    output_dir = tmp_path / "Output"
    output_dir.mkdir()
    (output_dir / "livro.md").write_text("já existe")

    pending, skipped = filter_already_done(
        [task], output_dir, tmp_path / "FEITOS", tmp_path / "ERROS"
    )
    assert pending == []
    assert len(skipped) == 1
    assert skipped[0].status == "skipped"
    assert skipped[0].slug == "livro"


def test_filter_already_done_skips_existing_feitos(tmp_path: Path) -> None:
    book = _make_book(tmp_path / "Input", "Livro", ["x.idml"])
    task = BatchTask(book_dir=book, idml_path=book / "x.idml", slug="livro")
    feitos = tmp_path / "FEITOS"
    (feitos / "Livro").mkdir(parents=True)

    pending, skipped = filter_already_done([task], tmp_path / "Output", feitos, tmp_path / "ERROS")
    assert pending == []
    assert skipped[0].error and "FEITOS" in skipped[0].error


def test_filter_already_done_skips_existing_erros(tmp_path: Path) -> None:
    book = _make_book(tmp_path / "Input", "Livro", ["x.idml"])
    task = BatchTask(book_dir=book, idml_path=book / "x.idml", slug="livro")
    erros = tmp_path / "ERROS"
    (erros / "Livro").mkdir(parents=True)

    pending, skipped = filter_already_done([task], tmp_path / "Output", tmp_path / "FEITOS", erros)
    assert pending == []
    assert skipped[0].error and "ERROS" in skipped[0].error


def test_filter_already_done_passes_through_new_books(tmp_path: Path) -> None:
    book = _make_book(tmp_path / "Input", "Novo", ["x.idml"])
    task = BatchTask(book_dir=book, idml_path=book / "x.idml", slug="novo")

    pending, skipped = filter_already_done(
        [task], tmp_path / "Output", tmp_path / "FEITOS", tmp_path / "ERROS"
    )
    assert len(pending) == 1
    assert pending[0] is task
    assert skipped == []


# ---------------------------------------------------------------------------
# _rewrite_asset_paths
# ---------------------------------------------------------------------------


def test_rewrite_asset_paths_replaces_markdown_image_links() -> None:
    md = "![figura](assets/img/foo.jpg)\n\nOutra: ![](assets/vector/bar.svg)"
    out = _rewrite_asset_paths(md, "meu-livro")
    assert "](meu-livro_assets/img/foo.jpg)" in out
    assert "](meu-livro_assets/vector/bar.svg)" in out
    assert "](assets/" not in out


def test_rewrite_asset_paths_replaces_html_src_double_quote() -> None:
    md = '<img src="assets/eqs/eq001.png" alt="x">'
    out = _rewrite_asset_paths(md, "abc")
    assert 'src="abc_assets/eqs/eq001.png"' in out


def test_rewrite_asset_paths_replaces_html_src_single_quote() -> None:
    md = "<img src='assets/img/y.png'>"
    out = _rewrite_asset_paths(md, "abc")
    assert "src='abc_assets/img/y.png'" in out


def test_rewrite_asset_paths_replaces_reference_links() -> None:
    md = "[fig1]: assets/img/foo.jpg\n[fig2]: assets/vector/bar.svg"
    out = _rewrite_asset_paths(md, "livro")
    assert "[fig1]: livro_assets/img/foo.jpg" in out
    assert "[fig2]: livro_assets/vector/bar.svg" in out


def test_rewrite_asset_paths_leaves_plain_text_untouched() -> None:
    # "assets/" no meio de texto comum, sem ser referência a path, fica
    md = "O termo 'assets/' aparece literalmente aqui, mas não é um link."
    out = _rewrite_asset_paths(md, "x")
    assert out == md


def test_rewrite_asset_paths_handles_multiple_occurrences() -> None:
    md = (
        "![a](assets/img/1.jpg)\n"
        "![b](assets/img/2.jpg)\n"
        "![c](assets/eqs/3.png)\n"
    )
    out = _rewrite_asset_paths(md, "livro")
    assert out.count("livro_assets/") == 3
    # nenhum ](assets/ remanescente — todas as 3 imagens foram reescritas
    assert "](assets/" not in out
