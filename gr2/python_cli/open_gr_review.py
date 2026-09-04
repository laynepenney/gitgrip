"""Project-tier open-gr --enter: one review-kind gr commit opens one exact
multi-repository review, and exit returns the agent to its prior work.

Composes the repo-tier review open (``project_review.open_project_review``, which
materializes each pinned head and enters the review lane) with a project-tier
receipt naming the gr commit and the per-repo base/head, plus an exit that
restores the prior lane AND the prior cwd. The review's per-repo ``base`` is the
recorded fork base (it rode in with the review-kind pins), so one gr commit opens
the exact review the author bound.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

from gr2.prototypes import lane_workspace_prototype as lane_proto

from . import grip, project_review, review
from .gitops import git


class OpenGrReviewError(Exception):
    pass


_RECEIPT_NAME = ".grip-open-gr.json"


def _pin_transport_location(pin_repo: str) -> str:
    """The clone LOCATION named by a pin's recorded remote.

    A ``local:`` fixture prefix names a filesystem path; every other identity
    (HTTPS/SSH) is its own clone URL. For a ``local:`` checkout we clone from its
    ORIGIN (not the checkout itself), mirroring ``_canonical_repo_identity`` so
    the resolved source's origin canonicalizes to the SAME identity the pin
    carries -- otherwise ``_validate_workspace_repository_boundary`` refuses the
    resolved source as an identity mismatch. This is transport only; that
    boundary check remains the authority regardless of what we clone from.
    """
    if pin_repo.startswith("local:"):
        local = Path(pin_repo.removeprefix("local:"))
        origin = review.gitops.remote_origin_url(local) if local.is_dir() else None
        return origin or str(local)
    return pin_repo


def resolve_sources_from_pins(
    pins: list[project_review.ProjectReviewPin] | tuple[project_review.ProjectReviewPin, ...],
    staging_dir: Path | str,
    *,
    allow_local: bool = False,
) -> dict[str, tuple[Path, str]]:
    """Build the source transport map from each pin's RECORDED REMOTE.

    For each pin, clone ``pin.repo`` into ``staging_dir/<key>`` and confirm the
    pin's base AND head are commits there. The returned ``review_branch`` is the
    head sha itself: ``git rev-parse --verify <sha>^{commit}`` resolves a sha to
    itself, and ``open_review_lane`` only requires a ref that resolves to
    ``expected_head_sha`` -- so no synthetic branch is minted.

    A recorded remote that does not carry the pinned head is refused HERE, before
    any review lane opens -- the recorded-remote analogue of the transport map's
    "missing source" refusal. This is the production shape: ``open-gr`` resolves
    what to review from the review-kind commit alone, with no hand-passed
    author-clone map.
    """
    staging_dir = Path(staging_dir)
    staging_dir.mkdir(parents=True, exist_ok=True)
    srcmap: dict[str, tuple[Path, str]] = {}
    for pin in pins:
        location = _pin_transport_location(pin.repo)
        dest = staging_dir / pin.key
        if dest.exists():
            raise OpenGrReviewError(f"open-gr staging destination already exists: {dest}")
        cloned = git(staging_dir, "clone", "--quiet", "--no-checkout", location, str(dest))
        if cloned.returncode != 0:
            raise OpenGrReviewError(
                f"cannot resolve source for {pin.key!r} from recorded remote {location!r}: "
                f"{cloned.stderr.strip()}"
            )
        for label, sha in (("base", pin.base), ("head", pin.head)):
            if git(dest, "cat-file", "-e", f"{sha}^{{commit}}").returncode != 0:
                raise OpenGrReviewError(
                    f"recorded remote for {pin.key!r} does not carry {label} {sha}: the pinned "
                    f"head must be published to the pinned remote for a remote-resolved open-gr"
                )
        srcmap[pin.key] = (dest, pin.head)
    return srcmap


def open_gr_receipt_path(review_root: Path) -> Path:
    """The project-tier receipt lives at the review lane root (not a repo's .git),
    because it names the whole review, not one member."""
    return Path(review_root) / _RECEIPT_NAME


def _current_lane_name(workspace: Path, owner_unit: str) -> str | None:
    try:
        return lane_proto.require_current_lane(workspace, owner_unit).get("lane_name")
    except SystemExit:
        return None


def open_gr_enter(
    workspace: Path,
    owner_unit: str,
    lane_name: str,
    gr_commit: str,
    sources: dict[str, tuple[Path, str]] | None = None,
    *,
    prior_cwd: Path | str,
    allow_local: bool = False,
    staging_dir: Path | str | None = None,
) -> project_review.ProjectReviewOutcome:
    """Open a multi-repo review from a review-KIND gr commit and enter its lane.

    Refuses a non-review-kind commit (``read_project_review_commit`` rejects a
    wrong schema) BEFORE any materialization. When ``sources`` is None the source
    transport map is RESOLVED from each pin's recorded remote (the production
    shape: the review-kind commit is the only input, no hand-passed author-clone
    map); a caller may still pass an explicit map (author clones for a pre-push
    head not yet on the remote). Delegates materialization + lane enter to
    ``open_project_review`` (which refuses a missing pin before it clones
    anything). On success writes the project-tier receipt naming the gr commit,
    the per-repo base/head, the prior lane, and the prior cwd for exit-restore.
    """
    workspace = Path(workspace).resolve()
    # Control 1: a non-review-kind commit is refused here, before anything is made.
    rows = grip.read_project_review_commit(workspace, gr_commit)
    pins = [
        project_review.ProjectReviewPin(
            key=r["key"], repo=r["repo"], path=r["path"], base=r["base"], head=r["head"]
        )
        for r in rows
    ]
    spec = project_review.ProjectReviewSpec("gr2-project-review/v1", gr_commit, tuple(pins))

    if sources is None:
        staging = Path(staging_dir) if staging_dir is not None else (
            workspace / ".grip" / "open-gr-staging" / lane_name
        )
        sources = resolve_sources_from_pins(pins, staging, allow_local=allow_local)

    prior_lane = _current_lane_name(workspace, owner_unit)
    outcome = project_review.open_project_review(
        workspace=workspace, owner_unit=owner_unit, lane_name=lane_name,
        spec=spec, sources=sources, allow_local=allow_local,
    )
    if outcome.status != "opened" or outcome.review_root is None:
        # Refusal / partial propagates unchanged; no receipt, no enter to unwind.
        return outcome

    receipt = {
        "gr_commit": gr_commit,
        "owner_unit": owner_unit,
        "lane_name": lane_name,
        "prior_lane": prior_lane,
        "prior_cwd": str(Path(prior_cwd)),
        "review_root": str(outcome.review_root),
        "repos": [{"key": r["key"], "base": r["base"], "head": r["head"]} for r in rows],
    }
    open_gr_receipt_path(outcome.review_root).write_text(json.dumps(receipt, indent=2) + "\n")
    return outcome


@dataclasses.dataclass(frozen=True)
class OpenGrExit:
    restored_lane: str | None
    restored_cwd: str
    gr_commit: str


def exit_gr_review(
    workspace: Path, owner_unit: str, review_root: Path, *, actor: str
) -> OpenGrExit:
    """Exit a review opened by ``open_gr_enter``: restore the prior lane and cwd.

    Reads the project-tier receipt for the prior lane/cwd, then pops the review
    lane off the return stack (``exit_lane`` restores recent[0] as current). The
    restore is the whole point — skipping it leaves the agent stranded in the
    review lane.
    """
    import argparse

    workspace = Path(workspace).resolve()
    receipt_path = open_gr_receipt_path(review_root)
    if not receipt_path.exists():
        raise OpenGrReviewError(f"no open-gr receipt at {receipt_path}; not a review opened by open-gr")
    receipt = json.loads(receipt_path.read_text())

    lane_proto.exit_lane(argparse.Namespace(
        workspace_root=workspace, owner_unit=owner_unit, actor=actor,
        notify_channel=False, recall=False,
    ))
    restored_lane = _current_lane_name(workspace, owner_unit)
    return OpenGrExit(
        restored_lane=restored_lane,
        restored_cwd=receipt["prior_cwd"],
        gr_commit=receipt["gr_commit"],
    )
