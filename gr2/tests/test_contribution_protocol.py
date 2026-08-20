"""Prototype 2, the protocol around the machine: ownership, sets, retirement, appends.

Everything runs against throwaway repositories and files under ``tmp_path``. The
topology is the W2 one (a scratch parent with a bare canonical remote and child
clones) plus, where a SET needs them, further bare owners so that one set spans
several destinations. What the witnesses prove:

* W1  ownership is a RECORDED fact: every resolved entry carries ``declared_by``
      and ``overridden_by``; ``owner`` is the override or the declaration; a path
      classifies to its longest declared prefix; a path under no entry is refused;
      two layers declaring the same entry without ``override`` is a NAMED
      collision at resolution, never a silent precedence
* W4  a contribution SET prepares EVERY member through its gates before any verb
      runs, then lands in declared order; a refusal at prepare lands nothing; a
      refusal MID-SET stops the set and the set receipt names the landed, the
      refusing, and the not-attempted members; nothing is rolled back
* W5  a subspace REFUSES to retire while any of its contributions is open; the
      refusal lists operation ids; a refused contribution stays open until the
      author abandons it explicitly, and the abandon is a note in the
      contribution's own journal
* W6  a declared append-only surface: two writers both land, in arrival order,
      with no expected base to refuse on; earlier records are never rewritten;
      a second handle on the same file sees the first handle's records
"""

from __future__ import annotations

import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from gr2.prototypes.contribution_protocol import (
    ABANDONED_NOTE,
    AppendSurface,
    ContributionSet,
    Declaration,
    ResolutionCollision,
    ResolvedManifest,
    RetireRefused,
    SetMember,
    Subspace,
    WriteMode,
    state_latencies,
)
from gr2.prototypes.propagation_state_machine import (
    Coordinate,
    Destination,
    DestinationKind,
    Direction,
    Operation,
    State,
)
from gr2.tests.test_propagation_contribution import (
    _GIT_ENV,
    Parent,
    author,
    canonical,
    contribution,
    contributor,
    git,
    owner_main,
)

# --------------------------------------------------------------------------- helpers


def make_owner(root: Path, name: str) -> Parent:
    """Another bare canonical with the same seed shape, so one set can span owners."""
    owner = root / f"{name}.git"
    subprocess.run(
        ["git", "init", "-q", "--bare", "--initial-branch=main", str(owner)],
        check=True,
        capture_output=True,
        text=True,
        env={**os.environ, **_GIT_ENV},
    )
    seed = root / f"seed-{name}"
    subprocess.run(
        ["git", "clone", "-q", str(owner), str(seed)],
        check=True,
        capture_output=True,
        text=True,
        env={**os.environ, **_GIT_ENV},
    )
    git(seed, "switch", "-q", "-c", "main")
    (seed / "canon.md").write_text(f"{name} canon v1\n")
    (seed / "other.md").write_text(f"{name} other v1\n")
    git(seed, "add", "canon.md", "other.md")
    git(seed, "commit", "-q", "-m", f"{name} canon v1")
    git(seed, "push", "-q", "-u", "origin", "main")
    return Parent(owner=owner, base=git(seed, "rev-parse", "HEAD"), root=root)


@pytest.fixture
def parent(tmp_path: Path) -> Parent:
    """The W2 parent shape, built by the same helper the extra owners use."""
    return make_owner(tmp_path, "owner")


def coordinate(child_id: str, destination_id: str) -> Coordinate:
    return Coordinate(
        source=child_id,
        destination=destination_id,
        layer="layer-parent",
        direction=Direction.UP,
        operation=Operation.CONTRIBUTE,
        artifact_class="config",
    )


def member(owner: Parent, child: Path, member_id: str) -> SetMember:
    """One set member: its own sink carrying ``child``'s branch to ``owner``'s canonical."""
    destination = Destination(
        destination_id=f"canonical-{member_id}", path=owner.owner, kind=DestinationKind.CANONICAL
    )
    return SetMember(
        member_id=member_id,
        coordinate=coordinate(f"child-{member_id}", destination.destination_id),
        destination=destination,
        propagator=contributor(owner, child, member_id),
    )


# --------------------------------------------------------------------------- W1


