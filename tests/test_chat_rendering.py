from pathlib import Path

import pytest

from arqen.tools.workspace_files import SearchWorkspaceFilesTool, WorkspaceFilesTool, describe_size

strip_emphasis = pytest.importorskip("arqen.ui.window", reason="PyQt6 saknas").strip_emphasis


@pytest.mark.parametrize("source", [
    "const a = (i / count) * Math.PI * 2;",
    "ctx.moveTo(c * r, s * r);",
    "total = a * b * c",
    "SELECT * FROM files",
])
def test_arithmetic_survives_the_chat(source: str) -> None:
    """Stripping every asterisk used to turn ``c * r`` into ``c r``."""
    assert strip_emphasis(source) == source


@pytest.mark.parametrize("source, expected", [
    ("Det här är **viktigt** att veta.", "Det här är viktigt att veta."),
    ("Filen är *ganska* stor.", "Filen är ganska stor."),
    ("**Klart:** filen *skapades* nu.", "Klart: filen skapades nu."),
])
def test_emphasis_markers_are_dropped(source: str, expected: str) -> None:
    assert strip_emphasis(source) == expected


def test_sizes_are_readable(tmp_path: Path) -> None:
    small = tmp_path / "small.txt"
    small.write_text("x" * 500, encoding="utf-8")
    medium = tmp_path / "medium.txt"
    medium.write_text("x" * 5_000, encoding="utf-8")
    assert describe_size(small) == "500 B"
    assert describe_size(medium) == "4.9 kB"
    assert describe_size(tmp_path / "finns-inte.txt") == "?"


def test_a_listing_says_how_big_each_file_is(tmp_path, monkeypatch) -> None:
    """Without sizes, 'read the shortest one' means opening every file."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "kort.md").write_text("kort", encoding="utf-8")
    (tmp_path / "lang.md").write_text("x" * 4000, encoding="utf-8")
    (tmp_path / "undermapp").mkdir()

    listing = WorkspaceFilesTool().run({})
    assert "kort.md\t4 B" in listing
    assert "lang.md\t3.9 kB" in listing
    assert "undermapp/" in listing, "directories have no size to report"

    found = SearchWorkspaceFilesTool().run({"query": ".md"})
    assert "kort.md\t4 B" in found
    assert "lang.md\t3.9 kB" in found
