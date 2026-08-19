"""Prototype 1: the propagation daemon, proven on a synthetic source and a declared replica.

Everything here runs under ``tmp_path``: one bare "source" remote with a config-like file
on ``main``, an authoring clone that pushes changes to it, and a replica path that the
declaration names. No real workspace, remote, or authoring clone is touched.

What the tests prove, each as its own witness:

* a declaration names exactly one managed replica; an authoring kind, an unknown git
  environment, a non-positive interval, or a missing field is refused before any git call
* ``ensure_replica`` clones the declared branch when the path is absent, accepts the path
  it declared, and refuses a checkout whose origin or branch differ, or a non-git directory
* the first tick on a fresh replica acknowledges without running the verb (the replica
  was born at the source revision); a tick with no new revision is not an operation and
  writes nothing; a pushed change is applied on the next tick with exact revisions
* every receipt that is an operation is written as its own JSON file and announced as one
  ``propagation.receipt`` event on the outbox; a refusal is a receipt too, and the refused
  destination is left untouched
* the latency figures in a written receipt are recomputable from that receipt's own
  transition timestamps
* ``run_loop`` ticks once under ``once``, stops when told, sleeps the declared interval,
  and prints exactly one line per tick
"""

from __future__ import annotations

import io
import json
import os
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pytest
from gr2.prototypes.propagation_daemon import (
    ACTOR,
    Declaration,
    DeclarationError,
    DeclarationMismatch,
    declaration_from_dict,
    ensure_replica,
    latency_from_receipt,
    load_declaration,
    main,
    make_propagator,
    run_loop,
    summarize,
    tick,
)
from gr2.prototypes.propagation_state_machine import (
    DestinationKind,
    Direction,
    Operation,
    State,
)
from gr2.python_cli.events import EventType

# Commits in the synthetic repositories must not depend on, or touch, the machine's
# global git configuration (signing keys, hooks paths, identities).
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


def _run(*args: str) -> None:
    subprocess.run(
        list(args), check=True, capture_output=True, text=True, env={**os.environ, **_GIT_ENV}
    )


def snapshot(repo: Path) -> dict[str, str]:
    """Everything an 'untouched' claim is about: refs, HEAD, index+worktree state, bytes."""
    return {
        "refs": git(repo, "for-each-ref"),
        "head": git(repo, "rev-parse", "HEAD"),
        "porcelain": git(repo, "status", "--porcelain"),
        "canon": (repo / "canon.md").read_text(),
        "reflog": git(repo, "reflog", "show", "--format=%gs", "HEAD"),
    }


@dataclass
class Synthetic:
    remote: Path
    author: Path
    base: str
    root: Path

    def push_change(self, text: str) -> str:
        (self.author / "canon.md").write_text(text)
        git(self.author, "add", "canon.md")
        git(self.author, "commit", "-q", "-m", f"canon: {text.strip()[:40]}")
        git(self.author, "push", "-q", "origin", "main")
        return git(self.author, "rev-parse", "HEAD")


def _bare_with_one_commit(root: Path, name: str, text: str) -> tuple[Path, Path, str]:
    remote = root / f"{name}.git"
    _run("git", "init", "-q", "--bare", "--initial-branch=main", str(remote))
    author = root / f"{name}-author"
    _run("git", "clone", "-q", str(remote), str(author))
    git(author, "switch", "-q", "-c", "main")
    (author / "canon.md").write_text(text)
    git(author, "add", "canon.md")
    git(author, "commit", "-q", "-m", text.strip())
    git(author, "push", "-q", "-u", "origin", "main")
    return remote, author, git(author, "rev-parse", "HEAD")


@pytest.fixture
def synthetic(tmp_path: Path) -> Synthetic:
    remote, author, base = _bare_with_one_commit(tmp_path, "source", "canon v1\n")
    return Synthetic(remote=remote, author=author, base=base, root=tmp_path)


def declaration_dict(syn: Synthetic, **overrides: object) -> dict[str, object]:
    data: dict[str, object] = {
        "source_url": str(syn.remote),
        "branch": "main",
        "destination_id": "config-main-replica",
        "destination_path": str(syn.root / "replicas" / "config-main"),
        "state_dir": str(syn.root / "propagation" / "config-main"),
        "outbox_root": str(syn.root / "workspace"),
        "coordinate": {
            "source": "synthetic/source",
            "layer": "config",
            "artifact_class": "config-tree",
        },
        "interval_seconds": 7.5,
    }
    data.update(overrides)
    return data


