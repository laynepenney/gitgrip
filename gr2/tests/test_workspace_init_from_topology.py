from __future__ import annotations

import json
import tomllib
from pathlib import Path

from gr2.python_cli.app import app
from typer.testing import CliRunner

runner = CliRunner()


def _write_topology(workspace_root: Path) -> None:
    (workspace_root / "workspace.toml").write_text(
        """\
schema_version = 2
workspace_name = "declarative-team"

[[repos]]
key = "product"
url = "https://example.invalid/product.git"
path = "repos/product"
default_ref = "main"

[[repos]]
key = "config"
url = "https://example.invalid/config.git"
path = "config"
default_ref = "dev"
"""
    )


def test_workspace_init_from_topology_writes_declared_repos_in_an_empty_directory(
    tmp_path: Path,
) -> None:
    """The zero-to-team wire must not fall back to scanning local Git repos.

    Mutation: replace the declared-topology reader with `_scan_existing_repos`.
    This root has no Git repositories, so the old adoption path refuses and this
    witness goes red before a WorkspaceSpec can be written.
    """
    workspace_root = tmp_path / "empty-team"
    workspace_root.mkdir()
    _write_topology(workspace_root)

    result = runner.invoke(
        app,
        [
            "workspace",
            "init-from-topology",
            str(workspace_root),
            "--default-unit",
            "team",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["workspace_root"] == str(workspace_root)
    assert payload["spec_path"] == str(workspace_root / ".grip" / "workspace_spec.toml")
    assert payload["repo_count"] == 2
    assert [repo["name"] for repo in payload["repos"]] == ["product", "config"]
    assert [repo["path"] for repo in payload["repos"]] == ["repos/product", "config"]
    assert [repo["url"] for repo in payload["repos"]] == [
        "https://example.invalid/product.git",
        "https://example.invalid/config.git",
    ]
    assert payload["default_unit"] == "team"
    assert payload["source"] == "workspace.toml"
    assert not list(workspace_root.glob("*/.git"))
    assert not (workspace_root / "repos" / "product").exists()
    assert not (workspace_root / "config").exists()

    with (workspace_root / ".grip" / "workspace_spec.toml").open("rb") as spec_file:
        spec = tomllib.load(spec_file)
    assert spec["repos"] == payload["repos"]
    assert spec["units"] == [
        {
            "name": "team",
            "path": "agents/team/home",
            "repos": ["product", "config"],
        }
    ]

    text_result = runner.invoke(
        app,
        ["workspace", "init-from-topology", str(workspace_root), "--default-unit", "team"],
    )
    assert text_result.exit_code == 0, text_result.output
    assert "source = workspace.toml" in text_result.output


def test_workspace_init_from_topology_refuses_an_incomplete_declared_repo_before_writing(
    tmp_path: Path,
) -> None:
    workspace_root = tmp_path / "incomplete-team"
    workspace_root.mkdir()
    (workspace_root / "workspace.toml").write_text(
        """\
[[repos]]
key = "product"
path = "repos/product"
default_ref = "main"
"""
    )

    result = runner.invoke(app, ["workspace", "init-from-topology", str(workspace_root)])

    assert result.exit_code != 0
    assert "workspace.toml repos[0] ('product') is missing 'url'" in result.output
    assert not (workspace_root / ".grip" / "workspace_spec.toml").exists()


def test_workspace_init_from_topology_serializes_every_writer_value(
    tmp_path: Path,
) -> None:
    """Hostile strings must round-trip through every WorkspaceSpec value slot.

    Mutation: replace the writer serializer with raw interpolation. The command
    still exits 0, but this direct parse of its bytes fails. The witness thus
    catches the WRONG-BUT-GREEN failure mode rather than only a refusal path.
    """
    workspace_root = tmp_path / 'unsafe"team'
    workspace_root.mkdir()
    (workspace_root / "workspace.toml").write_text(
        r'''
[[repos]]
key = 'product"\\name'
url = 'https://example.invalid/a"\\b.git'
path = 'repos/product"\\path'
'''
    )

    default_unit = 'team"\\unit'
    result = runner.invoke(
        app,
        [
            "workspace",
            "init-from-topology",
            str(workspace_root),
            "--default-unit",
            default_unit,
        ],
    )

    assert result.exit_code == 0, result.output
    with (workspace_root / ".grip" / "workspace_spec.toml").open("rb") as spec_file:
        spec = tomllib.load(spec_file)
    assert spec["workspace_name"] == workspace_root.name
    assert spec["repos"] == [
        {
            "name": r'product"\\name',
            "path": r'repos/product"\\path',
            "url": r'https://example.invalid/a"\\b.git',
        }
    ]
    assert spec["units"] == [
        {
            "name": default_unit,
            "path": f"agents/{default_unit}/home",
            "repos": [r'product"\\name'],
        }
    ]
