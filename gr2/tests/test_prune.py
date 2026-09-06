"""gr2 `prune`: merged-branch detection by patch-id + squash tree, never
containment alone.

The load-bearing cases are the MOAT (a rebase/cherry-pick-merged branch that
`git branch --merged` -- gr1's mechanism -- does NOT report, but patch-id does)
and the SAFETY (an unmerged branch is never listed and never deleted, in any
mode). Each test builds a real, hermetic git repo with subprocess git.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from gr2.python_cli import prune as prune_ops


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, text=True, capture_output=True, check=True
    ).stdout.strip()


def _repo(root: Path) -> Path:
    """A repo on branch `dev` with one base commit."""
    repo = root / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "dev")
    _git(repo, "config", "user.email", "prune@example.invalid")
    _git(repo, "config", "user.name", "prune-test")
    (repo / "base.txt").write_text("base\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "base")
    return repo


def _commit(repo: Path, name: str, content: str, msg: str) -> str:
    (repo / name).write_text(content)
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", msg)
    return _git(repo, "rev-parse", "HEAD")


def _branch_merged_containment(repo: Path, target: str, branch: str) -> bool:
    """gr1's mechanism, as a control: `git branch --merged <target>`."""
    out = _git(repo, "branch", "--merged", target, "--format=%(refname:short)")
    return branch in out.splitlines()


