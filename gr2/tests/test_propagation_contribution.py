"""Prototype 2: the contribution protocol on the Prototype 0 machine.

Everything here runs against throwaway repositories under ``tmp_path``. No real
workspace, remote, or authoring clone is touched. The synthetic topology is a
scratch PARENT and two SUBSPACES:

* one bare ``owner.git`` — the parent layer's CANONICAL remote for ``main``, the
  surface the children do not own and may only change by contributing
* two child clones, ``child-a`` and ``child-b``, each an independent authoring
  clone of that canonical (independent clones are the product)

A contribution is a state-machine operation with ``direction=up``: the machine observes the
child's branch, fetches it into the sink's mirror, plans against the owner's
branch as read NOW, and lands it by a fast-forward push guarded by
``--force-with-lease`` on the expected base — compare-and-swap enforced by the
receiving repository, not by this process. What the witnesses prove:

* W2a  a contribution walks observed -> fetched -> planned -> applied -> verified
       -> acknowledged; the owner's branch reports the child's revision; the
       receipt names exact revisions; the cleanliness gate is recorded NOT RUN
       (a bare remote has no worktree), never silently omitted
* W2b  the manufactured collision: after A lands, B's change (authored against
       the OLD base) is REFUSED at plan — not a fast-forward of the observed base
       — with the observed base in the receipt; the owner's refs and B's clone are
       byte-for-byte untouched
* W2c  the compare-and-swap race: B plans while the owner is at the old base, the
       sink dies, A lands, B resumes — and B is REFUSED at apply because the
       expected base moved; nothing of B's reaches the owner
* W2d  the lease closes the window the process-side check cannot see: the owner
       moves AFTER B's apply-step head check and BEFORE B's push; the receiving
       repository rejects the lease; B is REFUSED with the revision the owner
       holds; B's bytes never land
* W2e  replan is the AUTHOR's act: B rebases onto the owner's branch and
       re-contributes; the new revision is a fresh attempt and lands; the journal
       carries the refused attempt and the acknowledged one, both by name
* W2f  policy governs ``up`` exactly as it governs ``down``: a policy that does
       not allow ``up`` refuses at ``policy.direction`` before any verb
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest
from gr2.prototypes.propagation_state_machine import (
    Coordinate,
    Destination,
    DestinationKind,
    Direction,
    Operation,
    Policy,
    Propagator,
    SinkKilled,
    State,
)

_GIT_ENV = {
    "GIT_AUTHOR_NAME": "prototype",
    "GIT_AUTHOR_EMAIL": "prototype@example.invalid",
    "GIT_COMMITTER_NAME": "prototype",
    "GIT_COMMITTER_EMAIL": "prototype@example.invalid",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
}


def git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
        env={**os.environ, **_GIT_ENV},
    )
    return proc.stdout.strip()


def bare_refs(repo: Path) -> str:
    return git(repo, "for-each-ref", "--format=%(refname) %(objectname)")


def clone_snapshot(repo: Path) -> dict[str, str]:
    return {
        "refs": git(repo, "for-each-ref", "--format=%(refname) %(objectname)"),
        "head": git(repo, "rev-parse", "HEAD"),
        "porcelain": git(repo, "status", "--porcelain"),
        "canon": (repo / "canon.md").read_text(),
        "reflog": git(repo, "reflog", "show", "--format=%gs", "HEAD"),
    }


@dataclass
class Parent:
    """A scratch parent layer: its canonical remote plus two subspace clones."""

    owner: Path
    base: str
    root: Path

    def child(self, name: str) -> Path:
        path = self.root / name
        subprocess.run(
            ["git", "clone", "-q", str(self.owner), str(path)],
            check=True,
            capture_output=True,
            text=True,
            env={**os.environ, **_GIT_ENV},
        )
        return path

    def sink(self, name: str) -> Path:
        return self.root / f"sink-{name}"


def author(child: Path, text: str, *, path: str = "canon.md") -> str:
    (child / path).write_text(text)
    git(child, "add", path)
    git(child, "commit", "-q", "-m", f"{path}: {text.strip()[:40]}")
    return git(child, "rev-parse", "HEAD")


@pytest.fixture
def parent(tmp_path: Path) -> Parent:
    owner = tmp_path / "owner.git"
    subprocess.run(
        ["git", "init", "-q", "--bare", "--initial-branch=main", str(owner)],
        check=True,
        capture_output=True,
        text=True,
        env={**os.environ, **_GIT_ENV},
    )
    seed = tmp_path / "seed"
    subprocess.run(
        ["git", "clone", "-q", str(owner), str(seed)],
        check=True,
        capture_output=True,
        text=True,
        env={**os.environ, **_GIT_ENV},
    )
    git(seed, "switch", "-q", "-c", "main")
    (seed / "canon.md").write_text("canon v1\n")
    (seed / "other.md").write_text("other v1\n")
    git(seed, "add", "canon.md", "other.md")
    git(seed, "commit", "-q", "-m", "canon v1")
    git(seed, "push", "-q", "-u", "origin", "main")
    base = git(seed, "rev-parse", "HEAD")
    return Parent(owner=owner, base=base, root=tmp_path)


POLICY_UP = Policy(policy_hash="policy-prototype-2", allowed_directions=frozenset({Direction.UP}))
POLICY_DOWN_ONLY = Policy(
    policy_hash="policy-prototype-2-down-only", allowed_directions=frozenset({Direction.DOWN})
)


def contribution(child_id: str) -> Coordinate:
    return Coordinate(
        source=child_id,
        destination="owner-canonical",
        layer="layer-parent",
        direction=Direction.UP,
        operation=Operation.CONTRIBUTE,
        artifact_class="config",
    )


def canonical(parent: Parent) -> Destination:
    return Destination(
        destination_id="owner-canonical", path=parent.owner, kind=DestinationKind.CANONICAL
    )


def contributor(
    parent: Parent, child: Path, name: str, *, policy: Policy = POLICY_UP, **kw
) -> Propagator:
    """The sink that carries ONE child's contributions: its source is that child's clone."""
    return Propagator(
        source_remote=child, branch="main", state_dir=parent.sink(name), policy=policy, **kw
    )


def owner_main(parent: Parent) -> str:
    return git(parent.owner, "rev-parse", "--verify", "refs/heads/main")


# --------------------------------------------------------------------------- W2a


def test_a_contribution_lands_on_the_owner_by_lease_push_and_names_exact_revisions(
    parent: Parent,
) -> None:
    child_a = parent.child("child-a")
    new = author(child_a, "canon v2 (a)\n")

    receipt = contributor(parent, child_a, "a").run(contribution("child-a"), canonical(parent))

    assert receipt is not None
    assert receipt.state is State.ACKNOWLEDGED
    assert [t.state for t in receipt.transitions] == [
        State.OBSERVED,
        State.FETCHED,
        State.PLANNED,
        State.APPLIED,
        State.VERIFIED,
        State.ACKNOWLEDGED,
    ]
    # the owner's BRANCH reports the child's revision: read back from the owner, not the verb
    assert owner_main(parent) == new
    assert receipt.source_rev == new
    assert receipt.expected_base == parent.base
    assert receipt.after == new
    # the cleanliness gate is recorded NOT RUN for a bare destination, never omitted
    by_id = {g.gate_id: g for g in receipt.gate_results}
    assert by_id["destination.clean"].result == "not-run"
    assert by_id["destination.base-unmoved"].result == "pass"
    assert by_id["destination.fast-forward"].result == "pass"
    assert by_id["policy.direction"].result == "pass"
    verified = next(t for t in receipt.transitions if t.state is State.VERIFIED)
    assert verified.observation["postcondition_checked"] == (
        "branch-is-intended-after-and-tree-matches-digest"
    )
    applied = next(t for t in receipt.transitions if t.state is State.APPLIED)
    assert applied.observation["verb_ran_now"] is True


# --------------------------------------------------------------------------- W2b


def test_the_manufactured_collision_refuses_the_stale_contribution_and_touches_nothing(
    parent: Parent,
) -> None:
    child_a = parent.child("child-a")
    child_b = parent.child("child-b")
    a_new = author(child_a, "canon v2 (a)\n")
    b_new = author(child_b, "canon v2 (b)\n")  # same logical path, authored against the OLD base

    assert (
        contributor(parent, child_a, "a").run(contribution("child-a"), canonical(parent)).state
        is State.ACKNOWLEDGED
    )
    assert owner_main(parent) == a_new

    owner_before = bare_refs(parent.owner)
    b_before = clone_snapshot(child_b)

    receipt = contributor(parent, child_b, "b").run(contribution("child-b"), canonical(parent))

    assert receipt is not None
    assert receipt.state is State.REFUSED
    # refused at PLAN: the owner's branch is not an ancestor of B's revision
    assert [t.state for t in receipt.transitions] == [
        State.OBSERVED,
        State.FETCHED,
        State.PLANNED,
        State.REFUSED,
    ]
    refused = receipt.transitions[-1]
    assert "destination.fast-forward" in refused.observation["failed_gates"]
    assert refused.observation["observed_base"] == a_new
    assert receipt.source_rev == b_new
    # nothing merged, nothing forced, nothing written: owner refs and B's clone unchanged
    assert bare_refs(parent.owner) == owner_before
    assert clone_snapshot(child_b) == b_before
    assert owner_main(parent) == a_new


# --------------------------------------------------------------------------- W2c


def test_compare_and_swap_race_refuses_at_apply_when_the_base_moved_after_plan(
    parent: Parent,
) -> None:
    child_a = parent.child("child-a")
    child_b = parent.child("child-b")
    a_new = author(child_a, "canon v2 (a)\n")
    b_new = author(child_b, "other v2 (b)\n", path="other.md")  # DISJOINT paths, same base

    # B plans while the owner is still at the base, then the sink dies
    with pytest.raises(SinkKilled):
        contributor(parent, child_b, "b", kill_after=State.PLANNED).run(
            contribution("child-b"), canonical(parent)
        )
    # A lands in between
    assert (
        contributor(parent, child_a, "a").run(contribution("child-a"), canonical(parent)).state
        is State.ACKNOWLEDGED
    )
    assert owner_main(parent) == a_new

    # B resumes the SAME operation from planned: apply re-reads the base and refuses
    receipt = contributor(parent, child_b, "b").run(contribution("child-b"), canonical(parent))

    assert receipt is not None
    assert receipt.state is State.REFUSED
    refused = receipt.transitions[-1]
    assert str(refused.observation["refusal_reason"]).startswith("expected_base moved")
    assert refused.observation["observed_base"] == a_new
    assert receipt.expected_base == parent.base
    assert receipt.source_rev == b_new
    # the owner still holds A's revision and nothing of B's is reachable from it
    assert owner_main(parent) == a_new
    contains = subprocess.run(
        ["git", "-C", str(parent.owner), "merge-base", "--is-ancestor", b_new, "refs/heads/main"],
        capture_output=True,
        text=True,
        env={**os.environ, **_GIT_ENV},
    )
    assert contains.returncode != 0  # B's revision is NOT an ancestor of the owner's branch


# --------------------------------------------------------------------------- W2d


def test_the_lease_refuses_a_move_inside_the_window_after_the_head_check(parent: Parent) -> None:
    child_a = parent.child("child-a")
    child_b = parent.child("child-b")
    a_new = author(child_a, "canon v2 (a)\n")
    b_new = author(child_b, "other v2 (b)\n", path="other.md")

    def another_writer_lands() -> None:
        # between B's apply-step head check and B's push, A pushes straight to the owner
        git(child_a, "push", "-q", "origin", "main")
        assert owner_main(parent) == a_new

    receipt = contributor(parent, child_b, "b", before_apply_verb=another_writer_lands).run(
        contribution("child-b"), canonical(parent)
    )

    assert receipt is not None
    assert receipt.state is State.REFUSED
    refused = receipt.transitions[-1]
    assert str(refused.observation["refusal_reason"]).startswith("destination.lease-refused")
    assert refused.observation["observed_base"] == a_new
    # the plan was computed against the base, the apply verb was attempted, the lease held the line
    assert receipt.expected_base == parent.base
    assert [t.state for t in receipt.transitions] == [
        State.OBSERVED,
        State.FETCHED,
        State.PLANNED,
        State.REFUSED,
    ]
    assert owner_main(parent) == a_new
    contains = subprocess.run(
        ["git", "-C", str(parent.owner), "merge-base", "--is-ancestor", b_new, "refs/heads/main"],
        capture_output=True,
        text=True,
        env={**os.environ, **_GIT_ENV},
    )
    assert contains.returncode != 0


# --------------------------------------------------------------------------- W2e


def test_replan_is_the_authors_act_and_the_rebased_contribution_lands_as_a_fresh_attempt(
    parent: Parent,
) -> None:
    child_a = parent.child("child-a")
    child_b = parent.child("child-b")
    a_new = author(child_a, "canon v2 (a)\n")
    b_stale = author(child_b, "other v2 (b)\n", path="other.md")
    assert (
        contributor(parent, child_a, "a").run(contribution("child-a"), canonical(parent)).state
        is State.ACKNOWLEDGED
    )

    sink_b = contributor(parent, child_b, "b")
    first = sink_b.run(contribution("child-b"), canonical(parent))
    assert first is not None and first.state is State.REFUSED
    assert first.source_rev == b_stale

    # the AUTHOR replans: rebase B onto the owner's branch (the machine never did this)
    git(child_b, "fetch", "-q", "origin")
    git(child_b, "rebase", "-q", "origin/main")
    b_rebased = git(child_b, "rev-parse", "HEAD")
    assert b_rebased != b_stale
    assert git(child_b, "merge-base", "--is-ancestor", a_new, b_rebased) == ""

    second = sink_b.run(contribution("child-b"), canonical(parent))

    assert second is not None
    assert second.state is State.ACKNOWLEDGED
    assert second.source_rev == b_rebased
    assert second.expected_base == a_new
    assert owner_main(parent) == b_rebased
    # both attempts are in the journal by name: the refused one at the stale revision,
    # the acknowledged one at the rebased revision — a refusal describes a moment
    assert (
        sink_b.journal.find(contribution("child-b").key(), b_stale)[-1][-1].state is State.REFUSED
    )
    assert (
        sink_b.journal.find(contribution("child-b").key(), b_rebased)[-1][-1].state
        is State.ACKNOWLEDGED
    )
    # the owner's tree now carries BOTH changes, because the author's rebase composed them
    assert git(parent.owner, "show", "refs/heads/main:canon.md") == "canon v2 (a)"
    assert git(parent.owner, "show", "refs/heads/main:other.md") == "other v2 (b)"


# --------------------------------------------------------------------------- W2f


def test_policy_that_does_not_allow_up_refuses_before_any_verb(parent: Parent) -> None:
    child_a = parent.child("child-a")
    author(child_a, "canon v2 (a)\n")
    owner_before = bare_refs(parent.owner)

    receipt = contributor(parent, child_a, "a", policy=POLICY_DOWN_ONLY).run(
        contribution("child-a"), canonical(parent)
    )

    assert receipt is not None
    assert receipt.state is State.REFUSED
    refused = receipt.transitions[-1]
    assert "policy.direction" in refused.observation["failed_gates"]
    assert bare_refs(parent.owner) == owner_before
    assert owner_main(parent) == parent.base