@pytest.fixture
def declaration(synthetic: Synthetic) -> Declaration:
    return declaration_from_dict(declaration_dict(synthetic))


def outbox_events(root: Path) -> list[dict[str, object]]:
    outbox = root / ".grip" / "events" / "outbox.jsonl"
    if not outbox.exists():
        return []
    return [json.loads(line) for line in outbox.read_text().splitlines() if line.strip()]


def receipt_files(decl: Declaration) -> list[Path]:
    if not decl.receipts_dir.exists():
        return []
    return sorted(p for p in decl.receipts_dir.iterdir() if p.suffix == ".json")


def applied_observation(receipt) -> dict[str, object]:
    applied = [t for t in receipt.transitions if t.state is State.APPLIED]
    assert len(applied) == 1, [t.state for t in receipt.transitions]
    return applied[0].observation


# ----------------------------------------------------------------------- declaration


def test_declaration_builds_a_downward_apply_coordinate_for_one_managed_replica(
    synthetic: Synthetic,
) -> None:
    decl = declaration_from_dict(declaration_dict(synthetic))
    assert decl.source_url == str(synthetic.remote)
    assert decl.branch == "main"
    assert decl.kind is DestinationKind.REPLICA
    assert decl.destination().kind is DestinationKind.REPLICA
    assert decl.destination().destination_id == "config-main-replica"
    assert decl.coordinate.destination == "config-main-replica"
    assert decl.coordinate.direction is Direction.DOWN
    assert decl.coordinate.operation is Operation.APPLY
    assert decl.coordinate.source == "synthetic/source"
    assert decl.coordinate.layer == "config"
    assert decl.coordinate.artifact_class == "config-tree"
    assert decl.interval_seconds == 7.5
    assert decl.policy().allowed_directions == frozenset({Direction.DOWN})
    assert decl.receipts_dir == decl.state_dir / "receipts"
    # the default git environment is isolated from the host; "inherit" is the opt-in
    assert decl.git_env_mode == "isolated"
    assert decl.git_env["GIT_CONFIG_GLOBAL"] == os.devnull
    assert decl.git_env["GIT_CONFIG_NOSYSTEM"] == "1"
    # a daemon never answers a prompt, in either mode
    assert decl.git_env["GIT_TERMINAL_PROMPT"] == "0"
    inherit = declaration_from_dict(declaration_dict(synthetic, git_env="inherit"))
    # inherit carries ONLY the prompt override: the host's config and credential helper
    # stay in force, which is the whole point of declaring it for a private remote
    assert inherit.git_env == {"GIT_TERMINAL_PROMPT": "0"}


def test_declaration_defaults_interval_and_policy_hash_when_absent(synthetic: Synthetic) -> None:
    data = declaration_dict(synthetic)
    del data["interval_seconds"]
    decl = declaration_from_dict(data)
    assert decl.interval_seconds == 30.0
    assert decl.policy_hash == "prototype-1-downward-only"


@pytest.mark.parametrize(
    "missing",
    ["source_url", "branch", "destination_id", "destination_path", "state_dir", "outbox_root"],
)
def test_declaration_refuses_a_missing_field_by_name(synthetic: Synthetic, missing: str) -> None:
    data = declaration_dict(synthetic)
    del data[missing]
    with pytest.raises(DeclarationError, match=missing):
        declaration_from_dict(data)


def test_declaration_refuses_a_missing_or_incomplete_coordinate(synthetic: Synthetic) -> None:
    data = declaration_dict(synthetic)
    del data["coordinate"]
    with pytest.raises(DeclarationError, match="coordinate"):
        declaration_from_dict(data)
    with pytest.raises(DeclarationError, match="coordinate must be an object"):
        declaration_from_dict(declaration_dict(synthetic, coordinate="synthetic/source"))
    partial = {"source": "synthetic/source", "layer": "config"}
    with pytest.raises(DeclarationError, match="artifact_class"):
        declaration_from_dict(declaration_dict(synthetic, coordinate=partial))