def _declarations() -> list[Declaration]:
    # ancestors first; the SHORTER path is declared before the longer one nested under it,
    # so a first-match classifier and a longest-prefix classifier give different answers
    return [
        Declaration(layer="org", name="canon", path="config/canon.md"),
        Declaration(layer="org", name="notes", path="team"),
        Declaration(layer="team", name="ledger", path="team/ledger"),
        Declaration(layer="team", name="canon", path="config/canon.md", overrides=True),
    ]


def test_w1_ownership_is_recorded_provenance_and_owner_is_override_or_declaration() -> None:
    as_agent = ResolvedManifest.resolve("agent", _declarations())

    canon = as_agent.entry("canon")
    assert canon.declared_by == "org"
    assert canon.overridden_by == "team"
    assert canon.owner == "team"  # the override governs; the declaration is still recorded
    assert canon.write_mode is WriteMode.CONTRIBUTE
    notes = as_agent.entry("notes")
    assert (notes.declared_by, notes.overridden_by, notes.owner) == ("org", None, "org")
    assert as_agent.owner("ledger") == "team"

    # the SAME declarations resolved AS the team: what the team owns is authored, not contributed
    as_team = ResolvedManifest.resolve("team", _declarations())
    assert as_team.entry("canon").write_mode is WriteMode.OWN
    assert as_team.entry("ledger").write_mode is WriteMode.OWN
    assert as_team.entry("notes").write_mode is WriteMode.CONTRIBUTE

    # append-only is DECLARED by name, never inferred
    with_append = ResolvedManifest.resolve("agent", _declarations(), appends=["ledger"])
    assert with_append.entry("ledger").write_mode is WriteMode.APPEND
    assert as_agent.entry("ledger").write_mode is WriteMode.CONTRIBUTE


def test_w1_classify_picks_the_longest_declared_prefix_and_refuses_undeclared_paths() -> None:
    manifest = ResolvedManifest.resolve("agent", _declarations())

    canon = manifest.classify("config/canon.md")
    assert canon.mode is WriteMode.CONTRIBUTE
    assert canon.owner == "team"
    assert canon.entry is not None and canon.entry.name == "canon"

    nested = manifest.classify("team/ledger/2026.jsonl")  # under BOTH team/ and team/ledger
    assert nested.entry is not None and nested.entry.name == "ledger"
    assert nested.owner == "team"
    sibling = manifest.classify("team/readme.md")
    assert sibling.entry is not None and sibling.entry.name == "notes"
    assert sibling.owner == "org"

    # a path that merely shares a prefix STRING is not under the entry
    assert manifest.classify("teamwork.md").entry is None
    unknown = manifest.classify("elsewhere/file.md")
    assert unknown.mode is WriteMode.READ
    assert unknown.owner is None
    assert "under no declared entry" in unknown.reason


def test_w1_two_declarations_without_override_are_a_named_collision_not_precedence() -> None:
    colliding = [
        Declaration(layer="org", name="canon", path="config/canon.md"),
        Declaration(layer="team", name="canon", path="team/canon.md"),
    ]
    with pytest.raises(ResolutionCollision) as refused:
        ResolvedManifest.resolve("agent", colliding)
    message = str(refused.value)
    # the refusal NAMES both layers and both paths: a reader can act on it
    for fragment in ("'org'", "'team'", "config/canon.md", "team/canon.md", "without override"):
        assert fragment in message

    # positive control: the same pair WITH an override resolves, provenance intact
    resolved = ResolvedManifest.resolve(
        "agent",
        [
            colliding[0],
            Declaration(layer="team", name="canon", path="team/canon.md", overrides=True),
        ],
    )
    entry = resolved.entry("canon")
    assert (entry.declared_by, entry.overridden_by, entry.path) == ("org", "team", "team/canon.md")


# --------------------------------------------------------------------------- W4


