"""Native single-repository commit creation for the Python gr2 CLI."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

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


def create_commit(repo: Path, message: str, *, amend: bool = False) -> CommitReceipt:
    """Create a commit and return the immutable commit ID observed afterward.

    A normal commit first asks the index whether a staged diff exists. It never
    classifies "nothing to commit" by localized or version-dependent prose.
    Amend is allowed without a new staged diff because changing only the prior
    commit message is a valid amend operation.
    """
    if not message:
        raise CommitError("commit message must not be empty")
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
