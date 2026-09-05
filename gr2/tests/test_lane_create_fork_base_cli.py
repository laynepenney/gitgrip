"""The CLI `lane create` records a fork base, so `review create-project` works for a
stranger.

`create_lane` records only the fork base the caller supplies (the fork-base ruling:
record, do not derive). The CLI `lane create` clones each repo AFTER the doc is
written, so nothing supplied a fork base and every CLI-created lane had none — which
made `review create-project` refuse with "no recorded fork base" for anyone who did
not set it by hand (Fathom, driving the R2 producer verb from help text). The CLI now
records the materialization point (the branch each repo forked from and the sha it
started at) after cloning. These tests drive the real CLI, not create_lane directly.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from typer.testing import CliRunner

from gr2.prototypes import lane_workspace_prototype as lanes
from gr2.python_cli import app as gr2_app
from gr2.python_cli import grip

runner = CliRunner()


def _git(cwd: Path, *a: str) -> str:
    return subprocess.run(["git", *a], cwd=cwd, text=True, capture_output=True, check=True).stdout.strip()


def _source_repo(tmp_path: Path, ws: Path, name: str) -> tuple[str, str]:
    """A source checkout at ws/repos/<name> whose origin is a local bare repo (a
    cloneable, filesystem-identity source — the materialize path clones the origin).
    Returns (bare_url, main_sha)."""
    origin = tmp_path / f"{name}.git"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    src = ws / "repos" / name
    src.parent.mkdir(parents=True, exist_ok=True)
    _git(tmp_path, "clone", "-q", str(origin), str(src))
    _git(src, "config", "user.email", "t@e.invalid")
    _git(src, "config", "user.name", "t")
    (src / "f.txt").write_text("base\n")
    _git(src, "add", ".")
    _git(src, "commit", "-q", "-m", "base")
    _git(src, "push", "-q", "origin", "main")
    return str(origin), _git(src, "rev-parse", "HEAD")


def _workspace(tmp_path: Path, repos: list[str]) -> tuple[Path, dict[str, str]]:
    ws = tmp_path / "ws"
    (ws / ".grip").mkdir(parents=True)
    # the grip object store (create-project writes the review-kind commit here)
    _git(ws / ".grip", "init", "-q", "-b", "main")
    _git(ws / ".grip", "config", "user.email", "g@e.invalid")
    _git(ws / ".grip", "config", "user.name", "g")
    _git(ws / ".grip", "commit", "-q", "--allow-empty", "-m", "init grip")
    tips: dict[str, str] = {}
    urls: dict[str, str] = {}
    for r in repos:
        urls[r], tips[r] = _source_repo(tmp_path, ws, r)
    blocks = "".join(
        f'\n[[repos]]\nname = "{r}"\npath = "repos/{r}"\nurl = "{urls[r]}"\n'
        for r in repos
    )
    (ws / ".grip" / "workspace_spec.toml").write_text(
        f'schema_version = 1\nworkspace_name = "m"\n{blocks}\n'
        f'[[units]]\nname = "atlas"\npath = "agents/atlas"\nrepos = {repos!r}\n'.replace("'", '"')
    )
    return ws, tips


def test_cli_lane_create_records_fork_base_for_each_repo(tmp_path: Path) -> None:
    ws, tips = _workspace(tmp_path, ["app", "lib"])
    res = runner.invoke(gr2_app.app, ["lane", "create", str(ws), "atlas", "feature",
                                      "--repos", "app,lib", "--branch", "main"])
    assert res.exit_code == 0, res.output
    doc = lanes.load_lane_doc(ws, "atlas", "feature")
    assert "fork_base" in doc, "CLI-created lane must record a fork base"
    for r in ("app", "lib"):
        assert doc["fork_base"][r]["branch"] == "main"
        assert doc["fork_base"][r]["sha"] == tips[r]  # the materialization point


def test_cli_created_lane_then_create_project_succeeds(tmp_path: Path) -> None:
    # The stranger path end to end: create a lane through the CLI, then the R2 producer
    # verb pins base..head instead of refusing on a missing fork base.
    ws, _ = _workspace(tmp_path, ["app", "lib"])
    assert runner.invoke(gr2_app.app, ["lane", "create", str(ws), "atlas", "feature",
                                       "--repos", "app,lib", "--branch", "main"]).exit_code == 0
    res = runner.invoke(gr2_app.app, ["review", "create-project", str(ws), "atlas", "feature"])
    assert res.exit_code == 0, res.output
    sha = next(l for l in res.output.splitlines() if l.startswith("gr:"))[3:].strip()
    rows = {r["key"]: r for r in grip.read_project_review_commit(ws, sha)}
    assert set(rows) == {"app", "lib"}
