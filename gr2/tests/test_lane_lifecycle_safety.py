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


def _real_worktree(tmp_path: Path, name: str = "wt", branch: str = "feat/x") -> Path:
    wt = tmp_path / name
    wt.mkdir()
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
    wt = _real_worktree(tmp_path, branch="feat/bind-me")
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


def test_create_bound_lane_refuses_dirty_tree(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    wt = _real_worktree(tmp_path, branch="feat/dirty")
    (wt / "f.txt").write_text("uncommitted change\n")  # make the tree dirty
    with pytest.raises(SystemExit, match="dirty tree"):
        lanes.create_lane(_create_bound(workspace, "bound", wt))
    # refused before any lane tree was created
    assert not lanes.lane_dir(workspace, "atlas", "bound").exists()


def test_create_bound_lane_refuses_detached_head(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    wt = _real_worktree(tmp_path, branch="feat/detach")
    head = _git(wt, "rev-parse", "HEAD").stdout.strip()
    _git(wt, "checkout", "-q", head)  # detach
    with pytest.raises(SystemExit, match="detached HEAD"):
        lanes.create_lane(_create_bound(workspace, "bound", wt))
    assert not lanes.lane_dir(workspace, "atlas", "bound").exists()


def test_create_bound_lane_refuses_non_git_path(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    plain = tmp_path / "notgit"
    plain.mkdir()
    with pytest.raises(SystemExit, match="not a git work tree"):
        lanes.create_lane(_create_bound(workspace, "bound", plain))


def test_create_bound_lane_refuses_multi_repo(tmp_path: Path) -> None:
    workspace = _two_repo_workspace(tmp_path)
    wt = _real_worktree(tmp_path, branch="feat/multi")
    with pytest.raises(SystemExit, match="single-repo only"):
        lanes.create_lane(_create_bound(workspace, "bound", wt, repos="app,lib"))
    assert not lanes.lane_dir(workspace, "atlas", "bound").exists()


def test_app_lane_create_bind_skips_materialization(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # End-to-end wiring: `lane create --bind` writes a bound lane.toml AND does
    # not materialize a clone (the ~95s/1.78GB tax the ruling exists to avoid).
    workspace = _workspace(tmp_path)
    (workspace / ".grip" / "events").mkdir(parents=True, exist_ok=True)
    wt = _real_worktree(tmp_path, branch="feat/app-bind")
    materialized: list[str] = []
    monkeypatch.setattr(app_module, "_materialize_lane_repos", lambda *a, **k: materialized.append("called"))
    monkeypatch.setattr(app_module, "emit_after_outcome", lambda **k: None)
    app_module.lane_create(
        workspace, "atlas", "bound", repos="app", branch=None,
        lane_type="feature", source="manual", command=[], manual_hooks=False, bind=wt,
    )
    doc = lanes.tomllib.loads(lanes.lane_file(workspace, "atlas", "bound").read_text())
    assert doc["lane_kind"] == "bound"
    assert doc["bound_worktree"] == str(wt.resolve())
    assert materialized == []  # no clone was materialized for a bound lane


def test_app_lane_create_requires_branch_without_bind(tmp_path: Path) -> None:
    import typer
    workspace = _workspace(tmp_path)
    with pytest.raises(typer.BadParameter, match="branch is required"):
        app_module.lane_create(
            workspace, "atlas", "m", repos="app", branch=None,
            lane_type="feature", source="manual", command=[], manual_hooks=False, bind=None,
        )
