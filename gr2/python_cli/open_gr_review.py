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


def review_cache_root() -> Path:
    """The persistent per-host review-mirror cache root, SHARED with
    config/scripts/review-clone.sh so there is one bare mirror per repo on this
    host, never a second keyed differently. Honors the same
    ``SYNAPT_REVIEW_CACHE_ROOT`` override the script honors."""
    import os
    return Path(os.environ.get("SYNAPT_REVIEW_CACHE_ROOT") or (Path.home() / ".synapt-review-cache"))


def _mirror_basename(transport_location: str) -> str:
    """The repo name the shared cache keys a mirror under: the URL/path basename
    minus a trailing ``.git`` (e.g. …/recall.git -> recall). This matches
    review-clone.sh's ``<repo>.git`` for every repo whose review-clone name is its
    URL basename (all the code repos); ``site`` is the one review-clone name that
    is NOT its URL basename, and is out of scope for multi-repo code review."""
    name = transport_location.rstrip("/").rsplit("/", 1)[-1]
    return name[:-4] if name.endswith(".git") else name


def resolve_sources_from_pins(
    pins: list[project_review.ProjectReviewPin] | tuple[project_review.ProjectReviewPin, ...],
    staging_dir: Path | str | None = None,
    *,
    allow_local: bool = False,
    cache_root: Path | str | None = None,
) -> tuple[dict[str, tuple[Path, str]], dict[str, dict[str, str]]]:
    """Resolve each source from its RECORDED REMOTE through a PERSISTENT bare mirror.

    For each pin, ensure a bare mirror at the SHARED per-host cache
    (``<cache_root>/<repo>.git``, cache_root defaulting to review-clone.sh's
    ``~/.synapt-review-cache``) via ``ensure_repo_cache`` -- seed with
    ``git clone --mirror`` if absent, else ``remote update --prune`` (fetch fresh; a
    stale mirror must never read as current) -- then confirm the pin's base AND head
    are commits IN the mirror. The mirror IS the source handed to the review open:
    the review lane then clones from it blobless (``--filter=blob:none``) and sparse
    (see ``review_ephemeral.materialize_review_ephemeral``), so the lane fetches only
    the blobs and checks out only the paths a review reads instead of copying a full
    clone per review (the measured 978M harm). The mirror's objects are NOT borrowed
    via ``--reference``: the review lane is a self-contained clone, disposable on exit.

    The returned ``review_branch`` is the head sha itself (a sha resolves to itself
    under ``rev-parse --verify <sha>^{commit}``). A mirror that does not carry the
    pinned head is refused HERE, before any review lane opens. Returns
    ``(srcmap, mirror_meta)`` where ``mirror_meta[key]`` names the mirror path and
    its fetched tip so a reviewer can tell a stale mirror from a fresh one.

    ``staging_dir`` is accepted for signature compatibility and no longer used:
    the mirror replaces the per-review staging clone.
    """
    root = Path(cache_root) if cache_root is not None else review_cache_root()
    srcmap: dict[str, tuple[Path, str]] = {}
    mirror_meta: dict[str, dict[str, str]] = {}
    for pin in pins:
        location = _pin_transport_location(pin.repo)
        mirror = root / f"{_mirror_basename(location)}.git"
        try:
            review.gitops.ensure_repo_cache(location, mirror)
        except SystemExit as exc:
            raise OpenGrReviewError(
                f"cannot ensure review mirror for {pin.key!r} at {mirror} from {location!r}: {exc}"
            ) from exc
        # Serve blobless (--filter=blob:none) clones from the mirror, same as
        # review-clone.sh sets on its cache.
        git(mirror, "config", "uploadpack.allowFilter", "true")
        for label, sha in (("base", pin.base), ("head", pin.head)):
            if git(mirror, "cat-file", "-e", f"{sha}^{{commit}}").returncode != 0:
                raise OpenGrReviewError(
                    f"review mirror for {pin.key!r} does not carry {label} {sha}: the pinned "
                    f"head must be published to the pinned remote for a remote-resolved open-gr"
                )
        tip = git(mirror, "rev-parse", "HEAD")
        srcmap[pin.key] = (mirror, pin.head)
        mirror_meta[pin.key] = {"mirror": str(mirror), "fetched_tip": tip.stdout.strip()}
    return srcmap, mirror_meta


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

    # When sources are RESOLVED from the recorded remote, each source is the
    # persistent bare mirror and each review lane is a blobless+sparse
    # review-EPHEMERAL clone from it (never the work-lane clone seam). An explicit
    # sources map (pre-push author clones) has no mirror and clones normally.
    ephemeral = False
    mirror_meta: dict[str, dict[str, str]] = {}
    if sources is None:
        sources, mirror_meta = resolve_sources_from_pins(
            pins, staging_dir, allow_local=allow_local
        )
        ephemeral = True

    prior_lane = _current_lane_name(workspace, owner_unit)
    outcome = project_review.open_project_review(
        workspace=workspace, owner_unit=owner_unit, lane_name=lane_name,
        spec=spec, sources=sources, allow_local=allow_local, ephemeral=ephemeral,
    )
    if outcome.status != "opened" or outcome.review_root is None:
        # Refusal / partial propagates unchanged; no receipt, no enter to unwind.
        return outcome

    receipt = {
        "gr_commit": gr_commit,
        "owner_unit": owner_unit,
        "lane_name": lane_name,
        "lane_kind": "review-ephemeral" if ephemeral else "materialized",
        "prior_lane": prior_lane,
        "prior_cwd": str(Path(prior_cwd)),
        "review_root": str(outcome.review_root),
        "repos": [
            {
                "key": r["key"], "base": r["base"], "head": r["head"],
                # A reviewer can tell a stale mirror from a fresh one from these.
                **({"mirror": mirror_meta[r["key"]]["mirror"],
                    "fetched_tip": mirror_meta[r["key"]]["fetched_tip"]}
                   if r["key"] in mirror_meta else {}),
            }
            for r in rows
        ],
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
    # A review-ephemeral review is READ-ONLY and disposable: rm -rf is the ONLY
    # cleanup (no prune verb that could ever touch a work lane). The mirror
    # persists; only the disposable review clones are removed.
    if receipt.get("lane_kind") == "review-ephemeral":
        import shutil
        shutil.rmtree(review_root, ignore_errors=True)
    return OpenGrExit(
        restored_lane=restored_lane,
        restored_cwd=receipt["prior_cwd"],
        gr_commit=receipt["gr_commit"],
    )
