"""Row 1 (git am reconstruction): a project-review gr commit can CARRY the
reconstruction range per repo, so a pre-push head is reconstructed from the commit
alone -- no hand `git am`, no clone that already holds the head, no head on any
remote. This ports the review-BIND commit's carry-the-range/reconstruct/assert-tree
model (grip.reconstruct_review_lane) to the PROJECT-review path.

Shape (b), self-describing commit (Stromus, 2026-09-05). The assertion is TREE ==
the pinned head's tree, NOT sha: `git am` re-stamps the committer identity and date
at apply time, so an honest reconstruction has a different sha until the committer-
date-match lane (row 2) lands. The reconstructed sha is recorded beside the pinned
sha so row 2 has its before/after.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from gr2.python_cli import grip


def _git(cwd: Path, *a: str) -> str:
    return subprocess.run(["git", *a], cwd=cwd, text=True, capture_output=True, check=True).stdout.strip()


def _base_remote_and_range(tmp_path: Path) -> tuple[str, str, str, str, str]:
    """A bare origin carrying only BASE, plus a range.patch for a PRE-PUSH head that
    exists in NO clone the caller keeps and on NO remote -- only as the patch bytes.
    Returns (remote_url, base_sha, head_sha, head_tree, range_patch_text)."""
    origin = tmp_path / "alpha.git"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    work = tmp_path / "work"
    _git(tmp_path, "clone", "-q", str(origin), str(work))
    _git(work, "config", "user.email", "a@e.invalid")
    _git(work, "config", "user.name", "a")
    (work / "f.txt").write_text("base\n")
    _git(work, "add", ".")
    _git(work, "commit", "-q", "-m", "base")
    _git(work, "push", "-q", "origin", "main")
    base = _git(work, "rev-parse", "HEAD")
    # the review head: committed locally, NEVER pushed
    (work / "f.txt").write_text("base\nreview change\n")
    (work / "new.txt").write_text("added by the review\n")
    _git(work, "add", ".")
    _git(work, "commit", "-q", "-m", "review head")
    head = _git(work, "rev-parse", "HEAD")
    head_tree = _git(work, "rev-parse", "HEAD^{tree}")
    range_patch = subprocess.run(
        ["git", "format-patch", f"{base}..{head}", "--stdout"],
        cwd=work, text=True, capture_output=True, check=True).stdout
    return str(origin), base, head, head_tree, range_patch


def test_project_review_carries_range_and_reconstructs_tree(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    (ws / ".grip").mkdir(parents=True)
    grip.grip_init(ws)
    remote, base, head, head_tree, range_patch = _base_remote_and_range(tmp_path)

    # create-project records the range for key "alpha" (base + remote + the patch).
    commit = grip.create_project_review_commit(
        ws,
        [{"key": "alpha", "repo": remote, "path": "repos/alpha", "base": base, "head": head}],
        ranges={"alpha": range_patch},
    )
    # the commit carries the range object subtree (self-describing).
    assert "alpha" in grip._tree_keys(ws, commit, "objects")

    # reconstruction: clone remote, checkout base, git am the carried range, assert
    # the resulting TREE equals the pinned head's tree; the sha is recorded, not asserted.
    lane_dir = tmp_path / "lane" / "alpha"
    result = grip.reconstruct_project_review_lane(ws, commit, "alpha", lane_dir)
    assert result["reconstructed_tree"] == head_tree
    assert result["bound_head"] == head            # the pinned head sha
    assert result["reconstructed_head"] != ""      # recorded for row 2's before/after
    # the reconstructed tree is what the range produces (new.txt present).
    assert (lane_dir / "new.txt").read_text() == "added by the review\n"


def test_ranges_referencing_an_unknown_key_is_refused(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    (ws / ".grip").mkdir(parents=True)
    grip.grip_init(ws)
    remote, base, head, _tree, range_patch = _base_remote_and_range(tmp_path)
    with pytest.raises(grip.GripCorruptError, match="not in the pins"):
        grip.create_project_review_commit(
            ws,
            [{"key": "alpha", "repo": remote, "path": "repos/alpha", "base": base, "head": head}],
            ranges={"beta": range_patch},  # beta is not a pinned key
        )


def test_reconstruct_project_review_lane_refuses_a_non_project_commit(tmp_path: Path) -> None:
    # A workspace-KIND commit carries no project-review range; reconstruction must
    # refuse it naming the schema, not blindly try to git am.
    ws = tmp_path / "ws"
    (ws / ".grip").mkdir(parents=True)
    grip.grip_init(ws)
    remote, base, head, _tree, _range = _base_remote_and_range(tmp_path)
    wrong = grip.create_workspace_commit(
        ws, [{"key": "alpha", "remote": remote, "path": "repos/alpha", "commit": head, "base": base}])
    with pytest.raises(grip.GripCorruptError, match="project review"):
        grip.reconstruct_project_review_lane(ws, wrong, "alpha", tmp_path / "lane" / "alpha")