@pytest.mark.parametrize("kind", ["authoring", "mirror", ""])
def test_declaration_refuses_any_kind_but_replica_before_any_git_call(
    synthetic: Synthetic, kind: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # if the refusal happened after a git call, this would raise something else first
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **k: pytest.fail("git was invoked for a refused kind")
    )
    with pytest.raises(DeclarationError, match="managed replicas only"):
        declaration_from_dict(declaration_dict(synthetic, kind=kind))


def test_declaration_accepts_the_replica_kind_spelled_out(synthetic: Synthetic) -> None:
    decl = declaration_from_dict(declaration_dict(synthetic, kind="replica"))
    assert decl.kind is DestinationKind.REPLICA


def test_declaration_refuses_an_unknown_git_environment(synthetic: Synthetic) -> None:
    with pytest.raises(DeclarationError, match="git_env must be"):
        declaration_from_dict(declaration_dict(synthetic, git_env="host"))


@pytest.mark.parametrize("interval", [0, -1, -0.5])
def test_declaration_refuses_a_non_positive_interval(synthetic: Synthetic, interval: float) -> None:
    with pytest.raises(DeclarationError, match="interval_seconds must be positive"):
        declaration_from_dict(declaration_dict(synthetic, interval_seconds=interval))


def test_load_declaration_reads_a_json_object_and_refuses_anything_else(
    synthetic: Synthetic, tmp_path: Path
) -> None:
    path = tmp_path / "declaration.json"
    path.write_text(json.dumps(declaration_dict(synthetic)))
    decl = load_declaration(path)
    assert decl.destination_id == "config-main-replica"
    assert decl.destination_path == synthetic.root / "replicas" / "config-main"
    path.write_text(json.dumps([declaration_dict(synthetic)]))
    with pytest.raises(DeclarationError, match="JSON object"):
        load_declaration(path)


def test_make_propagator_passes_the_source_url_through_as_the_exact_string(
    synthetic: Synthetic,
) -> None:
    # a Path would collapse the "//" of a URL scheme into "/" and the source would
    # silently become a relative directory; the machine only ever stringifies it
    url = "https://example.invalid/org/config.git"
    decl = declaration_from_dict(declaration_dict(synthetic, source_url=url))
    propagator = make_propagator(decl)
    assert str(propagator.source_remote) == url
    assert "//" in str(propagator.source_remote)
    assert propagator.branch == "main"
    assert propagator.state_dir == decl.state_dir
    assert propagator.policy == decl.policy()
    assert propagator.git_env == decl.git_env
    assert "GIT_CONFIG_GLOBAL" in propagator.git_env  # isolated by default
    # and the inherit mode reaches the machine as inherit: the host config is NOT masked
    # (the first dogfood run lost the credential helper here and hung on a username prompt)
    inherit = make_propagator(declaration_from_dict(declaration_dict(synthetic, git_env="inherit")))
    assert inherit.git_env == {"GIT_TERMINAL_PROMPT": "0"}
    assert "GIT_CONFIG_GLOBAL" not in inherit.git_env


# ----------------------------------------------------------------------- ensure_replica


def test_ensure_replica_clones_the_declared_branch_single_branch_when_absent(
    synthetic: Synthetic, declaration: Declaration
) -> None:
    # a second branch on the source makes --single-branch load-bearing: without it the
    # clone would carry refs/remotes/origin/scratch too, and the assertion below would fail
    git(synthetic.author, "push", "-q", "origin", "main:refs/heads/scratch")
    assert not declaration.destination_path.exists()
    path = ensure_replica(declaration)
    assert path == declaration.destination_path
    assert git(path, "remote", "get-url", "origin") == str(synthetic.remote)
    assert git(path, "rev-parse", "--abbrev-ref", "HEAD") == "main"
    assert git(path, "rev-parse", "HEAD") == synthetic.base
    assert (path / "canon.md").read_text() == "canon v1\n"
    tracking = git(path, "for-each-ref", "--format=%(refname)", "refs/remotes/").splitlines()
    assert tracking == ["refs/remotes/origin/main"]


def test_ensure_replica_accepts_the_path_it_declared_and_leaves_it_untouched(
    declaration: Declaration,
) -> None:
    ensure_replica(declaration)
    before = snapshot(declaration.destination_path)
    assert ensure_replica(declaration) == declaration.destination_path
    assert snapshot(declaration.destination_path) == before


