"""Contract: ``repo status`` reads a workspace spec that ``workspace init``
actually wrote -- which has no ``schema_version``.

``workspace init`` writes ``workspace_spec.toml`` with ``workspace_name``,
``[[repos]]`` and ``[[units]]`` and **no** ``schema_version`` key. Every other
reader (``spec show``, ``spec validate``) reads that file fine, because they
use ``.get``. ``repo_maintenance.read_workspace_spec`` alone did
``raw["schema_version"]`` -> ``KeyError: 'schema_version'``, a traceback on
every valid workspace. The field is parsed strictly and then never consumed
downstream, so requiring it bought nothing and cost the whole verb.

The witness builds the workspace with the real ``workspace init`` verb, so the
spec under test is the one production writes -- not a fixture that might
disagree with it -- then invokes ``repo status`` through the CLI.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import typer
from gr2.python_cli.app import repo_app, workspace_app
from typer.testing import CliRunner

app = typer.Typer()
app.add_typer(workspace_app, name="workspace")
app.add_typer(repo_app, name="repo")
runner = CliRunner()


def _init_workspace(tmp_path: Path) -> Path:
    """A workspace whose spec is written by the real ``workspace init``."""
    repo = tmp_path / "repo-a"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "dev@layne.pro"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Layne Penney"], cwd=repo, check=True)
    (repo / "README.md").write_text("a\n")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=repo, check=True)
    result = runner.invoke(app, ["workspace", "init", str(tmp_path)])
    assert result.exit_code == 0, result.output
    spec = tmp_path / ".grip" / "workspace_spec.toml"
    assert spec.exists()
    assert "schema_version" not in spec.read_text()  # the precondition the bug needs
    return tmp_path


def test_repo_status_reads_a_spec_without_schema_version(tmp_path):
    """The production path: init a workspace, then ``repo status`` it. Before
    the fix this raised ``KeyError: 'schema_version'``."""
    ws = _init_workspace(tmp_path)
    result = runner.invoke(app, ["repo", "status", str(ws)])
    assert result.exit_code == 0, result.output
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert "KeyError" not in result.output


def test_a_spec_that_does_carry_schema_version_still_reads(tmp_path):
    """The control: the reader must not have swung to ignoring the field's
    presence. A spec that includes ``schema_version`` reads with that value."""
    from gr2.prototypes import repo_maintenance_prototype as repo_proto

    ws = _init_workspace(tmp_path)
    spec = ws / ".grip" / "workspace_spec.toml"
    spec.write_text("schema_version = 7\n" + spec.read_text())
    parsed = repo_proto.read_workspace_spec(spec)
    assert parsed.schema_version == 7
