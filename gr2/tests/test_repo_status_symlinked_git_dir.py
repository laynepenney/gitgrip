"""Fast-follow: a symlinked ``.git`` gets its own distinct reason, not a
reused "linked worktree" one.

``is_linked_worktree`` (added for the linked-worktree fix) detects a
non-directory ``.git`` by lstat, which is correct for a worktree POINTER
FILE (what ``git worktree add`` produces) but also matched a ``.git`` that
is a SYMLINK into another clone's real git directory -- a different
isolation violation, not an actual git worktree. The BLOCK was already
correct for both cases (both mean the repo does not own its own git state);
only the reported reason was wrong for the symlink case, and would have sent
someone looking for a ``git worktree list`` entry that does not exist.

This mirrors ``clone_exec.py``'s ``verify_clone_isolation``, which already
treats these as two distinct checks with two distinct messages, in the same
order: symlink first, then worktree-pointer-file.
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


def test_inspect_repo_flags_a_symlinked_git_dir_distinctly(tmp_path):
    real = tmp_path / "real"
    _init_repo(real)

    symlinked = tmp_path / "symlinked"
    symlinked.mkdir()
    (symlinked / ".git").symlink_to(real / ".git")

    status = repo_proto.inspect_repo(symlinked)
    assert status.exists
    assert status.is_git_repo
    assert status.git_dir_is_symlink is True
    assert status.linked_worktree is False  # not conflated with the worktree case


def test_inspect_repo_still_flags_a_real_linked_worktree_as_such(tmp_path):
    canonical = tmp_path / "canonical"
    _init_repo(canonical)

    linked = tmp_path / "linked-worktree"
    subprocess.run(
        ["git", "worktree", "add", "-b", "wt-branch", str(linked)],
        cwd=canonical,
        check=True,
        capture_output=True,
        text=True,
    )

    status = repo_proto.inspect_repo(linked)
    assert status.linked_worktree is True
    assert status.git_dir_is_symlink is False  # not conflated with the symlink case


def test_inspect_repo_does_not_flag_an_own_clone_as_either(tmp_path):
    origin = tmp_path / "origin"
    _init_repo(origin)

    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", "-q", str(origin), str(clone)], check=True)

    status = repo_proto.inspect_repo(clone)
    assert status.linked_worktree is False
    assert status.git_dir_is_symlink is False


def test_classify_blocks_a_symlinked_git_dir_with_a_distinct_reason(tmp_path):
    real = tmp_path / "real"
    _init_repo(real)

    symlinked = tmp_path / "symlinked"
    symlinked.mkdir()
    (symlinked / ".git").symlink_to(real / ".git")

    target = repo_proto.RepoTarget(
        scope="shared",
        target_name="symlinked",
        repo_name="symlinked",
        path=symlinked,
        url="https://example.invalid/symlinked.git",
    )
    policy = repo_proto.RepoPolicy(sync_mode="ff-only", dirty_policy="block", tracked_branch=None)
    status = repo_proto.inspect_repo(symlinked)

    action = repo_proto.classify(target, status, policy)
    assert action.action == "block_git_dir_symlink"
    assert action.action != "block_linked_worktree"
    assert "symlink" in action.reason.lower()
    assert "worktree" not in action.reason.lower()