def test_ensure_replica_refuses_a_checkout_whose_origin_is_not_the_declared_source(
    synthetic: Synthetic, declaration: Declaration
) -> None:
    other, _, _ = _bare_with_one_commit(synthetic.root, "other", "other v1\n")
    declaration.destination_path.parent.mkdir(parents=True)
    _run("git", "clone", "-q", str(other), str(declaration.destination_path))
    before = snapshot(declaration.destination_path)
    with pytest.raises(DeclarationMismatch, match="has origin"):
        ensure_replica(declaration)
    assert snapshot(declaration.destination_path) == before


def test_ensure_replica_refuses_a_checkout_on_another_branch(
    synthetic: Synthetic, declaration: Declaration
) -> None:
    ensure_replica(declaration)
    git(declaration.destination_path, "switch", "-q", "-c", "scratch")
    before = snapshot(declaration.destination_path)
    with pytest.raises(DeclarationMismatch, match="is on 'scratch'"):
        ensure_replica(declaration)
    assert snapshot(declaration.destination_path) == before


def test_ensure_replica_refuses_a_path_that_is_not_a_git_checkout(
    declaration: Declaration,
) -> None:
    declaration.destination_path.mkdir(parents=True)
    (declaration.destination_path / "canon.md").write_text("not a clone\n")
    with pytest.raises(DeclarationMismatch, match="not a git checkout"):
        ensure_replica(declaration)
    assert (declaration.destination_path / "canon.md").read_text() == "not a clone\n"
    assert not (declaration.destination_path / ".git").exists()


# ----------------------------------------------------------------------- ticks


def test_first_tick_on_a_fresh_replica_acknowledges_without_running_the_verb(
    synthetic: Synthetic, declaration: Declaration
) -> None:
    ensure_replica(declaration)
    propagator = make_propagator(declaration)
    result = tick(declaration, propagator)
    assert result.was_operation
    assert result.cursor_before is None
    assert result.source_rev == synthetic.base
    receipt = result.receipt
    assert receipt is not None
    assert receipt.state is State.ACKNOWLEDGED
    assert receipt.attempt == 1
    assert receipt.replayed is False
    assert receipt.source_rev == synthetic.base
    assert receipt.expected_base == synthetic.base
    assert receipt.after == synthetic.base
    # the replica was born at the source revision: the read-back established it, no verb
    assert applied_observation(receipt)["verb_ran_now"] is False
    assert git(declaration.destination_path, "rev-parse", "HEAD") == synthetic.base
    # one receipt file, one outbox event, one summary carried by both
    files = receipt_files(declaration)
    assert files == [result.receipt_path]
    assert files[0].name.endswith(f"-{receipt.pending_id[:12]}-acknowledged.json")
    events = outbox_events(declaration.outbox_root)
    assert [e["type"] for e in events] == [EventType.PROPAGATION_RECEIPT.value]
    event = events[0]
    assert event["actor"] == ACTOR
    assert event["owner_unit"] == declaration.destination_id
    assert event["summary"] == result.summary
    assert event["state"] == "acknowledged"
    assert event["pending_id"] == receipt.pending_id
    assert event["operation_id"] == receipt.operation_id
    assert event["source_rev"] == synthetic.base
    assert event["expected_base"] == synthetic.base
    assert event["after"] == synthetic.base
    assert event["replayed"] is False
    assert event["receipt_path"] == str(result.receipt_path)
    assert result.summary.startswith("propagation acknowledged: config-main-replica at ")
    assert "attempt 1" in result.summary


def test_a_tick_with_no_new_revision_is_not_an_operation_and_writes_nothing(
    synthetic: Synthetic, declaration: Declaration
) -> None:
    ensure_replica(declaration)
    propagator = make_propagator(declaration)
    first = tick(declaration, propagator)
    assert first.was_operation
    files_before = receipt_files(declaration)
    events_before = outbox_events(declaration.outbox_root)
    before = snapshot(declaration.destination_path)
    second = tick(declaration, propagator)
    assert not second.was_operation
    assert second.receipt is None
    assert second.receipt_path is None
    assert second.latency_seconds is None
    assert second.cursor_before == synthetic.base
    assert second.source_rev == synthetic.base
    assert "not an operation" in second.summary
    assert "cursor already at" in second.summary
    assert receipt_files(declaration) == files_before
    assert outbox_events(declaration.outbox_root) == events_before
    assert snapshot(declaration.destination_path) == before


