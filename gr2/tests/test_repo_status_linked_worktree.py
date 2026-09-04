"""Contract: ``repo status`` flags a hand-made linked worktree as a violation.

``inspect_repo``'s existing repo-detection used ``git rev-parse
--is-inside-work-tree``, which answers ``true`` inside a linked worktree just
as it does inside a real clone -- the same trap ``clone_exec.py``'s
``verify_clone_isolation`` docstring names explicitly for gr2's lane-clone
path. So a hand-run ``git worktree add`` at a desk-level repo path was
invisible to ``repo status``: it read as an ordinary, healthy repo.

The fix distinguishes them the same way ``clone_exec.py`` does -- by lstat-ing
``.git`` rather than trusting ``is-inside-work-tree`` -- and ``classify``
returns a dedicated ``block_linked_worktree`` action before any of the
branch/dirty logic runs, since the structural problem exists independent of
repo state.

Both tests build real repos with real git commands; neither is a fixture that
might disagree with what ``git worktree add`` actually produces.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from gr2.prototypes import repo_maintenance_prototype as repo_proto


def _init_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "dev@layne.pro"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Layne Penney"], cwd=path, check=True)
    (path / "README.md").write_text("a\n")
    subprocess.run(["git", "add", "."], cwd=path, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=path, check=True)


def test_inspect_repo_flags_a_real_linked_worktree(tmp_path):
    canonical = tmp_path / "canonical"
    _init_repo(canonical)

    linked = tmp_path / "linked-worktree"
    result = subprocess.run(
        ["git", "worktree", "add", "-b", "wt-branch", str(linked)],
        cwd=canonical,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr

    status = repo_proto.inspect_repo(linked)
    assert status.exists
    assert status.is_git_repo  # is-inside-work-tree still answers true -- that's the trap
    assert status.linked_worktree is True


def test_inspect_repo_does_not_flag_an_own_clone(tmp_path):
    origin = tmp_path / "origin"
    _init_repo(origin)

    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", "-q", str(origin), str(clone)], check=True)

    status = repo_proto.inspect_repo(clone)
    assert status.exists
    assert status.is_git_repo
    assert status.linked_worktree is False


def test_classify_blocks_a_linked_worktree_before_any_other_check(tmp_path):
    canonical = tmp_path / "canonical"
    _init_repo(canonical)

    linked = tmp_path / "linked-worktree"
    subprocess.run(
        ["git", "worktree", "add", "-b", "wt-branch2", str(linked)],
        cwd=canonical,
        check=True,
        capture_output=True,
        text=True,
    )

    target = repo_proto.RepoTarget(
        scope="shared",
        target_name="linked-worktree",
        repo_name="linked-worktree",
        path=linked,
        url="https://example.invalid/linked-worktree.git",
    )
    policy = repo_proto.RepoPolicy(sync_mode="ff-only", dirty_policy="block", tracked_branch=None)
    status = repo_proto.inspect_repo(linked)

    action = repo_proto.classify(target, status, policy)
    assert action.action == "block_linked_worktree"
    assert "worktree" in action.reason.lower()


def test_classify_does_not_block_an_own_clone(tmp_path):
    origin = tmp_path / "origin"
    _init_repo(origin)

    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", "-q", str(origin), str(clone)], check=True)

    target = repo_proto.RepoTarget(
        scope="shared",
        target_name="clone",
        repo_name="clone",
        path=clone,
        url="https://example.invalid/clone.git",
    )
    policy = repo_proto.RepoPolicy(sync_mode="ff-only", dirty_policy="block", tracked_branch=None)
    status = repo_proto.inspect_repo(clone)

    action = repo_proto.classify(target, status, policy)
    assert action.action != "block_linked_worktree"