def test_w4_a_set_prepares_every_member_before_any_verb_then_lands_in_declared_order(
    parent: Parent, tmp_path: Path
) -> None:
    owner2 = make_owner(tmp_path, "owner2")
    a1 = parent.child("a1")
    a2 = owner2.child("a2")
    new1 = author(a1, "canon v2 (set m1)\n")
    new2 = author(a2, "owner2 canon v2 (set m2)\n")
    contribution_set = ContributionSet(
        "set-1", [member(parent, a1, "m1"), member(owner2, a2, "m2")]
    )

    prepared = contribution_set.prepare()

    assert prepared.phase == "prepared"
    assert [o.state for o in prepared.outcomes] == [str(State.PLANNED), str(State.PLANNED)]
    # prepared, NOT landed: both owners still at their bases
    assert owner_main(parent) == parent.base
    assert owner_main(owner2) == owner2.base
    for outcome in prepared.outcomes:
        assert outcome.receipt is not None
        assert [t.state for t in outcome.receipt.transitions] == [
            State.OBSERVED,
            State.FETCHED,
            State.PLANNED,
        ]

    landed_order: list[str] = []
    landed = contribution_set.land(on_member_landed=landed_order.append)

    assert landed.phase == "landed"
    assert landed.landed == ("m1", "m2")
    assert landed_order == ["m1", "m2"]  # declared order, not arrival order
    assert landed.refused == () and landed.not_attempted == ()
    assert owner_main(parent) == new1
    assert owner_main(owner2) == new2
    # each member's receipt is the RESUMED attempt: one journaled attempt, planned then applied
    for outcome in landed.outcomes:
        assert outcome.receipt is not None and outcome.receipt.attempt == 1
        assert outcome.receipt.state is State.ACKNOWLEDGED
    as_dict = landed.as_dict()
    assert as_dict["order"] == ["m1", "m2"] and as_dict["landed"] == ["m1", "m2"]


def test_w4_a_refusal_at_prepare_lands_nothing_even_for_the_members_that_were_fine(
    parent: Parent, tmp_path: Path
) -> None:
    owner2 = make_owner(tmp_path, "owner2")
    a1 = parent.child("a1")
    a2 = owner2.child("a2")
    author(a1, "canon v2 (stale m1)\n")
    new2 = author(a2, "owner2 canon v2 (fine m2)\n")
    # an interloper lands on owner 1 first, so m1 is stale against the owner's CURRENT base
    interloper = parent.child("interloper")
    interloper_rev = author(interloper, "canon v2 (interloper)\n")
    assert (
        contributor(parent, interloper, "x")
        .run(contribution("interloper"), canonical(parent))
        .state
        is State.ACKNOWLEDGED
    )  # type: ignore[union-attr]

    contribution_set = ContributionSet(
        "set-2", [member(parent, a1, "m1"), member(owner2, a2, "m2")]
    )
    prepared = contribution_set.prepare()

    assert prepared.phase == "refused-at-prepare"
    assert prepared.refused == ("m1",)
    m1, m2 = prepared.outcomes
    assert m1.state == str(State.REFUSED) and m1.receipt is not None
    assert "destination.fast-forward" in [
        g.gate_id for g in m1.receipt.gate_results if g.result == "fail"
    ]
    assert m1.receipt.observed_base == interloper_rev
    assert m2.state == str(State.PLANNED)  # m2 was fine, and it did NOT land
    assert owner_main(owner2) == owner2.base
    assert owner_main(parent) == interloper_rev
    assert new2 != owner2.base


def test_w4_a_mid_set_refusal_stops_the_set_and_reports_landed_refused_not_attempted(
    parent: Parent, tmp_path: Path
) -> None:
    owner2 = make_owner(tmp_path, "owner2")
    owner3 = make_owner(tmp_path, "owner3")
    a1, a2, a3 = parent.child("a1"), owner2.child("a2"), owner3.child("a3")
    new1 = author(a1, "canon v2 (m1)\n")
    author(a2, "owner2 canon v2 (m2)\n")
    new3 = author(a3, "owner3 canon v2 (m3)\n")
    contribution_set = ContributionSet(
        "set-3",
        [member(parent, a1, "m1"), member(owner2, a2, "m2"), member(owner3, a3, "m3")],
    )
    assert contribution_set.prepare().phase == "prepared"

    # between prepare and land, owner 2 moves: the compare-and-swap at apply will refuse m2
    interloper = owner2.child("interloper2")
    moved_to = author(interloper, "owner2 canon v2 (interloper)\n")
    assert (
        contributor(owner2, interloper, "x2")
        .run(
            coordinate("interloper2", "canonical-x2"),
            Destination(
                destination_id="canonical-x2", path=owner2.owner, kind=DestinationKind.CANONICAL
            ),
        )
        .state
        is State.ACKNOWLEDGED
    )  # type: ignore[union-attr]

    landed = contribution_set.land()

    assert landed.phase == "stopped"
    assert landed.landed == ("m1",)
    assert landed.refused == ("m2",)
    assert landed.not_attempted == ("m3",)
    m1, m2, m3 = landed.outcomes
    assert m2.receipt is not None and m2.receipt.state is State.REFUSED
    assert "expected_base moved" in (m2.receipt.refusal_reason or "")
    assert m2.receipt.observed_base == moved_to
    assert m3.receipt is None
    # nothing rolled back: m1 stays landed; m3 never reached its owner
    assert owner_main(parent) == new1
    assert owner_main(owner2) == moved_to
    assert owner_main(owner3) == owner3.base
    assert new3 != owner3.base


