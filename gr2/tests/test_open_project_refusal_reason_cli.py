"""A refusal a stranger cannot read is the worst exit point.

`review open-project` printed `status=refused ... review_root=None` on its
default (non-JSON) output and put the ACTUAL reason only under `--json`. A
reviewer following the happy path saw a refusal with no cause and had to know
to re-run with --json. The reason must be on the default output.
"""
from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from gr2.python_cli import app as gr2_app
from gr2.python_cli import project_review

runner = CliRunner()


def _refused(monkeypatch, reason: str) -> None:
    outcome = project_review.ProjectReviewOutcome(
        "refused",
        "a" * 40,
        (),
        (project_review.ProjectReviewFailure("recall", reason),),
        None,
        False,
    )
    # Intercept the underlying review call so no real workspace is needed.
    from gr2.python_cli import open_gr_review
    monkeypatch.setattr(open_gr_review, "open_gr_enter", lambda *a, **k: outcome)


def test_open_project_refusal_prints_reason_on_default_output(tmp_path: Path, monkeypatch) -> None:
    reason = "selected source identity mismatch: source 'X', pin 'local:Y'"
    _refused(monkeypatch, reason)
    result = runner.invoke(
        gr2_app.app,
        ["review", "open-project", str(tmp_path), "gr:" + "a" * 40, "default", "lane", "--enter", "--allow-local"],
    )
    assert result.exit_code == 1, result.output
    assert reason in result.output, f"refusal reason absent from default output:\n{result.output}"


def test_open_project_refusal_reason_still_in_json(tmp_path: Path, monkeypatch) -> None:
    # Control: --json keeps carrying the reason (the fix must not move it OUT of json).
    reason = "selected source identity mismatch: source 'X', pin 'local:Y'"
    _refused(monkeypatch, reason)
    result = runner.invoke(
        gr2_app.app,
        ["review", "open-project", str(tmp_path), "gr:" + "a" * 40, "default", "lane", "--enter", "--allow-local", "--json"],
    )
    assert result.exit_code == 1, result.output
    assert reason in result.output
