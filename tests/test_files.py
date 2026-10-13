"""write_file: no-clobber creation and safe replacement."""
import os
import stat

import pytest

from atlgames import files
from atlgames.files import write_file


def test_creates_the_file_and_its_directory(tmp_path):
    path = tmp_path / "new" / "dir" / "puzzle.puz"
    assert write_file(path, b"data") == path
    assert path.read_bytes() == b"data"


def test_without_overwrite_an_existing_file_is_kept(tmp_path):
    path = tmp_path / "puzzle.puz"
    path.write_bytes(b"mine")
    with pytest.raises(FileExistsError):
        write_file(path, b"new")
    assert path.read_bytes() == b"mine"


@pytest.mark.skipif(not hasattr(os, "symlink") or os.name == "nt", reason="symlinks")
def test_without_overwrite_symlinks_are_never_followed(tmp_path):
    target = tmp_path / "target.txt"
    target.write_bytes(b"mine")
    link = tmp_path / "link.puz"
    link.symlink_to(target)
    with pytest.raises(FileExistsError):
        write_file(link, b"new")
    assert target.read_bytes() == b"mine"
    dangling = tmp_path / "dangling.puz"
    dangling.symlink_to(tmp_path / "missing.txt")
    with pytest.raises(FileExistsError):
        write_file(dangling, b"new")
    assert not (tmp_path / "missing.txt").exists()


def test_without_overwrite_a_failed_write_leaves_nothing(tmp_path):
    path = tmp_path / "puzzle.puz"
    with pytest.raises(TypeError):
        write_file(path, "not bytes")
    assert not path.exists()


def test_overwrite_replaces_the_file_and_keeps_its_permissions(tmp_path):
    path = tmp_path / "puzzle.puz"
    path.write_bytes(b"old")
    path.chmod(0o640)
    write_file(path, b"new", overwrite=True)
    assert path.read_bytes() == b"new"
    if os.name != "nt":
        assert stat.S_IMODE(path.stat().st_mode) == 0o640
    assert [p.name for p in tmp_path.iterdir()] == ["puzzle.puz"]


def test_overwrite_creates_new_files_readable(tmp_path):
    path = tmp_path / "puzzle.puz"
    write_file(path, b"new", overwrite=True)
    if os.name != "nt":
        assert stat.S_IMODE(path.stat().st_mode) == 0o644


def test_overwrite_failure_keeps_the_previous_file(tmp_path, monkeypatch):
    path = tmp_path / "puzzle.puz"
    path.write_bytes(b"old")

    def fail(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(files.os, "replace", fail)
    with pytest.raises(OSError, match="disk full"):
        write_file(path, b"new", overwrite=True)
    assert path.read_bytes() == b"old"
    assert [p.name for p in tmp_path.iterdir()] == ["puzzle.puz"]  # no temporary file left


@pytest.mark.skipif(not hasattr(os, "symlink") or os.name == "nt", reason="symlinks")
def test_overwrite_replaces_a_symlink_instead_of_following_it(tmp_path):
    target = tmp_path / "target.txt"
    target.write_bytes(b"mine")
    link = tmp_path / "link.puz"
    link.symlink_to(target)
    write_file(link, b"new", overwrite=True)
    assert not link.is_symlink() and link.read_bytes() == b"new"
    assert target.read_bytes() == b"mine"
