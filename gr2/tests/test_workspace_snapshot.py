"""kind=workspace gr commit: a materialized lane's resolved heads captured as
one gr commit and read back (R2 Milestone 1, section-5 workspace kind)."""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

import pytest

from gr2.prototypes import lane_workspace_prototype as lanes
from gr2.python_cli import commit as commit_ops
from gr2.python_cli import grip
from gr2.python_cli import workspace_snapshot as ws_snap


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=repo, check=check, capture_output=True, text=True)


def _init_repo(path: Path) -> Path:
    path.mkdir(parents=True)
    _git(path, "init", "-b", "main")
    _git(path, "config", "user.name", "Test")
    _git(path, "config", "user.email", "test@example.com")
    (path / "tracked.txt").write_text("initial\n")
    _git(path, "add", ".")
    _git(path, "commit", "-m", "initial")
    return path


def _workspace(tmp_path: Path, repos: list[str]) -> Path:
    ws = tmp_path / "ws"
    grip_dir = ws / ".grip"
    grip_dir.mkdir(parents=True)
    _git(grip_dir, "init", "-b", "main")
    _git(grip_dir, "config", "user.name", "Grip")
    _git(grip_dir, "config", "user.email", "grip@example.com")
    _git(grip_dir, "commit", "--allow-empty", "-m", "init grip")
    repo_blocks = "".join(
        f'\n[[repos]]\nname = "{r}"\npath = "repos/{r}"\nurl = "https://example.invalid/{r}.git"\n'
        for r in repos
    )
    (grip_dir / "workspace_spec.toml").write_text(
        f'schema_version = 1\nworkspace_name = "m"\n{repo_blocks}\n'
        f'[[units]]\nname = "atlas"\npath = "agents/atlas"\nrepos = {repos!r}\n'.replace("'", '"')
    )
    return ws


def _materialized_lane(tmp_path: Path, repos: list[str], lane: str = "feature") -> Path:
    ws = _workspace(tmp_path, repos)
    branch = ",".join(f"{r}=main" for r in repos)
    assert lanes.create_lane(argparse.Namespace(
        workspace_root=ws, owner_unit="atlas", lane_name=lane, type="feature",
        repos=",".join(repos), branch=branch, source="test", default_commands=[],
    )) == 0
    lane_root = lanes.lane_dir(ws, "atlas", lane)
    for r in repos:
        _init_repo(lane_root / "repos" / r)
    return ws


def _commit_lane_change(ws: Path, repos: list[str], lane: str = "feature") -> None:
    lane_root = lanes.lane_dir(ws, "atlas", lane)
    for r in repos:
        (lane_root / "repos" / r / "new.txt").write_text("x\n")
        _git(lane_root / "repos" / r, "add", "new.txt")
    report = commit_ops.commit_lane(ws, "atlas", "lane work", lane_name=lane)
    assert not report.any_failed and report.any_committed


def test_snapshot_lane_round_trips_resolved_heads(tmp_path: Path) -> None:
    ws = _materialized_lane(tmp_path, ["a", "b"])
    _commit_lane_change(ws, ["a", "b"])
    lane_root = lanes.lane_dir(ws, "atlas", "feature")

    commit = ws_snap.snapshot_lane(ws, "atlas", "feature")
    rows = {r["key"]: r for r in ws_snap.read_snapshot(ws, commit)}

    assert set(rows) == {"a", "b"}
    for r in ("a", "b"):
        repo = lane_root / "repos" / r
        head = _git(repo, "rev-parse", "HEAD").stdout.strip()
        base = _git(repo, "rev-parse", "HEAD^").stdout.strip()
        assert rows[r]["commit"] == head
        assert rows[r]["base"] == base
        assert rows[r]["remote"] == f"https://example.invalid/{r}.git"
        assert rows[r]["path"] == f"repos/{r}"
    # The read-back kind is strictly workspace.
    assert _git(ws / ".grip", "show", f"{commit}:.grip/kind").stdout.strip() == "workspace"


def test_read_workspace_commit_reports_every_repo_in_the_tree(tmp_path: Path) -> None:
    # Mutation target: a create that drops one repo from the tree reds this.
    ws = _materialized_lane(tmp_path, ["a", "b"])
    _commit_lane_change(ws, ["a", "b"])
    commit = ws_snap.snapshot_lane(ws, "atlas", "feature")
    assert {r["key"] for r in ws_snap.read_snapshot(ws, commit)} == {"a", "b"}


def test_snapshot_refuses_a_dirty_repo(tmp_path: Path) -> None:
    # Control: an uncommitted repo is refused, not silently recorded — a
    # workspace commit must reproduce the author's actual state.
    ws = _materialized_lane(tmp_path, ["a", "b"])
    _commit_lane_change(ws, ["a", "b"])
    lane_root = lanes.lane_dir(ws, "atlas", "feature")
    (lane_root / "repos" / "b" / "dirty.txt").write_text("uncommitted\n")  # untracked = dirty
    with pytest.raises(ws_snap.WorkspaceSnapshotError, match="uncommitted changes"):
        ws_snap.snapshot_lane(ws, "atlas", "feature")


