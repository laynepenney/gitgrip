"""M0 witnesses for lane creation, transitions, and outcome truth."""

from __future__ import annotations

import argparse
import json
import multiprocessing
from pathlib import Path

import pytest

from gr2.python_cli import app as app_module
from gr2.prototypes import lane_workspace_prototype as lanes


def _workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    (workspace / ".grip").mkdir(parents=True)
    (workspace / ".grip" / "workspace_spec.toml").write_text(
        '''schema_version = 1
workspace_name = "m0"

[[repos]]
name = "app"
path = "repos/app"
url = "https://example.invalid/app.git"

[[units]]
name = "atlas"
path = "agents/atlas"
repos = ["app"]
'''
    )
    return workspace


def _create(workspace: Path, name: str, *, branch: str = "main") -> argparse.Namespace:
    return argparse.Namespace(
        workspace_root=workspace, owner_unit="atlas", lane_name=name, type="feature",
        repos="app", branch=f"app={branch}", source="test", default_commands=[],
    )


def _enter_process(workspace: str, name: str, ready, start) -> None:
    ready.set()
    start.wait(5)
    lanes.enter_lane(argparse.Namespace(
        workspace_root=Path(workspace), owner_unit="atlas", lane_name=name,
        actor=f"agent:{name}", notify_channel=False, recall=False,
    ))


