"""Native commit creation for the Python gr2 CLI.

Single-repository by default; lane-aware across a materialized lane's repos
when a workspace + owner unit are supplied (impedance B).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from gr2.prototypes import lane_workspace_prototype as lane_proto

from .gitops import git


class CommitError(Exception):
    pass


class NothingToCommitError(CommitError):
    pass


@dataclass(frozen=True)
class CommitReceipt:
    commit_sha: str
    message: str
    amended: bool


def _head_sha(repo: Path, *, required: bool) -> str | None:
    try:
        result = git(repo, "rev-parse", "--verify", "HEAD")
    except OSError as exc:
        raise CommitError(f"failed to resolve HEAD in {repo}: {exc}") from exc
    sha = result.stdout.strip() if result.returncode == 0 else ""
    if required and not sha:
        raise CommitError("git commit succeeded but the resulting HEAD could not be verified")
    return sha or None


def _staged_changes_exist(repo: Path) -> bool:
    try:
        probe = git(repo, "diff", "--cached", "--quiet", "--exit-code")
    except OSError as exc:
        raise CommitError(f"failed to inspect the staged index in {repo}: {exc}") from exc
    if probe.returncode == 0:
        return False
    if probe.returncode == 1:
        return True
    detail = (probe.stderr or probe.stdout).strip()
    raise CommitError(detail or f"staged-index probe failed with exit {probe.returncode}")


def _refuse_review_ephemeral_repo(repo: Path) -> None:
    """A review-ephemeral lane repo carries a review record naming its kind. Refuse
    a commit into it directly (the reviewer's cwd is inside the review lane), so a
    review lane never becomes a work lane through the single-repo path."""
    import json as _json
    record = Path(repo) / ".git" / "grip-review.json"
    try:
        kind = _json.loads(record.read_text()).get("lane_kind")
    except (OSError, ValueError):
        return
    if kind == "review-ephemeral":
        raise CommitError(
            f"{repo} is a review-ephemeral review lane (read-only, disposable): it "
            "cannot be committed to. A review lane never becomes a work lane."
        )


def create_commit(repo: Path, message: str, *, amend: bool = False) -> CommitReceipt:
    """Create a commit and return the immutable commit ID observed afterward.

    A normal commit first asks the index whether a staged diff exists. It never
    classifies "nothing to commit" by localized or version-dependent prose.
    Amend is allowed without a new staged diff because changing only the prior
    commit message is a valid amend operation.
    """
    if not message:
        raise CommitError("commit message must not be empty")
    _refuse_review_ephemeral_repo(repo)
    if not amend and not _staged_changes_exist(repo):
        raise NothingToCommitError("no staged changes to commit")

    head_before = _head_sha(repo, required=False)

    args = ["commit"]
    if amend:
        args.append("--amend")
    args.extend(["-m", message])
    try:
        committed = git(repo, *args)
    except OSError as exc:
        raise CommitError(f"failed to launch git commit in {repo}: {exc}") from exc
    if committed.returncode != 0:
        detail = (committed.stderr or committed.stdout).strip()
        raise CommitError(detail or f"git commit failed with exit {committed.returncode}")

    commit_sha = _head_sha(repo, required=True)
    assert commit_sha is not None
    if commit_sha == head_before:
        raise CommitError(
            f"git commit returned success but HEAD did not advance from {head_before}"
        )
    return CommitReceipt(commit_sha=commit_sha, message=message, amended=amend)


# --- lane-aware commit (impedance B) --------------------------------------


@dataclass(frozen=True)
class LaneRepoCommit:
    repo: str
    status: str  # "committed" | "skipped_empty" | "failed"
    commit_sha: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class LaneCommitReport:
    owner_unit: str
    lane_name: str
    lane_kind: str
    results: list[LaneRepoCommit] = field(default_factory=list)

    @property
    def any_committed(self) -> bool:
        return any(r.status == "committed" for r in self.results)

    @property
    def any_failed(self) -> bool:
        return any(r.status == "failed" for r in self.results)


def _lane_repo_targets(
    workspace_root: Path, owner_unit: str, lane_name: str, doc: dict
) -> list[tuple[str, Path]]:
    """(repo_key, repo_root) for each repo the lane commit should touch.

    A bound lane is single-repo: its one repo lives in the author's bound
    worktree, not under the lane state tree. A materialized lane commits each
    of its repos/<key> checkouts.
    """
    kind = doc.get("lane_kind", "materialized")
    repos = list(doc.get("repos", []))
    if kind == "bound":
        worktree = doc.get("bound_worktree")
        if not worktree:
            raise CommitError(
                f"bound lane {owner_unit}/{lane_name} records no bound_worktree"
            )
        key = repos[0] if repos else "bound"
        return [(key, Path(worktree))]
    lane_root = lane_proto.lane_dir(workspace_root, owner_unit, lane_name)
    return [(repo, lane_root / "repos" / repo) for repo in repos]


def commit_lane(
    workspace_root: Path,
    owner_unit: str,
    message: str,
    *,
    lane_name: str | None = None,
    amend: bool = False,
) -> LaneCommitReport:
    """Commit each repo of a lane under one message.

    Repos with an empty staged index are skipped and reported (never an empty
    commit). A repo whose commit fails is recorded as failed and does NOT roll
    back the repos already committed; the report names it so the caller can act.
    Bound lanes stay single-repo (the bound worktree).
    """
    if not message:
        raise CommitError("commit message must not be empty")
    workspace_root = Path(workspace_root).resolve()
    if lane_name is None:
        lane_name = lane_proto.require_current_lane(workspace_root, owner_unit)["lane_name"]
    doc = lane_proto.load_lane_doc(workspace_root, owner_unit, lane_name)
    kind = doc.get("lane_kind", "materialized")
    if kind == "review-ephemeral":
        raise CommitError(
            f"lane {owner_unit}/{lane_name} is a review-ephemeral lane (read-only, "
            "disposable): it cannot be committed to. A review lane never becomes a "
            "work lane; exit the review and open a work lane to make changes."
        )

    results: list[LaneRepoCommit] = []
    for repo_key, repo_root in _lane_repo_targets(workspace_root, owner_unit, lane_name, doc):
        try:
            if not amend and not _staged_changes_exist(repo_root):
                results.append(LaneRepoCommit(repo_key, "skipped_empty"))
                continue
            receipt = create_commit(repo_root, message, amend=amend)
            results.append(LaneRepoCommit(repo_key, "committed", commit_sha=receipt.commit_sha))
        except CommitError as exc:
            results.append(LaneRepoCommit(repo_key, "failed", error=str(exc)))
    return LaneCommitReport(owner_unit=owner_unit, lane_name=lane_name, lane_kind=kind, results=results)