def test_a_pushed_change_is_applied_on_the_next_tick_with_exact_revisions(
    synthetic: Synthetic, declaration: Declaration
) -> None:
    ensure_replica(declaration)
    propagator = make_propagator(declaration)
    tick(declaration, propagator)
    new = synthetic.push_change("canon v2\n")
    assert new != synthetic.base
    result = tick(declaration, propagator)
    assert result.was_operation
    assert result.cursor_before == synthetic.base
    assert result.source_rev == new
    receipt = result.receipt
    assert receipt is not None
    assert receipt.state is State.ACKNOWLEDGED
    assert receipt.attempt == 1
    assert receipt.replayed is False
    assert receipt.source_rev == new
    assert receipt.expected_base == synthetic.base
    assert receipt.after == new
    assert applied_observation(receipt)["verb_ran_now"] is True
    assert git(declaration.destination_path, "rev-parse", "HEAD") == new
    assert (declaration.destination_path / "canon.md").read_text() == "canon v2\n"
    assert git(declaration.destination_path, "status", "--porcelain") == ""
    # exact revisions in the one line a channel reader sees
    assert f"at {synthetic.base[:12]} -> {new[:12]}, intended {new[:12]}" in result.summary
    assert "(source synthetic/source, attempt 1, total " in result.summary
    # a second receipt file and a second outbox event, each naming the new revision
    files = receipt_files(declaration)
    assert len(files) == 2
    assert result.receipt_path in files
    events = outbox_events(declaration.outbox_root)
    assert len(events) == 2
    assert events[1]["source_rev"] == new
    assert events[1]["expected_base"] == synthetic.base
    assert events[1]["after"] == new
    assert events[1]["state"] == "acknowledged"
    # and the tick after that is current again: nothing written, nothing emitted
    third = tick(declaration, propagator)
    assert not third.was_operation
    assert third.cursor_before == new
    assert receipt_files(declaration) == files
    assert outbox_events(declaration.outbox_root) == events


def test_written_receipt_round_trips_and_its_latency_is_recomputable_from_itself(
    synthetic: Synthetic, declaration: Declaration
) -> None:
    ensure_replica(declaration)
    propagator = make_propagator(declaration)
    tick(declaration, propagator)
    new = synthetic.push_change("canon v2\n")
    result = tick(declaration, propagator)
    assert result.receipt is not None and result.receipt_path is not None
    payload = json.loads(result.receipt_path.read_text())
    assert set(payload) == {"daemon", "declaration", "observed_at", "latency_seconds", "receipt"}
    assert payload["daemon"] == ACTOR
    assert payload["declaration"] == {
        "source_url": str(synthetic.remote),
        "branch": "main",
        "destination_id": "config-main-replica",
        "destination_path": str(declaration.destination_path),
    }
    assert payload["observed_at"] == result.observed_at
    assert payload["receipt"] == result.receipt.as_dict()
    assert payload["receipt"]["state"] == "acknowledged"
    assert payload["receipt"]["source_rev"] == new
    assert payload["receipt"]["after"] == new
    # the latency the daemon reports is the latency the module derives from the receipt
    assert payload["latency_seconds"] == result.latency_seconds
    assert result.latency_seconds == latency_from_receipt(result.receipt)
    # and it is recomputable by a reader who has ONLY the written file
    transitions = payload["receipt"]["transitions"]
    states = [t["state"] for t in transitions]
    assert states == ["observed", "fetched", "planned", "applied", "verified", "acknowledged"]
    stamps = [datetime.fromisoformat(t["timestamp"]) for t in transitions]
    recomputed = {
        f"{a['state']}->{b['state']}": round((tb - ta).total_seconds(), 6)
        for (a, ta), (b, tb) in zip(
            zip(transitions, stamps, strict=True),
            zip(transitions[1:], stamps[1:], strict=True),
            strict=False,
        )
    }
    recomputed["total"] = round((stamps[-1] - stamps[0]).total_seconds(), 6)
    assert payload["latency_seconds"] == recomputed
    assert set(recomputed) == {
        "observed->fetched",
        "fetched->planned",
        "planned->applied",
        "applied->verified",
        "verified->acknowledged",
        "total",
    }
    assert all(value >= 0 for value in recomputed.values())
    assert recomputed["total"] == pytest.approx(
        sum(v for k, v in recomputed.items() if k != "total"), abs=1e-5
    )


