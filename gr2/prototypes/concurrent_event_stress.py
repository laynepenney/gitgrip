#!/usr/bin/env python3
"""Repeated before/after stress harness for event-log sequence integrity."""

from __future__ import annotations

import argparse
import json
import multiprocessing
import os
import sys
import tempfile
from pathlib import Path

SOURCE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE_ROOT))

from python_cli.events import EventType, emit  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rounds", type=int, default=30)
    parser.add_argument("--writers", type=int, default=2)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def _worker(
    workspace: str,
    actor: str,
    start: object,
    queue: object,
    unlocked: bool,
    expected_source_root: str,
) -> None:
    try:
        import gr2

        module_file = Path(gr2.__file__).resolve() if gr2.__file__ is not None else None
        source_root = Path(expected_source_root).resolve()
        if module_file is None or not module_file.is_relative_to(source_root):
            raise RuntimeError(
                f"spawned worker imported gr2 outside expected worktree: "
                f"module={module_file}, expected_root={source_root}"
            )
        if unlocked:
            os.environ["GR2_DISABLE_EVENT_LOCKING"] = "1"
            os.environ["GR2_EVENT_TEST_DELAY"] = "0.03"
        if not start.wait(timeout=10):
            raise TimeoutError("start gate timed out")
        emit(
            event_type=EventType.LANE_ENTERED,
            workspace_root=Path(workspace),
            actor=actor,
            owner_unit="event-stress",
            payload={"round_actor": actor},
        )
    except Exception as exc:
        queue.put({"ok": False, "error": repr(exc)})
    else:
        queue.put({"ok": True, "gr2_module": str(module_file)})


def _read_rows(outbox: Path) -> tuple[list[dict[str, object]], int]:
    rows: list[dict[str, object]] = []
    corruption_count = 0
    for line in outbox.read_text().splitlines() if outbox.exists() else []:
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            corruption_count += 1
            continue
        if not isinstance(row, dict):
            corruption_count += 1
            continue
        rows.append(row)
    return rows, corruption_count


def prove_corruption_detector() -> dict[str, object]:
    """Prove the reported zero can distinguish a known malformed event."""
    with tempfile.TemporaryDirectory(prefix="gr2-event-corruption-control-") as tmp:
        outbox = Path(tmp) / "outbox.jsonl"
        outbox.write_text("{malformed-json\n")
        _, corruption_count = _read_rows(outbox)
    return {
        "proven": corruption_count == 1,
        "fixture": "malformed-json",
        "detected_count": corruption_count,
    }


def _run_round(writers: int, unlocked: bool) -> dict[str, object]:
    ctx = multiprocessing.get_context("spawn")
    with tempfile.TemporaryDirectory(prefix="gr2-event-stress-") as tmp:
        workspace = Path(tmp)
        (workspace / ".grip").mkdir()
        start = ctx.Event()
        queue = ctx.Queue()
        processes = [
            ctx.Process(
                target=_worker,
                args=(
                    str(workspace),
                    f"writer:{index}",
                    start,
                    queue,
                    unlocked,
                    str(SOURCE_ROOT),
                ),
            )
            for index in range(writers)
        ]
        for process in processes:
            process.start()
        start.set()
        for process in processes:
            process.join(timeout=15)
        outcomes = [queue.get(timeout=2) for _ in processes]
        rows, corruption_count = _read_rows(workspace / ".grip" / "events" / "outbox.jsonl")
        seqs = [row.get("seq") for row in rows]
        return {
            "all_workers_succeeded": all(outcome["ok"] for outcome in outcomes),
            "lost_events": len(rows) != writers,
            "duplicate_seq": len(seqs) != len(set(seqs)),
            "corruption_count": corruption_count,
        }


def run_phase(*, rounds: int, writers: int, unlocked: bool) -> dict[str, object]:
    results = [_run_round(writers, unlocked) for _ in range(rounds)]
    return {
        "locking": "disabled" if unlocked else "enabled",
        "rounds": rounds,
        "writers": writers,
        "duplicate_seq_rounds": sum(bool(row["duplicate_seq"]) for row in results),
        "lost_event_rounds": sum(bool(row["lost_events"]) for row in results),
        "corruption_count": sum(int(row["corruption_count"]) for row in results),
        "worker_failure_rounds": sum(not bool(row["all_workers_succeeded"]) for row in results),
    }


def sequential_control(writes: int = 8) -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="gr2-event-sequential-control-") as tmp:
        workspace = Path(tmp)
        (workspace / ".grip").mkdir()
        old_disabled = os.environ.get("GR2_DISABLE_EVENT_LOCKING")
        old_delay = os.environ.get("GR2_EVENT_TEST_DELAY")
        os.environ["GR2_DISABLE_EVENT_LOCKING"] = "1"
        os.environ["GR2_EVENT_TEST_DELAY"] = "0"
        try:
            for index in range(writes):
                emit(
                    event_type=EventType.LANE_ENTERED,
                    workspace_root=workspace,
                    actor="sequential-control",
                    owner_unit="event-stress",
                    payload={"index": index},
                )
        finally:
            if old_disabled is None:
                os.environ.pop("GR2_DISABLE_EVENT_LOCKING", None)
            else:
                os.environ["GR2_DISABLE_EVENT_LOCKING"] = old_disabled
            if old_delay is None:
                os.environ.pop("GR2_EVENT_TEST_DELAY", None)
            else:
                os.environ["GR2_EVENT_TEST_DELAY"] = old_delay
        rows, corruption_count = _read_rows(workspace / ".grip" / "events" / "outbox.jsonl")
        seqs = [row.get("seq") for row in rows]
        return {
            "writes": writes,
            "strictly_monotonic": seqs == list(range(1, writes + 1)),
            "corruption_count": corruption_count,
        }


def main() -> int:
    args = parse_args()
    payload = {
        "corruption_detector_control": prove_corruption_detector(),
        "sequential_control": sequential_control(),
        "before_locking": run_phase(rounds=args.rounds, writers=args.writers, unlocked=True),
        "after_locking": run_phase(rounds=args.rounds, writers=args.writers, unlocked=False),
    }
    print(json.dumps(payload, indent=2))
    after = payload["after_locking"]
    return int(
        not payload["corruption_detector_control"]["proven"]
        or not payload["sequential_control"]["strictly_monotonic"]
        or after["duplicate_seq_rounds"] != 0
        or after["lost_event_rounds"] != 0
        or after["corruption_count"] != 0
        or after["worker_failure_rounds"] != 0
    )


if __name__ == "__main__":
    raise SystemExit(main())