def test_plain_merged_branch_is_pruned_by_patch_id(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _git(repo, "checkout", "-q", "-b", "feature")
    _commit(repo, "f.txt", "feature\n", "feature work")
    _git(repo, "checkout", "-q", "dev")
    _git(repo, "merge", "-q", "--no-ff", "feature", "-m", "merge feature")

    merged, _ = prune_ops.list_merged_branches(repo, "dev")
    names = {m.name: m.reason for m in merged}
    assert "feature" in names
    assert names["feature"] == "patch-id"


def test_rebase_merged_branch_containment_misses_but_patch_id_catches(tmp_path: Path) -> None:
    """THE MOAT: a branch whose commit landed on the target by cherry-pick has a
    tip that is NOT an ancestor of the target, so gr1's `git branch --merged`
    excludes it -- while its work IS in the target by patch-id. prune catches it.
    """
    repo = _repo(tmp_path)
    _git(repo, "checkout", "-q", "-b", "feature")
    feat_sha = _commit(repo, "f.txt", "feature\n", "feature work")
    _git(repo, "checkout", "-q", "dev")
    # dev advances with its OWN commit first, so the cherry-pick below lands on a
    # different parent and gets a NEW sha (same patch-id) -- otherwise git would
    # reproduce feature's exact commit and dev would fast-forward onto it.
    _commit(repo, "dev-only.txt", "dev\n", "unrelated dev work")
    _git(repo, "cherry-pick", feat_sha)  # dev gets feature's change as a NEW sha

    # Control: gr1's containment mechanism does NOT see it merged.
    assert _branch_merged_containment(repo, "dev", "feature") is False
    # But its tip is not an ancestor either (proves the scenario is a real gap).
    assert _git(repo, "rev-parse", "feature") != _git(repo, "rev-parse", "dev")

    merged, _ = prune_ops.list_merged_branches(repo, "dev")
    names = {m.name: m.reason for m in merged}
    assert names.get("feature") == "patch-id"


def test_squash_merged_branch_is_pruned_by_tree(tmp_path: Path) -> None:
    """A squash-merge gives the combined change a brand-new commit whose
    per-commit patch-ids never match the branch's originals -- `git cherry`
    cannot see it. The squash tree check (aggregate patch-id == a first-parent
    target commit's patch-id) does."""
    repo = _repo(tmp_path)
    _git(repo, "checkout", "-q", "-b", "feature")
    _commit(repo, "a.txt", "a\n", "c1")
    _commit(repo, "b.txt", "b\n", "c2")
    _git(repo, "checkout", "-q", "dev")
    _git(repo, "merge", "-q", "--squash", "feature")
    _git(repo, "commit", "-q", "-m", "squashed feature")

    # Confirm cherry alone would NOT flag it (the reason the squash path exists).
    cherry_merged, plus = prune_ops._cherry_merged(repo, "dev", "feature")
    assert cherry_merged is False and plus == 2

    merged, _ = prune_ops.list_merged_branches(repo, "dev")
    names = {m.name: m.reason for m in merged}
    assert names.get("feature") == "squash"


def test_unmerged_branch_is_never_listed_or_deleted(tmp_path: Path) -> None:
    """SAFETY: a branch with work absent from the target is never reported and
    never deleted, in dry-run or --execute. This is the one that must never
    regress -- deleting unmerged work is the harm the whole verb guards against.
    """
    repo = _repo(tmp_path)
    _git(repo, "checkout", "-q", "-b", "feature")
    _commit(repo, "f.txt", "unmerged\n", "unmerged work")
    _git(repo, "checkout", "-q", "dev")

    merged, _ = prune_ops.list_merged_branches(repo, "dev")
    assert all(m.name != "feature" for m in merged)

    report = prune_ops.prune(repo, target="dev", execute=True)
    assert "feature" not in report.deleted
    assert _git(repo, "rev-parse", "--verify", "refs/heads/feature")  # still exists


def test_protected_branches_are_never_candidates(tmp_path: Path) -> None:
    """current branch, the target's short name, main, and dev are never listed,
    even when their work is in the target."""
    repo = _repo(tmp_path)
    # A branch literally named main, fully merged (its content is in dev's base).
    _git(repo, "branch", "main", "dev")
    # The current branch is dev (the target).
    merged, protected = prune_ops.list_merged_branches(repo, "dev")
    listed = {m.name for m in merged}
    assert "main" not in listed
    assert "dev" not in listed
    assert "main" in protected and "dev" in protected


def test_target_own_short_name_branch_is_never_pruned(tmp_path: Path) -> None:
    """The target's OWN short-name branch must never be a candidate. A branch is
    merged against itself by patch-id (`git cherry topic topic` is empty), so
    without protecting the target's short name a `prune --target topic` on a
    checkout that also has a local `topic` branch (not current, not main/dev)
    would -D the very branch it is measuring against. This is the witness for
    the protected.add(_short(target)) guard; dropping that line makes this red.
    """
    repo = _repo(tmp_path)
    # A local branch named like a non-dev/main target, holding already-merged
    # content; the current branch stays dev so ONLY the target-short-name guard
    # can protect it.
    _git(repo, "branch", "topic", "dev")

    merged, protected = prune_ops.list_merged_branches(repo, "topic")
    assert all(m.name != "topic" for m in merged)
    assert "topic" in protected

    report = prune_ops.prune(repo, target="topic", execute=True)
    assert "topic" not in report.deleted
    assert _git(repo, "rev-parse", "--verify", "refs/heads/topic")  # still exists


def test_current_branch_is_protected_even_when_merged(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _git(repo, "checkout", "-q", "-b", "feature")
    _commit(repo, "f.txt", "feature\n", "feature work")
    _git(repo, "checkout", "-q", "dev")
    _git(repo, "merge", "-q", "--no-ff", "feature", "-m", "merge feature")
    # Stay ON feature: it is merged, but it is the current branch.
    _git(repo, "checkout", "-q", "feature")
    merged, protected = prune_ops.list_merged_branches(repo, "dev")
    assert all(m.name != "feature" for m in merged)
    assert "feature" in protected


def test_dry_run_reports_but_does_not_delete(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _git(repo, "checkout", "-q", "-b", "feature")
    _commit(repo, "f.txt", "feature\n", "feature work")
    _git(repo, "checkout", "-q", "dev")
    _git(repo, "merge", "-q", "--no-ff", "feature", "-m", "merge feature")

    report = prune_ops.prune(repo, target="dev", execute=False)
    assert any(m.name == "feature" for m in report.merged)
    assert report.deleted == []
    assert _git(repo, "rev-parse", "--verify", "refs/heads/feature")  # not deleted


def test_execute_deletes_only_the_merged_branch(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    # merged branch
    _git(repo, "checkout", "-q", "-b", "done")
    _commit(repo, "done.txt", "done\n", "done work")
    _git(repo, "checkout", "-q", "dev")
    _git(repo, "merge", "-q", "--no-ff", "done", "-m", "merge done")
    # unmerged branch
    _git(repo, "checkout", "-q", "-b", "wip")
    _commit(repo, "wip.txt", "wip\n", "wip work")
    _git(repo, "checkout", "-q", "dev")

    report = prune_ops.prune(repo, target="dev", execute=True)
    assert report.deleted == ["done"]
    with pytest.raises(subprocess.CalledProcessError):
        _git(repo, "rev-parse", "--verify", "refs/heads/done")  # gone
    assert _git(repo, "rev-parse", "--verify", "refs/heads/wip")  # kept


def test_resolve_target_missing_ref_raises(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    with pytest.raises(prune_ops.PruneError):
        prune_ops.resolve_target(repo, "origin/nonexistent", "origin")


def test_resolve_target_explicit_is_used(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    ref, source = prune_ops.resolve_target(repo, "dev", "origin")
    assert ref == "dev"
    assert "explicit" in source


def _set_remote_tracking(repo: Path, name: str, sha: str) -> None:
    _git(repo, "update-ref", f"refs/remotes/origin/{name}", sha)


def test_default_target_prefers_dev_over_origin_head(tmp_path: Path) -> None:
    """The reorder witness: origin/HEAD points at main on a fresh clone, so
    resolving HEAD first would measure prune against main and read dev-merged
    branches as unmerged. dev must win. (Old HEAD-first order returned main.)"""
    repo = _repo(tmp_path)
    sha = _git(repo, "rev-parse", "HEAD")
    _set_remote_tracking(repo, "dev", sha)
    _set_remote_tracking(repo, "main", sha)
    _git(repo, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")

    ref, source = prune_ops.resolve_target(repo, None, "origin")
    assert ref == "origin/dev"
    assert "integration branch" in source


def test_default_target_falls_to_origin_head_when_no_dev(tmp_path: Path) -> None:
    """No origin/dev: fall to the remote's own default via origin/HEAD."""
    repo = _repo(tmp_path)
    sha = _git(repo, "rev-parse", "HEAD")
    _set_remote_tracking(repo, "main", sha)
    _git(repo, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")

    ref, source = prune_ops.resolve_target(repo, None, "origin")
    assert ref == "origin/main"
    assert "origin/HEAD" in source


def test_default_target_falls_to_main_when_no_dev_and_no_head_symref(tmp_path: Path) -> None:
    """The bare main-fallback branch: origin/main exists but there is no
    origin/dev and no origin/HEAD symref. Resolves to origin/main via the
    fallback, not a raise. Witnesses the main-fallback branch itself (the
    HEAD-driven test above never exercises it); dropping that branch reds this.
    """
    repo = _repo(tmp_path)
    sha = _git(repo, "rev-parse", "HEAD")
    _set_remote_tracking(repo, "main", sha)  # no dev, no origin/HEAD symref

    ref, source = prune_ops.resolve_target(repo, None, "origin")
    assert ref == "origin/main"
    assert source == "fallback (origin/main)"


def test_default_target_raises_when_nothing_resolves(tmp_path: Path) -> None:
    repo = _repo(tmp_path)  # no remote-tracking refs at all
    with pytest.raises(prune_ops.PruneError):
        prune_ops.resolve_target(repo, None, "origin")
