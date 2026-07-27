"""Temporary proof-of-gate smoke test -- deliberately fails, will be reverted
in the very next commit. Exists only to confirm the gr2_python CI job (and
its wiring into the `ci` aggregate) actually catches a real test failure,
not just that the job runs and exits 0 regardless of content."""


def test_ci_gate_deliberately_fails() -> None:
    assert False, "PROOF-OF-GATE: this is intentional, see grip PR#795"
