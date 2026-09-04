"""Capture a materialized lane's resolved repository state as one kind=workspace
gr commit (R2 Milestone 1, the section-5 semantic tree for the workspace kind).

The workspace gr commit is a reproduction coordinate: it records, per repo, the
exact head a checkout must materialize plus the base it builds on. A repo with
uncommitted changes is REFUSED, not recorded — snapshotting a dirty tree would
record a coordinate that does not reproduce the author's actual state. Commit
the lane first (``gr2 commit`` lane-aware), then snapshot.
"""

from __future__ import annotations

from pathlib import Path

from gr2.prototypes import lane_workspace_prototype as lane_proto

from . import grip
from .gitops import git, repo_dirty


class WorkspaceSnapshotError(Exception):
    pass


def _resolve_head(repo_root: Path, key: str) -> tuple[str, str]:
    """(commit, base) for one lane repo: HEAD and the parent it builds on."""
    head = git(repo_root, "rev-parse", "--verify", "HEAD")
    if head.returncode != 0 or not head.stdout.strip():
        raise WorkspaceSnapshotError(f"repo {key} has no HEAD to snapshot")
    commit = head.stdout.strip()
    parent = git(repo_root, "rev-parse", "--verify", "HEAD^")
    if parent.returncode != 0 or not parent.stdout.strip():
        raise WorkspaceSnapshotError(
            f"repo {key} has no base commit (root-only); nothing to build the snapshot base on"
        )
    return commit, parent.stdout.strip()


def resolve_lane_repos(workspace_root: Path, owner_unit: str, lane_name: str) -> list[dict[str, str]]:
    """Resolve every repo of a materialized lane into the section-5 fields.

    Refuses a repo with uncommitted changes (a snapshot must reproduce).
    """
    workspace_root = Path(workspace_root).resolve()
    doc = lane_proto.load_lane_doc(workspace_root, owner_unit, lane_name)
    spec = lane_proto.load_workspace_spec(workspace_root)
    spec_by_name = {r.get("name"): r for r in spec.get("repos", [])}
    lane_root = lane_proto.lane_dir(workspace_root, owner_unit, lane_name)

    resolved: list[dict[str, str]] = []
    for key in doc.get("repos", []):
        repo_root = lane_root / "repos" / key
        if not (repo_root / ".git").exists():
            raise WorkspaceSnapshotError(f"repo {key} is not materialized at {repo_root}")
        if repo_dirty(repo_root):
            raise WorkspaceSnapshotError(
                f"repo {key} has uncommitted changes; commit the lane before snapshotting"
            )
        repo_spec = spec_by_name.get(key)
        if not repo_spec:
            raise WorkspaceSnapshotError(f"repo {key} is not in the workspace spec")
        commit, base = _resolve_head(repo_root, key)
        resolved.append({
            "key": key,
            "remote": str(repo_spec.get("url", "")),
            "path": str(repo_spec.get("path", "")),
            "commit": commit,
            "base": base,
        })
    return resolved


def snapshot_lane(workspace_root: Path, owner_unit: str, lane_name: str) -> str:
    """Resolve a materialized lane and write one kind=workspace gr commit.

    Returns the gr commit id (the reproduction coordinate).
    """
    workspace_root = Path(workspace_root).resolve()
    repos = resolve_lane_repos(workspace_root, owner_unit, lane_name)
    if not repos:
        raise WorkspaceSnapshotError(f"lane {owner_unit}/{lane_name} has no repos to snapshot")
    return grip.create_workspace_commit(workspace_root, repos)


def read_snapshot(workspace_root: Path, commit: str) -> list[dict[str, str]]:
    """Decode a kind=workspace gr commit's resolved repository fields."""
    return grip.read_workspace_commit(Path(workspace_root).resolve(), commit)
