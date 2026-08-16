"""Executable contract for the native single-repository ``gr2 add`` verb."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=check,
        capture_output=True,
        text=True,
    )


def _init_repo(path: Path) -> Path:
    path.mkdir()
    _git(path, "init", "-b", "main")
    _git(path, "config", "user.name", "Test")
    _git(path, "config", "user.email", "test@example.com")
    (path / "keep.txt").write_text("before\n")
    (path / "delete.txt").write_text("delete me\n")
    _git(path, "add", ".")
    _git(path, "commit", "-m", "initial")
    return path


def _cached_names(repo: Path) -> list[str]:
    output = _git(repo, "diff", "--cached", "--name-only", "-z").stdout
    return [name for name in output.split("\0") if name]


def test_stage_files_stages_added_modified_and_deleted_paths(tmp_path: Path) -> None:
    from gr2.python_cli.add import stage_files

    repo = _init_repo(tmp_path / "repo")
    (repo / "keep.txt").write_text("after\n")
    (repo / "delete.txt").unlink()
    (repo / "new.txt").write_text("new\n")

    result = stage_files(repo, ["keep.txt", "delete.txt", "new.txt"])

    assert result.staged_files == ("delete.txt", "keep.txt", "new.txt")
    assert _cached_names(repo) == ["delete.txt", "keep.txt", "new.txt"]


def test_deleted_path_is_staged_instead_of_misclassified_as_missing(tmp_path: Path) -> None:
    from gr2.python_cli.add import stage_files

    repo = _init_repo(tmp_path / "repo")
    (repo / "delete.txt").unlink()

    result = stage_files(repo, ["delete.txt"])

    assert result.staged_files == ("delete.txt",)
    assert (
        _git(repo, "diff", "--cached", "--diff-filter=D", "--name-only").stdout.strip()
        == "delete.txt"
    )


def test_never_existing_path_refuses_without_touching_the_index(tmp_path: Path) -> None:
    from gr2.python_cli.add import AddError, stage_files

    repo = _init_repo(tmp_path / "repo")

    with pytest.raises(AddError):
        stage_files(repo, ["never-existed.txt"])

    assert _cached_names(repo) == []


def test_result_is_scoped_to_requested_paths_not_the_whole_index(tmp_path: Path) -> None:
    from gr2.python_cli.add import stage_files

    repo = _init_repo(tmp_path / "repo")
    (repo / "keep.txt").write_text("already staged\n")
    _git(repo, "add", "keep.txt")
    (repo / "new.txt").write_text("requested\n")

    result = stage_files(repo, ["new.txt"])

    assert result.staged_files == ("new.txt",)
    assert _cached_names(repo) == ["keep.txt", "new.txt"]


def test_add_cli_defaults_to_the_cwd_repository_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from gr2.python_cli.app import app

    repo_a = _init_repo(tmp_path / "a")
    repo_b = _init_repo(tmp_path / "b")
    (repo_a / "new.txt").write_text("a\n")
    (repo_b / "new.txt").write_text("b\n")
    monkeypatch.chdir(repo_a)

    result = CliRunner().invoke(app, ["add", "new.txt"])

    assert result.exit_code == 0, result.output
    assert _cached_names(repo_a) == ["new.txt"]
    assert _cached_names(repo_b) == []
