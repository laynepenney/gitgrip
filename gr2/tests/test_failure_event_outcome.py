from __future__ import annotations

from pathlib import Path

from gr2.python_cli import events
from gr2.python_cli.events import EventEmitError
from gr2.python_cli.failures import resolve_failure_marker, write_failure_marker


def test_sink_failure_cannot_restore_a_resolved_failure_marker(tmp_path: Path, monkeypatch) -> None:
    marker = write_failure_marker(
        tmp_path,
        operation="lane.enter",
        stage="on_enter",
        hook_name="check",
        repo="app",
        owner_unit="atlas",
        lane_name="feat/test",
    )
    monkeypatch.setattr(
        events,
        "emit",
        lambda **_kwargs: (_ for _ in ()).throw(EventEmitError("sink unavailable")),
    )

    result = resolve_failure_marker(
        tmp_path,
        operation_id=str(marker["operation_id"]),
        resolved_by="agent:atlas",
        resolution="retry",
        owner_unit="atlas",
    )

    assert result["operation_id"] == marker["operation_id"]
    marker_path = tmp_path / ".grip" / "state" / "failures" / f"{marker['operation_id']}.json"
    assert not marker_path.exists()
