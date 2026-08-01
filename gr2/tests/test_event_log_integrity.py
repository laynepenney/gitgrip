"""Integrity tests for concurrent event writes and prototype evidence."""

from __future__ import annotations

import importlib.util
import json
import multiprocessing
import sys
import time
from argparse import Namespace
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def _gated_emit_worker(
    source_root: str,
    workspace_root: str,
    read_reached: object,
    release_read: object,
    result_queue: object,
) -> None:
    """Pause each process after reading seq so an unlocked RMW races deterministically."""
    events_path = Path(source_root) / "gr2" / "python_cli" / "events.py"
    spec = importlib.util.spec_from_file_location("event_integrity_worker_events", events_path)
    assert spec is not None and spec.loader is not None
    events = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(events)

    original_current_seq = events._current_seq

    def gated_current_seq(outbox: Path) -> int:
        seq = original_current_seq(outbox)
        read_reached.set()
        if not release_read.wait(timeout=10):
            raise TimeoutError("parent did not release the sequence-read gate")
        return seq

    events._current_seq = gated_current_seq
    try:
        events.emit(
            event_type=events.EventType.LANE_ENTERED,
            workspace_root=Path(workspace_root),
            actor=f"worker:{multiprocessing.current_process().name}",
            owner_unit="event-stress",
            payload={"lane_name": "integrity"},
        )
    except Exception as exc:  # pragma: no cover - reported across process boundary
        result_queue.put({"ok": False, "error": repr(exc)})
    else:
        result_queue.put({"ok": True})


def _wait_until_any(events: list[object], timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if any(event.is_set() for event in events):
            return True
        time.sleep(0.005)
    return False


def test_concurrent_emit_serializes_sequence_read_and_append(tmp_path: Path) -> None:
    """Removing the write lock lets both processes allocate seq=1."""
    (tmp_path / ".grip").mkdir()
    ctx = multiprocessing.get_context("spawn")
    reached = [ctx.Event(), ctx.Event()]
    release = ctx.Event()
    results = ctx.Queue()
    processes = [
        ctx.Process(
            target=_gated_emit_worker,
            args=(
                str(Path(__file__).resolve().parents[2]),
                str(tmp_path),
                reached[index],
                release,
                results,
            ),
            name=f"emit-{index}",
        )
        for index in range(2)
    ]

    for process in processes:
        process.start()

    assert _wait_until_any(reached, timeout=10), "neither writer reached sequence allocation"
    time.sleep(0.25)
    both_read_before_release = all(event.is_set() for event in reached)
    release.set()

    for process in processes:
        process.join(timeout=10)
        assert not process.is_alive(), "event writer hung"
        assert process.exitcode == 0

    outcomes = [results.get(timeout=2) for _ in processes]
    assert outcomes == [{"ok": True}, {"ok": True}]
    assert not both_read_before_release, "sequence allocation was not serialized"

    outbox = tmp_path / ".grip" / "events" / "outbox.jsonl"
    rows = [json.loads(line) for line in outbox.read_text().splitlines()]
    assert sorted(row["seq"] for row in rows) == [1, 2]


def test_sequential_emit_control_is_strictly_monotonic(tmp_path: Path) -> None:
    """The zero-concurrency control proves the sequence detector can report clean fruit."""
    from gr2.python_cli.events import EventType, emit

    (tmp_path / ".grip").mkdir()
    for index in range(8):
        emit(
            event_type=EventType.LANE_ENTERED,
            workspace_root=tmp_path,
            actor="sequential-control",
            owner_unit="event-stress",
            payload={"index": index},
        )

    outbox = tmp_path / ".grip" / "events" / "outbox.jsonl"
    rows = [json.loads(line) for line in outbox.read_text().splitlines()]
    assert [row["seq"] for row in rows] == list(range(1, 9))


def test_repeated_stress_distinguishes_unlocked_and_locked_paths() -> None:
    """Repeated fruit must expose the old race while the locked path stays clean."""
    from gr2.prototypes.concurrent_event_stress import run_phase, sequential_control

    control = sequential_control()
    unlocked = run_phase(rounds=3, writers=2, unlocked=True)
    locked = run_phase(rounds=3, writers=2, unlocked=False)

    assert control == {
        "writes": 8,
        "strictly_monotonic": True,
        "corruption_count": 0,
    }
    assert unlocked["duplicate_seq_rounds"] == 3
    assert locked["duplicate_seq_rounds"] == 0
    assert locked["lost_event_rounds"] == 0
    assert locked["corruption_count"] == 0
    assert locked["worker_failure_rounds"] == 0


def test_cross_mode_child_failure_preserves_exit_and_output() -> None:
    """Captured child failure must be loud rather than indistinguishable from silence."""
    from gr2.prototypes.cross_mode_lane_stress import HarnessCommandError, run

    with pytest.raises(HarnessCommandError) as exc_info:
        run(
            [
                sys.executable,
                "-c",
                "import sys; print('child-out'); "
                "print('child-err', file=sys.stderr); raise SystemExit(7)",
            ],
            capture=True,
        )

    message = str(exc_info.value)
    assert "exit 7" in message
    assert "child-out" in message
    assert "child-err" in message


def test_lease_corruption_detector_has_a_positive_control() -> None:
    """A zero corruption count is proven only if known corruption is detected."""
    from gr2.prototypes.concurrent_lease_stress import prove_corruption_detector

    receipt = prove_corruption_detector()
    assert receipt == {
        "proven": True,
        "fixture": "malformed-json",
        "detected_as_corrupt": True,
    }


def test_lease_stress_report_carries_and_enforces_the_positive_control(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Deleting the control from the report or ignoring a failed control turns RED."""
    from gr2.prototypes import concurrent_lease_stress as stress

    monkeypatch.setattr(stress, "parse_args", lambda: Namespace(rounds=0, json=True))
    monkeypatch.setattr(
        stress,
        "run_phase",
        lambda disable_locking, rounds: {
            "locking": "disabled" if disable_locking else "enabled",
            "rounds": rounds,
        },
    )
    monkeypatch.setattr(
        stress,
        "prove_corruption_detector",
        lambda: {
            "proven": False,
            "fixture": "malformed-json",
            "detected_as_corrupt": False,
        },
    )

    assert stress.main() == 1
    report = json.loads(capsys.readouterr().out)
    assert report["corruption_detector_control"]["proven"] is False


def test_event_corruption_detector_has_a_positive_control() -> None:
    """The event stress report must prove its own corruption counter."""
    from gr2.prototypes.concurrent_event_stress import prove_corruption_detector

    assert prove_corruption_detector() == {
        "proven": True,
        "fixture": "malformed-json",
        "detected_count": 1,
    }
