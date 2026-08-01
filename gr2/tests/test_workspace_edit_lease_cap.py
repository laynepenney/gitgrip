"""Contract for the workspace-wide edit-lease cap."""

from __future__ import annotations


def test_concurrent_workspace_cap_has_sequential_and_unlocked_controls() -> None:
    """A per-lane lock cannot protect a workspace-global cap."""
    from gr2.prototypes.concurrent_workspace_cap_stress import run_phase, sequential_control

    sequential = sequential_control()
    unlocked = run_phase(rounds=3, disable_locking=True)
    locked = run_phase(rounds=3, disable_locking=False)

    assert sequential == {
        "returncodes": [0, 1],
        "active_edit_count": 1,
        "cap_violation": False,
    }
    assert unlocked["cap_violation_rounds"] == 3
    assert unlocked["worker_failure_rounds"] == 0
    assert locked["cap_violation_rounds"] == 0
    assert locked["worker_failure_rounds"] == 0


def test_cross_mode_cap_verdict_names_its_sequential_axis() -> None:
    from gr2.prototypes.cross_mode_lane_stress import scenario_global_edit_lease_cap

    assert "sequential" in scenario_global_edit_lease_cap.__doc__.lower()