def test_a_dirty_replica_is_refused_with_a_receipt_left_untouched_then_applies_once_clean(
    synthetic: Synthetic, declaration: Declaration
) -> None:
    ensure_replica(declaration)
    propagator = make_propagator(declaration)
    tick(declaration, propagator)
    (declaration.destination_path / "canon.md").write_text("local edit on the replica\n")
    new = synthetic.push_change("canon v2\n")
    before = snapshot(declaration.destination_path)
    refused = tick(declaration, propagator)
    assert refused.was_operation
    receipt = refused.receipt
    assert receipt is not None
    assert receipt.state is State.REFUSED
    assert receipt.attempt == 1
    assert receipt.after is None
    assert receipt.refusal_reason is not None
    assert receipt.refusal_reason.startswith("destination.clean:")
    assert "refused: destination.clean:" in refused.summary
    assert "-> unchanged" in refused.summary
    # refused means untouched: refs, HEAD, worktree bytes, reflog all as before
    assert snapshot(declaration.destination_path) == before
    # and a refusal is a receipt too: written and announced
    files = receipt_files(declaration)
    assert refused.receipt_path in files
    assert refused.receipt_path.name.endswith("-refused.json")
    events = outbox_events(declaration.outbox_root)
    assert events[-1]["state"] == "refused"
    assert events[-1]["after"] is None
    assert events[-1]["source_rev"] == new
    # clean up, and the next tick is a NEW attempt at the same revision, not a replay
    git(declaration.destination_path, "checkout", "--", "canon.md")
    applied = tick(declaration, propagator)
    assert applied.receipt is not None
    assert applied.receipt.state is State.ACKNOWLEDGED
    assert applied.receipt.attempt == 2
    assert applied.receipt.replayed is False
    assert applied.receipt.after == new
    assert git(declaration.destination_path, "rev-parse", "HEAD") == new
    assert "attempt 2" in applied.summary
    assert len(receipt_files(declaration)) == len(files) + 1
    assert outbox_events(declaration.outbox_root)[-1]["state"] == "acknowledged"


def test_tick_writes_and_announces_nothing_when_the_machine_returns_none(
    declaration: Declaration, monkeypatch: pytest.MonkeyPatch
) -> None:
    # the only way to reach this branch is a race (the source moved back to the cursor
    # between observe and run), so the machine's answer is forced here; the claim under
    # test is the daemon's: no receipt, no file, no event
    ensure_replica(declaration)
    propagator = make_propagator(declaration)
    monkeypatch.setattr(propagator, "run", lambda coordinate, destination: None)
    result = tick(declaration, propagator)
    assert not result.was_operation
    assert result.receipt_path is None
    assert "source returned to the cursor" in result.summary
    assert receipt_files(declaration) == []
    assert outbox_events(declaration.outbox_root) == []


def test_summarize_names_state_destination_revisions_attempt_and_total(
    synthetic: Synthetic, declaration: Declaration
) -> None:
    ensure_replica(declaration)
    propagator = make_propagator(declaration)
    tick(declaration, propagator)
    new = synthetic.push_change("canon v2\n")
    receipt = tick(declaration, propagator).receipt
    assert receipt is not None
    line = summarize(receipt, {"total": 1.23456})
    assert line == (
        f"propagation acknowledged: config-main-replica at {synthetic.base[:12]} -> {new[:12]}, "
        f"intended {new[:12]} (source synthetic/source, attempt 1, total 1.235s)"
    )
    # a replayed receipt says so, and a missing total reads as 0.000s rather than failing
    from dataclasses import replace

    replayed = replace(receipt, replayed=True)
    assert summarize(replayed, {}).endswith(
        "(source synthetic/source, attempt 1, replayed, total 0.000s)"
    )


# ----------------------------------------------------------------------- loop + CLI


