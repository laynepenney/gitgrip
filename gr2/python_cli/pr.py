"""gr2 PR group orchestration.

Implements multi-repo PR lifecycle from PR-LIFECYCLE.md:
- create_pr_group: Create linked PRs across repos with pr_group_id
- merge_pr_group: Merge all PRs in a group (stops on first failure)
- check_pr_group_status: Poll status/checks and emit change events
- record_pr_review: Record an externally-submitted review event

The PlatformAdapter is group-unaware. This module assigns pr_group_id,
persists group metadata, and emits events per HOOK-EVENT-CONTRACT.md
section 3.2 (PR Lifecycle).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from .events import EventType, emit
from .platform import AdapterError, CreatePRRequest, MergeMethod, PlatformAdapter

__all__ = [
    "MergeMethod",
    "UnpermittedMergeMethodError",
    "resolve_merge_method",
    "PRMergeError",
    "create_pr_group",
    "merge_pr_group",
    "check_pr_group_status",
    "record_pr_review",
]


class UnpermittedMergeMethodError(RuntimeError):
    """The requested method is not permitted, and no other method was substituted.

    Deliberately NOT a subclass of the parse error. A name we cannot read and a name we
    can read but may not use are different facts, and a caller that wants to distinguish
    them should not have to inspect a message to do it.
    """

    def __init__(self, requested: MergeMethod, permitted: list[str]) -> None:
        self.requested = requested
        self.permitted = list(permitted)
        super().__init__(
            f"merge method {requested.value!r} is not permitted here "
            f"(permitted: {', '.join(self.permitted) or 'none'}). "
            f"Refusing rather than substituting: a merge that silently uses a different "
            f"strategy than the one requested reports success identically, and the only "
            f"way to discover it is counting parents afterwards."
        )


def _parse_method(name: str, *, source: str) -> MergeMethod:
    try:
        return MergeMethod(name)
    except ValueError:
        raise ValueError(
            f"unrecognised merge method {name!r} from {source} "
            f"(expected one of: {', '.join(m.value for m in MergeMethod)}). "
            f"Not falling back to a default: you asked for something, and quietly doing "
            f"something else is the defect this guard exists to prevent."
        ) from None


def resolve_merge_method(
    explicit: str | None = None,
    configured: str | None = None,
    permitted: list[str] | None = None,
) -> MergeMethod:
    """Resolve the merge strategy. The host is asked *whether*, never *which*.

    Precedence: explicit `--method`, then the workspace setting, then a merge commit.

    `permitted` is what the host allows, when we happen to know it. Passing `None` means
    **we did not ask** -- which must not read as "anything goes". No refusal is claimed in
    that case, and nothing asserts the method was permitted; unverifiable stays
    distinguishable from verified.
    """
    if explicit is not None:
        chosen = _parse_method(explicit, source="--method")
    elif configured is not None:
        chosen = _parse_method(configured, source="workspace setting")
    else:
        chosen = MergeMethod.MERGE

    if permitted is not None and chosen.value not in permitted:
        raise UnpermittedMergeMethodError(chosen, permitted)

    return chosen


class PRMergeError(RuntimeError):
    """Raised when a PR merge fails, carrying the merges that already succeeded.

    `completed` is REQUIRED and keyword-only, with no default, because this is the
    reliable half of G9 (grip#842). Merging is irreversible: by the time one repo fails,
    earlier repos are merged on the host and no amount of unwinding changes that. A caller
    that cannot learn which ones will re-attempt them.

        Irreversible work that is not recorded is worse than work not done,
        because the next actor plans against a state that is false.

    An optional field would be omitted at exactly one call site within a year and the
    guarantee would quietly become a convention. An empty list is a claim -- "nothing had
    merged" -- and must be stated, not defaulted; "nothing merged" and "nobody recorded
    what merged" are different facts and a default would make them identical.

    This is the layer a retry reads. The event log is the other layer and is best-effort:
    `emit` RAISES `EventEmitError` as of grip#843 (it previously swallowed everything);
    either way correctness must not rest on it -- fail-open lost the record silently, and
    fail-closed turns a logging failure into an operation failure. The two
    fail by different routes, which is the only thing that makes them depth rather than
    the same chance twice.
    """

    def __init__(
        self,
        repo: str,
        pr_number: int,
        reason: str,
        *,
        completed: list[dict],
    ) -> None:
        self.repo = repo
        self.pr_number = pr_number
        self.reason = reason
        self.completed = list(completed)
        already = ", ".join(str(c.get("repo")) for c in self.completed)
        super().__init__(
            f"merge failed for {repo}#{pr_number}: {reason}"
            + (
                f" (ALREADY MERGED, do not retry: {already})"
                if self.completed
                else " (nothing had merged yet)"
            )
        )


def _pr_groups_dir(workspace_root: Path) -> Path:
    return workspace_root / ".grip" / "pr_groups"


def _generate_group_id() -> str:
    return "pg_" + os.urandom(4).hex()


def _load_group(workspace_root: Path, pr_group_id: str) -> dict:
    path = _pr_groups_dir(workspace_root) / f"{pr_group_id}.json"
    return json.loads(path.read_text())


def _save_group(workspace_root: Path, group: dict) -> Path:
    d = _pr_groups_dir(workspace_root)
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{group['pr_group_id']}.json"
    path.write_text(json.dumps(group, indent=2))
    return path


def create_pr_group(
    workspace_root: Path,
    owner_unit: str,
    lane_name: str,
    title: str,
    base_branch: str,
    head_branch: str,
    repos: list[str],
    adapter: PlatformAdapter,
    actor: str,
    *,
    body: str = "",
    draft: bool = False,
) -> dict:
    """Create linked PRs across repos and emit pr.created."""
    pr_group_id = _generate_group_id()
    prs: list[dict] = []

    for repo in repos:
        request = CreatePRRequest(
            repo=repo,
            title=title,
            body=body,
            head_branch=head_branch,
            base_branch=base_branch,
            draft=draft,
        )
        ref = adapter.create_pr(request)
        prs.append({"repo": repo, "pr_number": ref.number, "url": ref.url})

    group = {
        "pr_group_id": pr_group_id,
        "owner_unit": owner_unit,
        "lane_name": lane_name,
        "title": title,
        "base_branch": base_branch,
        "head_branch": head_branch,
        "platform": getattr(adapter, "name", "github"),
        "prs": prs,
        "status": {repo: "OPEN" for repo in repos},
    }
    path = _save_group(workspace_root, group)

    emit(
        event_type=EventType.PR_CREATED,
        workspace_root=workspace_root,
        actor=actor,
        owner_unit=owner_unit,
        payload={"pr_group_id": pr_group_id, "lane_name": lane_name, "repos": prs},
    )

    group["state_path"] = str(path)
    return group


def merge_pr_group(
    workspace_root: Path,
    pr_group_id: str,
    adapter: PlatformAdapter,
    actor: str,
    *,
    method: MergeMethod,
) -> dict:
    """Merge all PRs in a group. Stops on first failure.

    `method` is required and keyword-only. Resolving a strategy correctly and then not
    threading it to the call is the same outcome as never resolving one -- a decided
    method that never reaches `gh` is indistinguishable from an undecided one, and the
    unit tests for the resolver stay green either way.
    """
    group = _load_group(workspace_root, pr_group_id)
    merged: list[dict] = []

    for pr_info in group["prs"]:
        repo = pr_info["repo"]
        number = pr_info["pr_number"]
        try:
            receipt = adapter.merge_pr(repo, number, method=method)
        except AdapterError as exc:
            # Best-effort durable layer. Wrapped so a failure HERE cannot replace the
            # PRMergeError below with the event subsystem's own exception -- if a broken
            # event layer can take the in-process layer down with it, they were never two
            # layers. This was written while `emit` still swallowed everything; grip#843
            # made it RAISE, so the wrap is now load-bearing rather than defensive. The
            # broader class -- emits sitting after irreversible work -- is grip#844.
            try:
                emit(
                    event_type=EventType.PR_MERGE_FAILED,
                    workspace_root=workspace_root,
                    actor=actor,
                    owner_unit=group.get("owner_unit", actor),
                    payload={
                        "pr_group_id": pr_group_id,
                        "repo": repo,
                        "pr_number": number,
                        "reason": str(exc),
                        # The irreversible work that already happened. Recorded on the
                        # FAILURE event because there may never be a success event.
                        "completed": merged,
                    },
                )
            except Exception as emit_exc:  # noqa: BLE001 - deliberately broad
                print(
                    f"gr2: could not record partial merge ({emit_exc}); "
                    f"the completed list is still on the raised PRMergeError",
                    file=sys.stderr,
                )
            raise PRMergeError(repo, number, str(exc), completed=merged) from exc

        # Carried back from the ADAPTER, never rebuilt from `pr_info`. Rebuilding from the
        # group file produces the same repo names in the same order -- the loop visits
        # repos in group order -- so the two are indistinguishable by inspection while one
        # is evidence that a merge happened and the other is a restatement of what we
        # intended. The second is exactly what a loop that never contacted the host would
        # also produce.
        #
        # `PRRef` is a thin receipt today and carries no commit id (grip#842 item 3 makes
        # it real). This shape is the seam: when the richer receipt lands it swaps in here
        # without the meaning of the record changing.
        merged.append(
            {"repo": receipt.repo, "pr_number": receipt.number, "url": receipt.url}
        )

    emit(
        event_type=EventType.PR_MERGED,
        workspace_root=workspace_root,
        actor=actor,
        owner_unit=group.get("owner_unit", actor),
        payload={"pr_group_id": pr_group_id, "repos": merged},
    )

    # Hand the caller what ACTUALLY merged. Without this the layer above has
    # nothing to consume and re-derives completion from the group's declared
    # `prs` -- which names repos the loop may never have reached. G9's list is
    # only worth carrying if the next consumer can read it.
    group["completed"] = merged
    return group


def check_pr_group_status(
    workspace_root: Path,
    pr_group_id: str,
    adapter: PlatformAdapter,
    actor: str,
) -> dict:
    """Poll PR status/checks for all repos in a group. Emit change events."""
    group = _load_group(workspace_root, pr_group_id)
    cached_status = group.get("status", {})

    for pr_info in group["prs"]:
        repo = pr_info["repo"]
        number = pr_info["pr_number"]
        status = adapter.pr_status(repo, number)
        old_state = cached_status.get(repo, "OPEN")

        if status.state != old_state:
            emit(
                event_type=EventType.PR_STATUS_CHANGED,
                workspace_root=workspace_root,
                actor=actor,
                owner_unit=group.get("owner_unit", actor),
                payload={
                    "pr_group_id": pr_group_id,
                    "repo": repo,
                    "pr_number": number,
                    "old_status": old_state,
                    "new_status": status.state,
                },
            )
            cached_status[repo] = status.state

        if status.checks:
            completed = [c for c in status.checks if c.status == "COMPLETED"]
            if completed and len(completed) == len(status.checks):
                failed = [c.name for c in completed if c.conclusion != "SUCCESS"]
                if failed:
                    emit(
                        event_type=EventType.PR_CHECKS_FAILED,
                        workspace_root=workspace_root,
                        actor=actor,
                        owner_unit=group.get("owner_unit", actor),
                        payload={
                            "pr_group_id": pr_group_id,
                            "repo": repo,
                            "pr_number": number,
                            "failed_checks": failed,
                        },
                    )
                else:
                    emit(
                        event_type=EventType.PR_CHECKS_PASSED,
                        workspace_root=workspace_root,
                        actor=actor,
                        owner_unit=group.get("owner_unit", actor),
                        payload={
                            "pr_group_id": pr_group_id,
                            "repo": repo,
                            "pr_number": number,
                            "passed_checks": [c.name for c in completed],
                        },
                    )

    group["status"] = cached_status
    _save_group(workspace_root, group)
    return group


def record_pr_review(
    workspace_root: Path,
    pr_group_id: str,
    repo: str,
    pr_number: int,
    reviewer: str,
    state: str,
    actor: str,
) -> None:
    """Record an externally-submitted PR review and emit pr.review_submitted."""
    emit(
        event_type=EventType.PR_REVIEW_SUBMITTED,
        workspace_root=workspace_root,
        actor=actor,
        owner_unit=actor,
        payload={
            "pr_group_id": pr_group_id,
            "repo": repo,
            "pr_number": pr_number,
            "reviewer": reviewer,
            "state": state,
        },
    )