def test_w4_a_set_refuses_to_exist_with_no_members_or_duplicate_member_ids(
    parent: Parent,
) -> None:
    with pytest.raises(ValueError):
        ContributionSet("empty", [])
    a1 = parent.child("a1")
    with pytest.raises(ValueError):
        ContributionSet("dup", [member(parent, a1, "m1"), member(parent, a1, "m1")])


# --------------------------------------------------------------------------- W5


def test_w5_retire_refuses_while_a_contribution_is_open_and_names_its_operation_id(
    parent: Parent,
) -> None:
    child_a = parent.child("child-a")
    author(child_a, "canon v2 (a)\n")
    sink = contributor(parent, child_a, "a")
    coord = contribution("child-a")
    prepared = sink.run(coord, canonical(parent), stop_after=State.PLANNED)
    assert prepared is not None and prepared.state is State.PLANNED
    subspace = Subspace("child-a", [(coord, sink)])

    with pytest.raises(RetireRefused) as refused:
        subspace.retire()
    assert subspace.retired is False
    [open_] = refused.value.open_contributions
    assert open_.coordinate_key == coord.key()
    assert open_.source_rev == prepared.source_rev
    assert open_.last_state == str(State.PLANNED)
    assert open_.operation_id == prepared.operation_id is not None
    assert prepared.operation_id in str(refused.value) or open_.source_rev[:12] in str(
        refused.value
    )

    # landing the contribution closes it; retire now succeeds
    landed = sink.run(coord, canonical(parent))
    assert landed is not None and landed.state is State.ACKNOWLEDGED
    assert subspace.open_contributions() == []
    subspace.retire()
    assert subspace.retired is True


def test_w5_a_refused_contribution_stays_open_until_abandoned_by_an_explicit_note(
    parent: Parent,
) -> None:
    child_a = parent.child("child-a")
    child_b = parent.child("child-b")
    author(child_a, "canon v2 (a)\n")
    stale = author(child_b, "canon v2 (b)\n")
    assert (
        contributor(parent, child_a, "a").run(contribution("child-a"), canonical(parent)).state
        is State.ACKNOWLEDGED
    )  # type: ignore[union-attr]
    sink_b = contributor(parent, child_b, "b")
    coord_b = contribution("child-b")
    refused = sink_b.run(coord_b, canonical(parent))
    assert refused is not None and refused.state is State.REFUSED
    subspace = Subspace("child-b", [(coord_b, sink_b)])

    # refused is NOT terminal: the author has not said what becomes of the change
    with pytest.raises(RetireRefused) as blocked:
        subspace.retire()
    [open_] = blocked.value.open_contributions
    assert (open_.source_rev, open_.last_state) == (stale, str(State.REFUSED))

    subspace.abandon(coord_b, stale, reason="superseded by child-a's change")
    assert sink_b.journal.notes(coord_b.key(), stale, ABANDONED_NOTE) == 1
    assert subspace.open_contributions() == []
    subspace.retire()
    assert subspace.retired is True

    # abandoning something the subspace does not hold is an error, not a silent no-op
    with pytest.raises(KeyError):
        subspace.abandon(contribution("child-z"), stale, reason="nope")


# --------------------------------------------------------------------------- W6


