"""Testes unitários do orquestrador de fila (``idml_to_md.batch``)."""

from __future__ import annotations

from pathlib import Path

from idml_to_md.batch import (
    BatchTask,
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
    # Sentinela: capitulo_1.md da unidade_1 — primeiro arquivo emitido pelo pipeline.
    sentinel = output_dir / "livro" / "unidade_1" / "capitulo_1.md"
    sentinel.parent.mkdir(parents=True)
    sentinel.write_text("já existe")

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


# Os testes de ``_rewrite_asset_paths`` foram removidos: o pipeline novo emite
# caminhos relativos (``../../assets/...``) já corretos para a estrutura final
# ``Output/<slug>/unidade_<N>/capitulo_<M>.md``, então não há mais reescrita
# por regex no batch worker.