def test_run_loop_once_ensures_the_replica_ticks_once_and_prints_exactly_one_line(
    synthetic: Synthetic, declaration: Declaration
) -> None:
    out = io.StringIO()
    assert not declaration.destination_path.exists()
    stats = run_loop(
        declaration, once=True, sleep=lambda s: pytest.fail("slept under once"), out=out
    )
    assert declaration.destination_path.exists()
    assert stats.ticks == 1
    assert stats.operations == 1
    assert stats.by_state == {"acknowledged": 1}
    assert stats.last is not None and stats.last.was_operation
    lines = out.getvalue().splitlines()
    assert len(lines) == 1
    assert lines[0] == f"{stats.last.observed_at} {stats.last.summary}"


def test_a_tick_whose_git_call_fails_is_printed_counted_and_the_loop_goes_on(
    synthetic: Synthetic, declaration: Declaration
) -> None:
    ensure_replica(declaration)
    # take the source away: the replica still names it as origin, so ensure_replica accepts
    # the path, and the first git call of the tick (ls-remote) fails
    moved = synthetic.remote.with_name("source.git.moved")
    synthetic.remote.rename(moved)
    out = io.StringIO()
    slept: list[float] = []
    seen = {"n": 0}

    def stop() -> bool:
        seen["n"] += 1
        return seen["n"] >= 2

    stats = run_loop(declaration, stop=stop, sleep=slept.append, out=out)
    assert stats.ticks == 2
    assert stats.failures == 2
    assert stats.operations == 0
    assert stats.by_state == {}
    assert stats.last is None
    assert slept == [7.5]  # it kept going after the first failure
    lines = out.getvalue().splitlines()
    assert len(lines) == 2
    for line in lines:
        assert "propagation tick-failed: config-main-replica git ls-remote exited" in line
        assert "ls-remote" in line
        assert "this tick left no receipt" in line
    assert receipt_files(declaration) == []
    assert outbox_events(declaration.outbox_root) == []
    # put the source back: the very next tick is an ordinary operation, nothing to repair
    moved.rename(synthetic.remote)
    recovered = run_loop(declaration, once=True, sleep=slept.append, out=io.StringIO())
    assert recovered.failures == 0
    assert recovered.operations == 1
    assert recovered.by_state == {"acknowledged": 1}


def test_run_loop_stops_when_told_and_sleeps_the_declared_interval_between_ticks(
    synthetic: Synthetic, declaration: Declaration
) -> None:
    out = io.StringIO()
    slept: list[float] = []
    ticks_seen = {"n": 0}

    def stop() -> bool:
        ticks_seen["n"] += 1
        return ticks_seen["n"] >= 3

    stats = run_loop(declaration, stop=stop, sleep=slept.append, out=out)
    assert stats.ticks == 3
    assert stats.operations == 1  # the first tick; the next two found the cursor current
    assert stats.by_state == {"acknowledged": 1}
    assert slept == [7.5, 7.5]
    lines = out.getvalue().splitlines()
    assert len(lines) == 3
    assert "propagation acknowledged" in lines[0]
    assert all("not an operation" in line for line in lines[1:])


def test_main_once_runs_a_single_tick_from_a_declaration_file(
    synthetic: Synthetic, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "declaration.json"
    path.write_text(json.dumps(declaration_dict(synthetic)))
    decl = load_declaration(path)
    assert main(["--declaration", str(path), "--once"]) == 0
    captured = capsys.readouterr()
    lines = captured.out.splitlines()
    assert len(lines) == 1
    assert "propagation acknowledged: config-main-replica" in lines[0]
    assert len(receipt_files(decl)) == 1
    assert [e["type"] for e in outbox_events(decl.outbox_root)] == ["propagation.receipt"]


def test_main_interval_override_replaces_the_declared_interval(
    synthetic: Synthetic, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "declaration.json"
    path.write_text(json.dumps(declaration_dict(synthetic)))
    seen: dict[str, object] = {}

    def fake_run_loop(declaration: Declaration, *, once: bool = False, **_: object):
        seen["interval"] = declaration.interval_seconds
        seen["once"] = once
        return None

    import gr2.prototypes.propagation_daemon as daemon

    monkeypatch.setattr(daemon, "run_loop", fake_run_loop)
    assert main(["--declaration", str(path), "--once", "--interval", "2.5"]) == 0
    assert seen == {"interval": 2.5, "once": True}
    assert main(["--declaration", str(path)]) == 0
    assert seen == {"interval": 7.5, "once": False}