def test_w6_two_writers_both_land_in_arrival_order_and_earlier_records_are_never_rewritten(
    tmp_path: Path,
) -> None:
    path = tmp_path / "ledger" / "events.jsonl"
    first_handle = AppendSurface(path)
    second_handle = AppendSurface(path)  # a second writer on the SAME file, no shared state

    r1 = first_handle.append("a", {"n": 1})
    r2 = second_handle.append("b", {"n": 1})
    r3 = first_handle.append("a", {"n": 2})
    assert [r.seq for r in (r1, r2, r3)] == [1, 2, 3]
    assert [(r.writer, r.payload["n"]) for r in first_handle.records()] == [
        ("a", 1),
        ("b", 1),
        ("a", 2),
    ]
    # the second handle reads the first handle's records: the file is the state
    assert second_handle.records() == first_handle.records()

    # earlier records are a PREFIX of the file after any later append
    before = path.read_bytes()
    second_handle.append("b", {"n": 2})
    after = path.read_bytes()
    assert after.startswith(before) and len(after) > len(before)
    assert [r.seq for r in first_handle.records()] == [1, 2, 3, 4]


def test_w6_concurrent_writers_produce_one_gapless_sequence(tmp_path: Path) -> None:
    path = tmp_path / "ledger" / "events.jsonl"
    writers, each = 4, 25

    def write_many(writer: str) -> None:
        surface = AppendSurface(path)
        for n in range(each):
            surface.append(writer, {"n": n})

    with ThreadPoolExecutor(max_workers=writers) as pool:
        list(pool.map(write_many, [f"w{i}" for i in range(writers)]))

    records = AppendSurface(path).records()
    assert [r.seq for r in records] == list(range(1, writers * each + 1))
    for i in range(writers):
        mine = [r.payload["n"] for r in records if r.writer == f"w{i}"]
        assert mine == list(range(each))  # each writer's own order is preserved


# --------------------------------------------------------------------------- measurement


def test_per_state_latency_is_read_from_the_receipts_own_timestamps_and_printed(
    parent: Parent, tmp_path: Path
) -> None:
    """Not a witness: the measurement the prototype must print (per-state seconds, from
    the receipt's timestamps, for one landing and for a two-member set). Run with ``-s``
    or read the captured table; the assertions only pin that the timestamps are ordered
    and that every state of the landing path has a row. For SET members the ``applied``
    row spans prepare -> land by construction (the planned transition is written at
    prepare time), so it reads as the time the prepared base sat, not the push alone."""
    child_a = parent.child("child-a")
    author(child_a, "canon v2 (a)\n")
    single = contributor(parent, child_a, "a").run(contribution("child-a"), canonical(parent))
    assert single is not None and single.state is State.ACKNOWLEDGED

    owner2 = make_owner(tmp_path, "owner2")
    b1, b2 = parent.child("b1"), owner2.child("b2")
    author(b1, "canon v3 (set)\n")
    author(b2, "owner2 canon v2 (set)\n")
    contribution_set = ContributionSet(
        "timed", [member(parent, b1, "m1"), member(owner2, b2, "m2")]
    )
    assert contribution_set.prepare().phase == "prepared"
    landed = contribution_set.land()
    assert landed.phase == "landed"

    lines = ["per-state latency (seconds since previous transition), from receipt timestamps"]
    for label, receipt in [("single", single)] + [
        (o.member_id, o.receipt) for o in landed.outcomes if o.receipt is not None
    ]:
        rows = state_latencies(receipt)
        assert [state for state, _ in rows] == [
            str(State.OBSERVED),
            str(State.FETCHED),
            str(State.PLANNED),
            str(State.APPLIED),
            str(State.VERIFIED),
            str(State.ACKNOWLEDGED),
        ]
        assert all(seconds >= 0.0 for _, seconds in rows)
        total = sum(seconds for _, seconds in rows)
        lines.append(
            f"  {label:>6}: "
            + "  ".join(f"{s}={sec:.3f}" for s, sec in rows)
            + f"  total={total:.3f}"
        )
    report = tmp_path / "latency.txt"
    report.write_text("\n".join(lines) + "\n")
    print("\n" + report.read_text(), end="")  # visible with -s; the file is the artifact
    assert report.read_text().count("total=") == 3