def test_create_is_exact_idempotent_and_conflicting_create_preserves_bytes(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    args = _create(workspace, "feature")
    assert lanes.create_lane(args) == 0
    metadata = lanes.lane_file(workspace, "atlas", "feature")
    original = metadata.read_bytes()

    assert lanes.create_lane(args) == 0
    assert metadata.read_bytes() == original

    with pytest.raises(SystemExit, match="refusing to replace existing lane"):
        lanes.create_lane(_create(workspace, "feature", branch="other"))
    assert metadata.read_bytes() == original


def test_rejected_create_leaves_no_target_tree(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    target = lanes.lane_dir(workspace, "atlas", "occupied")
    target.mkdir(parents=True)
    before = sorted(path.relative_to(workspace) for path in workspace.rglob("*"))
    with pytest.raises(SystemExit, match="refusing to create lane over existing path"):
        lanes.create_lane(_create(workspace, "occupied"))
    assert sorted(path.relative_to(workspace) for path in workspace.rglob("*")) == before


def test_atomic_replace_retains_old_bytes_when_publication_is_interrupted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "state.json"
    path.write_text("old")
    monkeypatch.setattr(lanes.os, "replace", lambda *_args: (_ for _ in ()).throw(OSError("interrupt")))
    with pytest.raises(OSError, match="interrupt"):
        lanes.atomic_replace_text(path, "new")
    assert path.read_text() == "old"
    assert list(tmp_path.glob(".state.json.*")) == []


def test_enter_exit_return_structured_outcomes_and_preserve_return_stack(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    for name in ("home", "review"):
        lanes.create_lane(_create(workspace, name))

    entered = lanes.enter_lane(argparse.Namespace(
        workspace_root=workspace, owner_unit="atlas", lane_name="home", actor="agent:a",
        notify_channel=False, recall=False,
    ))
    review = lanes.enter_lane(argparse.Namespace(
        workspace_root=workspace, owner_unit="atlas", lane_name="review", actor="agent:a",
        notify_channel=False, recall=False,
    ))
    exited = lanes.exit_lane(argparse.Namespace(
        workspace_root=workspace, owner_unit="atlas", actor="agent:a", notify_channel=False, recall=False,
    ))

    assert entered.as_dict()["current_lane"] == "home"
    assert review.previous_lane == "home"
    assert exited.previous_lane == "review"
    assert exited.current_lane == "home"
    assert exited.exit_code == 0
    assert lanes.require_current_lane(workspace, "atlas")["lane_name"] == "home"


def test_python_cli_renders_the_transition_writer_outcome(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    workspace = _workspace(tmp_path)
    lanes.create_lane(_create(workspace, "feature"))
    capsys.readouterr()

    app_module.lane_enter(workspace, "atlas", "feature", "agent:atlas", False, False, False)

    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "status": "ok",
        "action": "enter",
        "owner_unit": "atlas",
        "previous_lane": None,
        "current_lane": "feature",
        "state_path": str(lanes.current_lane_file(workspace, "atlas")),
    }


def test_concurrent_enters_keep_both_transitions_in_current_or_history(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    for name in ("home", "one", "two"):
        lanes.create_lane(_create(workspace, name))
    lanes.enter_lane(argparse.Namespace(
        workspace_root=workspace, owner_unit="atlas", lane_name="home", actor="agent:home",
        notify_channel=False, recall=False,
    ))
    ctx = multiprocessing.get_context("fork")
    start = ctx.Event()
    ready = [ctx.Event(), ctx.Event()]
    processes = [ctx.Process(target=_enter_process, args=(str(workspace), name, signal, start)) for name, signal in zip(("one", "two"), ready)]
    for process in processes:
        process.start()
    for signal in ready:
        assert signal.wait(5)
    start.set()
    for process in processes:
        process.join(10)
        assert process.exitcode == 0

    state = json.loads(lanes.current_lane_file(workspace, "atlas").read_text())
    names = {state["current"]["lane_name"], *(item["lane_name"] for item in state["recent"])}
    assert {"home", "one", "two"} <= names


def test_blocked_plan_reports_nonzero_and_damaged_audit_keeps_healthy_rows(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    workspace = _workspace(tmp_path)
    lanes.create_lane(_create(workspace, "feature"))
    capsys.readouterr()
    lease_path = lanes.lane_leases_file(workspace, "atlas", "feature")
    lease_path.parent.mkdir(parents=True, exist_ok=True)
    lease_path.write_text(json.dumps([{"actor": "agent:other", "mode": "edit", "acquired_at": "2026-01-01T00:00:00+00:00"}]))
    assert lanes.plan_exec(argparse.Namespace(workspace_root=workspace, owner_unit="atlas", lane_name="feature", command_text="true", repos=None, json=True)) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "blocked"

    for name in ("healthy", "damaged"):
        lanes.create_shared_scratchpad(argparse.Namespace(
            workspace_root=workspace, name=name, kind="doc", purpose="test", participant=["atlas"], ref=["x"], source="test",
        ))
    damaged_docs = lanes.shared_scratchpad_dir(workspace, "damaged") / "docs"
    (damaged_docs / "README.md").unlink()
    damaged_docs.rmdir()
    assert lanes.audit_shared_scratchpads(argparse.Namespace(workspace_root=workspace, stale_days=30)) == 0
    report = capsys.readouterr().out
    assert "healthy\tok" in report
    assert "damaged\tneeds-attention" in report
    assert "missing-docs-root" in report


# --------------------------------------------------------------------------- #
# lane_kind + --bind (gr2-lane-author-shape ruling, 2026-09-03)
# --------------------------------------------------------------------------- #
import subprocess


def _git(path: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=str(path), capture_output=True, text=True)


def _real_worktree(parent: Path, name: str = "wt", branch: str = "feat/x") -> Path:
    # The worktree is created UNDER `parent` so a bound lane whose worktree must
    # live inside workspace_root can pass containment; pass the workspace here.
    wt = parent / name
    wt.mkdir(parents=True)
    assert _git(wt, "init", "-q").returncode == 0
    _git(wt, "config", "user.email", "t@t.invalid")
    _git(wt, "config", "user.name", "t")
    (wt / "f.txt").write_text("hi\n")
    _git(wt, "add", ".")
    assert _git(wt, "commit", "-qm", "init").returncode == 0
    assert _git(wt, "checkout", "-qb", branch).returncode == 0
    return wt


def _create_bound(workspace: Path, name: str, bind: Path, *, repos: str = "app") -> argparse.Namespace:
    return argparse.Namespace(
        workspace_root=workspace, owner_unit="atlas", lane_name=name, type="feature",
        repos=repos, branch="app=main", source="test", default_commands=[], bind=str(bind),
    )


def _two_repo_workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace2"
    (workspace / ".grip").mkdir(parents=True)
    (workspace / ".grip" / "workspace_spec.toml").write_text(
        '''schema_version = 1
workspace_name = "m0"

[[repos]]
name = "app"
path = "repos/app"
url = "https://example.invalid/app.git"

[[repos]]
name = "lib"
path = "repos/lib"
url = "https://example.invalid/lib.git"

[[units]]
name = "atlas"
path = "agents/atlas"
repos = ["app", "lib"]
'''
    )
    return workspace


def test_materialized_lane_records_lane_kind_materialized(tmp_path: Path) -> None:
    # Every lane document carries lane_kind so a reader never infers it; the
    # ordinary create path is "materialized" and owns a repos/ subdir.
    workspace = _workspace(tmp_path)
    assert lanes.create_lane(_create(workspace, "feature")) == 0
    doc = lanes.tomllib.loads(lanes.lane_file(workspace, "atlas", "feature").read_text())
    assert doc["lane_kind"] == "materialized"
    assert "bound_worktree" not in doc
    assert (lanes.lane_dir(workspace, "atlas", "feature") / "repos").is_dir()


def test_create_bound_lane_writes_bound_receipt_and_no_clone(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    wt = _real_worktree(workspace, branch="feat/bind-me")
    assert lanes.create_lane(_create_bound(workspace, "bound", wt)) == 0
    lane_dir = lanes.lane_dir(workspace, "atlas", "bound")
    doc = lanes.tomllib.loads(lanes.lane_file(workspace, "atlas", "bound").read_text())
    assert doc["lane_kind"] == "bound"
    assert doc["bound_worktree"] == str(wt.resolve())
    # branch comes from the worktree's current branch, not the --branch arg
    assert doc["branch_map"] == {"app": "feat/bind-me"}
    # a bound lane owns no clone: no repos/ subdir was created
    assert not (lane_dir / "repos").exists()
    assert (lane_dir / "context").is_dir()


def test_create_bound_lane_records_worktree_head_as_bound_head(tmp_path: Path) -> None:
    # Note 1: create records the worktree HEAD as bound_head — the drift baseline
    # a review bind on this lane re-checks against.
    workspace = _workspace(tmp_path)
    wt = _real_worktree(workspace, branch="feat/head")
    expected_head = _git(wt, "rev-parse", "HEAD").stdout.strip()
    assert lanes.create_lane(_create_bound(workspace, "bound", wt)) == 0
    doc = lanes.tomllib.loads(lanes.lane_file(workspace, "atlas", "bound").read_text())
    assert doc["bound_head"] == expected_head


def test_create_bound_lane_refuses_worktree_outside_workspace(tmp_path: Path) -> None:
    # Note 2: containment — a worktree OUTSIDE workspace_root is refused, even a
    # clean valid git checkout. The path check runs first, so the message is the
    # containment refusal, not a git-state one.
    workspace = _workspace(tmp_path)
    outside = _real_worktree(tmp_path / "elsewhere", branch="feat/outside")
    with pytest.raises(SystemExit, match="not under the workspace root"):
        lanes.create_lane(_create_bound(workspace, "bound", outside))
    assert not lanes.lane_dir(workspace, "atlas", "bound").exists()


def test_create_bound_lane_refuses_dirty_tree(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    wt = _real_worktree(workspace, branch="feat/dirty")
    (wt / "f.txt").write_text("uncommitted change\n")  # make the tree dirty (tracked)
    with pytest.raises(SystemExit, match="dirty tree"):
        lanes.create_lane(_create_bound(workspace, "bound", wt))
    # refused before any lane tree was created
    assert not lanes.lane_dir(workspace, "atlas", "bound").exists()


def test_create_bound_lane_refuses_untracked_file_as_dirty(tmp_path: Path) -> None:
    # Note 3: an UNTRACKED file (e.g. a build artifact) counts as dirty and
    # refuses the bind — otherwise the recorded head would not reconstruct the
    # bytes the author is actually sitting on.
    workspace = _workspace(tmp_path)
    wt = _real_worktree(workspace, branch="feat/untracked")
    (wt / "build.o").write_text("artifact\n")  # untracked, not staged
    with pytest.raises(SystemExit, match="dirty tree"):
        lanes.create_lane(_create_bound(workspace, "bound", wt))
    assert not lanes.lane_dir(workspace, "atlas", "bound").exists()


def test_create_bound_lane_refuses_detached_head(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    wt = _real_worktree(workspace, branch="feat/detach")
    head = _git(wt, "rev-parse", "HEAD").stdout.strip()
    _git(wt, "checkout", "-q", head)  # detach
    with pytest.raises(SystemExit, match="detached HEAD"):
        lanes.create_lane(_create_bound(workspace, "bound", wt))
    assert not lanes.lane_dir(workspace, "atlas", "bound").exists()


def test_create_bound_lane_refuses_non_git_path(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    plain = workspace / "notgit"  # under workspace so containment passes; is-git fails
    plain.mkdir()
    with pytest.raises(SystemExit, match="not a git work tree"):
        lanes.create_lane(_create_bound(workspace, "bound", plain))


def test_create_bound_lane_refuses_multi_repo(tmp_path: Path) -> None:
    workspace = _two_repo_workspace(tmp_path)
    wt = _real_worktree(workspace, branch="feat/multi")
    with pytest.raises(SystemExit, match="single-repo only"):
        lanes.create_lane(_create_bound(workspace, "bound", wt, repos="app,lib"))
    assert not lanes.lane_dir(workspace, "atlas", "bound").exists()


def test_app_lane_create_bind_skips_materialization(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # End-to-end wiring: `lane create --bind` writes a bound lane.toml AND does
    # not materialize a clone (the ~95s/1.78GB tax the ruling exists to avoid).
    workspace = _workspace(tmp_path)
    (workspace / ".grip" / "events").mkdir(parents=True, exist_ok=True)
    wt = _real_worktree(workspace, branch="feat/app-bind")
    materialized: list[str] = []
    payloads: list[dict] = []
    monkeypatch.setattr(app_module, "_materialize_lane_repos", lambda *a, **k: materialized.append("called"))
    monkeypatch.setattr(app_module, "emit_after_outcome", lambda **k: payloads.append(k["payload"]))
    app_module.lane_create(
        workspace, "atlas", "bound", repos="app", branch=None,
        lane_type="feature", source="manual", command=[], manual_hooks=False, bind=wt,
    )
    doc = lanes.tomllib.loads(lanes.lane_file(workspace, "atlas", "bound").read_text())
    assert doc["lane_kind"] == "bound"
    assert doc["bound_worktree"] == str(wt.resolve())
    assert materialized == []  # no clone was materialized for a bound lane
    # Note 5: the lane.created event payload carries lane_kind + bound_worktree,
    # so a consumer distinguishes bound from materialized without a second read.
    assert payloads and payloads[0]["lane_kind"] == "bound"
    assert payloads[0]["bound_worktree"] == str(wt.resolve())


def test_app_lane_create_materialized_event_payload_has_lane_kind(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    workspace = _workspace(tmp_path)
    (workspace / ".grip" / "events").mkdir(parents=True, exist_ok=True)
    payloads: list[dict] = []
    monkeypatch.setattr(app_module, "_materialize_lane_repos", lambda *a, **k: None)
    monkeypatch.setattr(app_module, "emit_after_outcome", lambda **k: payloads.append(k["payload"]))
    app_module.lane_create(
        workspace, "atlas", "mat", repos="app", branch="app=main",
        lane_type="feature", source="manual", command=[], manual_hooks=False, bind=None,
    )
    assert payloads and payloads[0]["lane_kind"] == "materialized"
    assert "bound_worktree" not in payloads[0]


def test_app_lane_create_requires_branch_without_bind(tmp_path: Path) -> None:
    import typer
    workspace = _workspace(tmp_path)
    with pytest.raises(typer.BadParameter, match="branch is required"):
        app_module.lane_create(
            workspace, "atlas", "m", repos="app", branch=None,
            lane_type="feature", source="manual", command=[], manual_hooks=False, bind=None,
        )


# --------------------------------------------------------------------------- #
# bind_bound_lane (verb #2): review bind on a bound lane, sourced live from the
# worktree, refusing on drift (gr2-lane-author-shape ruling)
# --------------------------------------------------------------------------- #
import json as _json


def _commit(wt: Path, fname: str, text: str, msg: str) -> str:
    (wt / fname).write_text(text)
    _git(wt, "add", ".")
    assert _git(wt, "commit", "-qm", msg).returncode == 0
    return _git(wt, "rev-parse", "HEAD").stdout.strip()


def _bound_lane(tmp_path: Path):
    """A workspace + a clean bound lane on a real worktree with two commits."""
    workspace = _workspace(tmp_path)
    wt = _real_worktree(workspace, branch="feat/bind")  # commit A on feat/bind
    base = _git(wt, "rev-parse", "HEAD").stdout.strip()
    head = _commit(wt, "g.txt", "work\n", "the reviewed change")  # commit B
    assert lanes.create_lane(_create_bound(workspace, "bound", wt)) == 0
    return workspace, wt, base, head


def test_bind_bound_lane_writes_a_bound_receipt_from_the_worktree(tmp_path: Path) -> None:
    # The test worktree has no GitHub origin, so allow_local=True is required to
    # bind a local: identity (see the allow_local witnesses below).
    workspace, wt, base, head = _bound_lane(tmp_path)
    record = lanes.bind_bound_lane(workspace, "atlas", "bound", base=base, allow_local=True)
    assert record.lane_kind == "bound"
    assert record.head == head
    assert record.base == base
    assert record.repo.startswith("local:")  # no GitHub origin -> local identity under --allow-local
    # the receipt is written into the worktree's OWN .git (same helper as materialized)
    receipt = wt / ".git" / "grip-review.json"
    assert receipt.is_file()
    data = _json.loads(receipt.read_text())
    assert data == {"repo": record.repo, "base": base, "head": head, "lane_kind": "bound"}


def test_bind_bound_lane_refuses_non_hex_base(tmp_path: Path) -> None:
    # Item 1: a base that is not a 40-hex sha never reaches the receipt.
    workspace, wt, base, head = _bound_lane(tmp_path)
    with pytest.raises(SystemExit, match="not a full 40-hex commit"):
        lanes.bind_bound_lane(workspace, "atlas", "bound", base="nonsense", allow_local=True)
    assert not (wt / ".git" / "grip-review.json").exists()


def test_bind_bound_lane_refuses_well_formed_but_nonexistent_base(tmp_path: Path) -> None:
    # Item 1: a 40-hex string that is not a commit (or not an ancestor of head) is
    # refused by the merge-base --is-ancestor check.
    workspace, wt, base, head = _bound_lane(tmp_path)
    with pytest.raises(SystemExit, match="not an ancestor"):
        lanes.bind_bound_lane(workspace, "atlas", "bound", base="f" * 40, allow_local=True)
    assert not (wt / ".git" / "grip-review.json").exists()


def test_bind_bound_lane_refuses_no_origin_without_allow_local(tmp_path: Path) -> None:
    # Item 2: default allow_local=False refuses a worktree with no GitHub origin.
    workspace, wt, base, head = _bound_lane(tmp_path)
    with pytest.raises(SystemExit, match="no portable GitHub origin"):
        lanes.bind_bound_lane(workspace, "atlas", "bound", base=base)  # allow_local defaults False
    assert not (wt / ".git" / "grip-review.json").exists()


def test_bind_bound_lane_binds_github_origin_without_allow_local(tmp_path: Path) -> None:
    # Item 2: a worktree WITH a portable GitHub origin binds to that identity even
    # with allow_local=False (the default), and the identity is the canonical one.
    workspace, wt, base, head = _bound_lane(tmp_path)
    _git(wt, "remote", "add", "origin", "git@github.com:synapt-dev/grip.git")
    record = lanes.bind_bound_lane(workspace, "atlas", "bound", base=base)  # default False
    assert record.repo == "https://github.com/synapt-dev/grip"


def test_bind_bound_lane_refuses_on_head_drift(tmp_path: Path) -> None:
    workspace, wt, base, head = _bound_lane(tmp_path)
    _commit(wt, "h.txt", "more\n", "drift commit")  # HEAD moves off the recorded head
    with pytest.raises(SystemExit, match="DRIFT"):
        lanes.bind_bound_lane(workspace, "atlas", "bound", base=base)
    # no receipt was written
    assert not (wt / ".git" / "grip-review.json").exists()


def test_bind_bound_lane_refuses_on_dirty_tree(tmp_path: Path) -> None:
    workspace, wt, base, head = _bound_lane(tmp_path)
    (wt / "g.txt").write_text("uncommitted edit\n")  # dirty, HEAD unchanged
    with pytest.raises(SystemExit, match="DRIFT"):
        lanes.bind_bound_lane(workspace, "atlas", "bound", base=base)
    assert not (wt / ".git" / "grip-review.json").exists()


def test_bind_bound_lane_refuses_a_materialized_lane(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    assert lanes.create_lane(_create(workspace, "feature")) == 0  # materialized
    with pytest.raises(SystemExit, match="is not a bound lane"):
        lanes.bind_bound_lane(workspace, "atlas", "feature", base="a" * 40)


def test_app_lane_bind_verb_is_registered_and_binds(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    # The CLI verb is runtime-registered (walk the built registry, not decorators)
    by_name = {c.name: c for c in app_module.lane_app.registered_commands}
    assert "bind" in by_name and callable(by_name["bind"].callback)
    # ...and end-to-end it writes the bound receipt from the worktree.
    workspace, wt, base, head = _bound_lane(tmp_path)
    capsys.readouterr()
    app_module.lane_bind(workspace, "atlas", "bound", base=base, allow_local=True, json_output=True)
    out = _json.loads(capsys.readouterr().out)
    assert out == {"repo": out["repo"], "base": base, "head": head, "lane_kind": "bound"}
    assert (wt / ".git" / "grip-review.json").is_file()


def test_app_lane_bind_refuses_materialized_with_exit_2(tmp_path: Path) -> None:
    import typer
    workspace = _workspace(tmp_path)
    assert lanes.create_lane(_create(workspace, "feature")) == 0
    with pytest.raises(typer.Exit) as ei:
        app_module.lane_bind(workspace, "atlas", "feature", base="a" * 40, json_output=False)
    assert ei.value.exit_code == 2
