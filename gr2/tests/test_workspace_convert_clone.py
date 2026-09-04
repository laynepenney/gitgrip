"""Step 3 of the worktree-refactor ruling: ``convert_worktree_to_clone``
converts a linked worktree into an own clone, in place, replacing the
by-hand proof (config main, worktree-refactor design note) with real code.

The witness: ``.git`` lstat before (a worktree pointer file) and after (a
real directory) at the SAME path, plus the canonical repo's own
``worktree list`` showing the link genuinely gone -- not merely hidden.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from gr2.prototypes import repo_maintenance_prototype as repo_proto


def _init_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "dev@layne.pro"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Layne Penney"], cwd=path, check=True)
    (path / "README.md").write_text("a\n")
    subprocess.run(["git", "add", "."], cwd=path, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=path, check=True)


def test_convert_worktree_to_clone_replaces_the_pointer_file_with_a_real_directory(tmp_path):
    canonical = tmp_path / "canonical"
    _init_repo(canonical)

    linked = tmp_path / "linked-worktree"
    subprocess.run(
        ["git", "worktree", "add", "-b", "convert-branch", str(linked)],
        cwd=canonical,
        check=True,
        capture_output=True,
        text=True,
    )

    before_status = repo_proto.inspect_repo(linked)
    assert before_status.linked_worktree is True  # precondition the fix needs

    receipt = repo_proto.convert_worktree_to_clone(linked)

    # The witness: .git at the SAME path, before a pointer file, now a real directory.
    assert receipt["before_git_lstat"]["is_regular_file"] is True
    assert receipt["before_git_lstat"]["is_dir"] is False
    assert receipt["after_git_lstat"]["is_dir"] is True
    assert receipt["after_git_lstat"]["is_regular_file"] is False

    # The canonical repo's OWN worktree list no longer carries the link -- not
    # merely hidden from some other view, actually removed from the registry
    # `git worktree list` reads.
    list_result = subprocess.run(
        ["git", "worktree", "list", "--porcelain"],
        cwd=canonical,
        check=True,
        capture_output=True,
        text=True,
    )
    assert str(linked) not in list_result.stdout

    # The converted path is a real, independent, functioning clone.
    after_status = repo_proto.inspect_repo(linked)
    assert after_status.linked_worktree is False
    assert after_status.git_dir_is_symlink is False
    assert after_status.is_git_repo is True
    assert after_status.branch == "convert-branch"


def test_convert_worktree_to_clone_refuses_a_dirty_tree(tmp_path):
    canonical = tmp_path / "canonical"
    _init_repo(canonical)

    linked = tmp_path / "linked-worktree"
    subprocess.run(
        ["git", "worktree", "add", "-b", "dirty-branch", str(linked)],
        cwd=canonical,
        check=True,
        capture_output=True,
        text=True,
    )
    (linked / "untracked.txt").write_text("uncommitted\n")

    with pytest.raises(repo_proto.ConvertCloneError, match="dirty"):
        repo_proto.convert_worktree_to_clone(linked)

    # Refused BEFORE any mutation -- the worktree link is untouched.
    list_result = subprocess.run(
        ["git", "worktree", "list", "--porcelain"],
        cwd=canonical,
        check=True,
        capture_output=True,
        text=True,
    )
    assert str(linked) in list_result.stdout


def test_convert_worktree_to_clone_refuses_a_symlinked_git_dir(tmp_path):
    real = tmp_path / "real"
    _init_repo(real)

    symlinked = tmp_path / "symlinked"
    symlinked.mkdir()
    (symlinked / ".git").symlink_to(real / ".git")

    with pytest.raises(repo_proto.ConvertCloneError, match="symlink"):
        repo_proto.convert_worktree_to_clone(symlinked)


def test_convert_worktree_to_clone_refuses_an_own_clone(tmp_path):
    origin = tmp_path / "origin"
    _init_repo(origin)

    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", "-q", str(origin), str(clone)], check=True)

    with pytest.raises(repo_proto.ConvertCloneError, match="not a linked worktree"):
        repo_proto.convert_worktree_to_clone(clone)
