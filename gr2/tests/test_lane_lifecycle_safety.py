"""M0 witnesses for lane creation, transitions, and outcome truth."""

from __future__ import annotations

import argparse
import json
import multiprocessing
from pathlib import Path

import pytest

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