def test_read_workspace_commit_rejects_a_non_workspace_kind(tmp_path: Path) -> None:
    # Control: the review kind is a different kind; read_workspace_commit refuses it.
    # NOTE: the review kind ALSO carries a different schema, so this case is caught
    # by the schema gate before the kind gate ever runs — see the wrong-kind witness
    # below, which isolates the kind gate specifically.
    ws = _materialized_lane(tmp_path, ["a", "b"])
    _commit_lane_change(ws, ["a", "b"])
    lane_root = lanes.lane_dir(ws, "atlas", "feature")
    pins = [
        {"key": r, "repo": f"https://example.invalid/{r}.git", "path": f"repos/{r}",
         "head": _git(lane_root / "repos" / r, "rev-parse", "HEAD").stdout.strip(),
         "base": _git(lane_root / "repos" / r, "rev-parse", "HEAD^").stdout.strip()}
        for r in ("a", "b")
    ]
    review_commit = grip.create_project_review_commit(ws, pins)
    with pytest.raises(grip.GripCorruptError):
        ws_snap.read_snapshot(ws, review_commit)


def _repo_fields(ws: Path, repos: list[str], lane: str = "feature") -> list[dict[str, str]]:
    """Section-5 field dicts (remote/path/commit/base) drawn from a real lane."""
    lane_root = lanes.lane_dir(ws, "atlas", lane)
    return [
        {"key": r, "remote": f"https://example.invalid/{r}.git", "path": f"repos/{r}",
         "commit": _git(lane_root / "repos" / r, "rev-parse", "HEAD").stdout.strip(),
         "base": _git(lane_root / "repos" / r, "rev-parse", "HEAD^").stdout.strip()}
        for r in repos
    ]


def _write_grip_commit_with_kind(ws: Path, repos: list[dict[str, str]], kind: str) -> str:
    """Build a gr commit through the SAME _mktree/_hash_blob seam create_workspace_commit
    uses, but with the workspace SCHEMA and a parameterized kind blob.

    kind="workspace" is a valid snapshot; any other kind produces a tree whose ONLY
    defect is the kind field — the schema gate passes, so read_workspace_commit's kind
    gate is the sole thing that can reject it. This is the witness the review-kind
    control above cannot be (its schema differs, so the schema gate fires first).
    """
    entries: list[str] = []
    for repo in sorted(repos, key=lambda item: item["key"]):
        fields = [
            f"100644 blob {grip._hash_blob(ws, repo[name])}\t{name}"
            for name in ("remote", "path", "commit", "base")
        ]
        entries.append(f"040000 tree {grip._mktree(ws, fields)}\t{repo['key']}")
    repos_tree = grip._mktree(ws, entries)
    meta_tree = grip._mktree(ws, [
        f"100644 blob {grip._hash_blob(ws, grip._WORKSPACE_SCHEMA)}\tschema",
        f"100644 blob {grip._hash_blob(ws, kind)}\tkind",
    ])
    root_tree = grip._mktree(ws, [f"040000 tree {meta_tree}\t.grip", f"040000 tree {repos_tree}\trepos"])
    commit = grip._commit_tree(ws, root_tree, parent=grip._current_head(ws), message="test kind fixture")
    grip._grip_git(ws, "update-ref", "HEAD", commit)
    return commit


def test_read_workspace_commit_rejects_correct_schema_wrong_kind(tmp_path: Path) -> None:
    # WITNESS for the kind gate (grip.read_workspace_commit lines 132-133): a tree
    # with the correct workspace schema but kind="review". Deleting the kind gate
    # reds this test; the review-kind control above stays green regardless, so
    # without this witness the kind gate does nothing measurable.
    ws = _materialized_lane(tmp_path, ["a", "b"])
    _commit_lane_change(ws, ["a", "b"])
    fields = _repo_fields(ws, ["a", "b"])

    wrong = _write_grip_commit_with_kind(ws, fields, "review")
    with pytest.raises(grip.GripCorruptError, match="wrong kind"):
        ws_snap.read_snapshot(ws, wrong)


def test_write_grip_commit_with_kind_workspace_is_readable(tmp_path: Path) -> None:
    # Positive control proving the builder is otherwise sound: the SAME builder with
    # kind="workspace" round-trips. This is what makes the wrong-kind witness above
    # non-vacuous — the rejection there is the kind field, not a malformed tree.
    ws = _materialized_lane(tmp_path, ["a", "b"])
    _commit_lane_change(ws, ["a", "b"])
    fields = _repo_fields(ws, ["a", "b"])

    good = _write_grip_commit_with_kind(ws, fields, "workspace")
    rows = {r["key"]: r for r in ws_snap.read_snapshot(ws, good)}
    assert set(rows) == {"a", "b"}
    for r in ("a", "b"):
        assert rows[r]["remote"] == f"https://example.invalid/{r}.git"
