"""M1 local three-repository contract, deliberately landed before its service."""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

import pytest

from gr2.prototypes import lane_workspace_prototype as lanes


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, text=True, capture_output=True, check=True).stdout.strip()


def _source(root: Path, name: str) -> tuple[Path, str, str]:
    origin = root / f"{name}.git"
    _git(root, "init", "--bare", "-b", "main", str(origin))
    source = root / name
    _git(root, "clone", "-q", str(origin), str(source))
    _git(source, "config", "user.email", "m1@example.invalid")
    _git(source, "config", "user.name", "m1")
    (source / "README.md").write_text(f"{name} base\n")
    _git(source, "add", ".")
    _git(source, "commit", "-q", "-m", "base")
    _git(source, "push", "-q", "origin", "main")
    base = _git(source, "rev-parse", "main")
    branch = f"review/{name}"
    _git(source, "checkout", "-q", "-b", branch)
    (source / "review.txt").write_text(f"{name} review\n")
    _git(source, "add", ".")
    _git(source, "commit", "-q", "-m", "review")
    _git(source, "push", "-q", "origin", branch)
    head = _git(source, "rev-parse", branch)
    _git(source, "checkout", "-q", "main")
    return source, base, head


def _world(tmp_path: Path):
    workspace = tmp_path / "workspace"
    (workspace / ".grip").mkdir(parents=True)
    (workspace / ".grip" / "workspace_spec.toml").write_text('''schema_version = 1
workspace_name = "m1"

[[repos]]
name = "alpha"
path = "sources/alpha"
url = "https://example.invalid/alpha.git"

[[units]]
name = "atlas"
path = "agents/atlas"
repos = ["alpha"]
''')
    sources = {name: _source(tmp_path, name) for name in ("alpha", "beta", "gamma")}
    home = tmp_path / "home"
    _git(tmp_path, "init", "-q", str(home))
    _git(home, "config", "user.email", "m1@example.invalid")
    _git(home, "config", "user.name", "m1")
    (home / "tracked.txt").write_text("base\n")
    _git(home, "add", ".")
    _git(home, "commit", "-q", "-m", "home")
    (home / "tracked.txt").write_text("dirty\n")
    (home / "untracked.txt").write_text("keep\n")
    lanes.create_lane(argparse.Namespace(workspace_root=workspace, owner_unit="atlas", lane_name="home", type="feature", repos="alpha", branch="main", source="test", default_commands=[]))
    lanes.enter_lane(argparse.Namespace(workspace_root=workspace, owner_unit="atlas", lane_name="home", actor="agent:atlas", notify_channel=False, recall=False))
    current = lanes.current_lane_file(workspace, "atlas").read_bytes()
    return workspace, sources, home, current


def test_three_repo_contract_is_red_until_project_service_exists(tmp_path: Path) -> None:
    """Fixture checkpoint: product code must make this representative fruit real."""
    workspace, sources, home, current = _world(tmp_path)
    with pytest.raises(ModuleNotFoundError):
        from gr2.python_cli import project_review  # noqa: F401
    assert home.joinpath("tracked.txt").read_text() == "dirty\n"
    assert home.joinpath("untracked.txt").read_text() == "keep\n"
    assert lanes.current_lane_file(workspace, "atlas").read_bytes() == current
    assert [values[1:] for values in sources.values()]
