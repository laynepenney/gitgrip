"""Executable contract for the native single-repository ``gr2 commit`` verb."""

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
    (path / "tracked.txt").write_text("initial\n")
    _git(path, "add", ".")
    _git(path, "commit", "-m", "initial")
    return path


def test_create_commit_returns_the_commit_it_actually_created(tmp_path: Path) -> None:
    from gr2.python_cli.commit import create_commit

    repo = _init_repo(tmp_path / "repo")
    (repo / "tracked.txt").write_text("changed\n")
    _git(repo, "add", "tracked.txt")

    receipt = create_commit(repo, "native commit")

    actual_head = _git(repo, "rev-parse", "HEAD").stdout.strip()
    assert receipt.commit_sha == actual_head
    assert receipt.message == "native commit"
    assert _git(repo, "show", "-s", "--format=%s", "HEAD").stdout.strip() == "native commit"


def test_no_staged_changes_refuses_structurally_before_commit(tmp_path: Path) -> None:
    from gr2.python_cli.commit import NothingToCommitError, create_commit

    repo = _init_repo(tmp_path / "repo")
    head_before = _git(repo, "rev-parse", "HEAD").stdout.strip()

    with pytest.raises(NothingToCommitError):
        create_commit(repo, "must not exist")

    assert _git(repo, "rev-parse", "HEAD").stdout.strip() == head_before


def test_commit_outcome_uses_exit_status_not_command_prose(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from gr2.python_cli import commit as commit_ops

    repo = _init_repo(tmp_path / "repo")
    calls: list[tuple[str, ...]] = []

    def fake_git(_repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        if args[:3] == ("diff", "--cached", "--quiet"):
            return subprocess.CompletedProcess(["git", *args], 1, "", "nothing to commit")
        if args[0] == "commit":
            return subprocess.CompletedProcess(["git", *args], 0, "", "nothing to commit")
        if args == ("rev-parse", "--verify", "HEAD"):
            sha = "b" * 40 if calls.count(args) == 1 else "a" * 40
            return subprocess.CompletedProcess(["git", *args], 0, sha + "\n", "")
        raise AssertionError(args)

    monkeypatch.setattr(commit_ops, "git", fake_git)

    receipt = commit_ops.create_commit(repo, "status wins")

    assert receipt.commit_sha == "a" * 40
    assert any(args[0] == "commit" for args in calls)


def test_acknowledged_commit_without_a_new_head_refuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from gr2.python_cli import commit as commit_ops

    repo = _init_repo(tmp_path / "repo")

    def fake_git(_repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
        if args[:3] == ("diff", "--cached", "--quiet"):
            return subprocess.CompletedProcess(["git", *args], 1, "", "")
        if args[0] == "commit":
            return subprocess.CompletedProcess(["git", *args], 0, "", "")
        if args == ("rev-parse", "--verify", "HEAD"):
            return subprocess.CompletedProcess(["git", *args], 0, "a" * 40 + "\n", "")
        raise AssertionError(args)

    monkeypatch.setattr(commit_ops, "git", fake_git)

    with pytest.raises(commit_ops.CommitError, match="HEAD did not advance"):
        commit_ops.create_commit(repo, "no fruit")


def test_amend_without_new_staged_changes_is_allowed(tmp_path: Path) -> None:
    from gr2.python_cli.commit import create_commit

    repo = _init_repo(tmp_path / "repo")

    receipt = create_commit(repo, "amended message", amend=True)

    assert receipt.amended is True
    assert _git(repo, "show", "-s", "--format=%s", "HEAD").stdout.strip() == "amended message"


def test_commit_cli_defaults_to_the_cwd_repository_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from gr2.python_cli.app import app

    repo_a = _init_repo(tmp_path / "a")
    repo_b = _init_repo(tmp_path / "b")
    for repo in (repo_a, repo_b):
        (repo / "tracked.txt").write_text("changed\n")
        _git(repo, "add", "tracked.txt")
    before_b = _git(repo_b, "rev-parse", "HEAD").stdout.strip()
    monkeypatch.chdir(repo_a)

    result = CliRunner().invoke(app, ["commit", "-m", "cwd only"])

    assert result.exit_code == 0, result.output
    assert _git(repo_a, "show", "-s", "--format=%s", "HEAD").stdout.strip() == "cwd only"
    assert _git(repo_b, "rev-parse", "HEAD").stdout.strip() == before_b
