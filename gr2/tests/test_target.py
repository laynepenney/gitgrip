"""gr2 `target`: writer for the [settings].target that prune reads.

The load-bearing cases are the PRESERVE witness (a set must not drop other spec
fields -- the reason we do NOT reuse the regenerator `_write_workspace_spec`) and
the ROUND-TRIP with prune's reader (what `target set` writes, `_configured_target`
reads). Ops tests are hermetic (a spec file, no git); the warn/no-spec cases go
through the CLI.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
import tomli_w
from typer.testing import CliRunner

from gr2.python_cli import app as app_mod
from gr2.python_cli import target as target_ops


def _write_spec(root: Path, spec: dict) -> Path:
    grip = root / ".grip"
    grip.mkdir(parents=True, exist_ok=True)
    path = grip / "workspace_spec.toml"
    path.write_text(tomli_w.dumps(spec))
    return path


def _base_spec() -> dict:
    return {
        "workspace_name": "ws",
        "repos": [{"name": "grip", "path": "repos/grip", "url": "https://example.invalid/grip.git"}],
        "units": [{"name": "u", "path": "agents/u/home", "repos": ["grip"]}],
        "settings": {"merge_method": "merge"},
    }


# --- ops round-trips ----------------------------------------------------------


def test_set_then_show_round_trips(tmp_path: Path) -> None:
    _write_spec(tmp_path, _base_spec())
    target_ops.set_target(tmp_path, "epic/x")
    assert target_ops.show_target(tmp_path) == "epic/x"


def test_set_preserves_every_other_field(tmp_path: Path) -> None:
    """The PRESERVE witness: a set must not drop merge_method, repos, units, or
    workspace_name -- the whole reason set_target round-trips instead of calling
    the regenerator _write_workspace_spec (which emits no [settings] at all)."""
    _write_spec(tmp_path, _base_spec())
    target_ops.set_target(tmp_path, "dev")

    import tomllib

    with (tmp_path / ".grip" / "workspace_spec.toml").open("rb") as fh:
        spec = tomllib.load(fh)
    assert spec["settings"]["merge_method"] == "merge"  # untouched
    assert spec["settings"]["target"] == "dev"
    assert spec["workspace_name"] == "ws"
    assert spec["repos"][0]["name"] == "grip"
    assert spec["units"][0]["name"] == "u"


def test_set_target_round_trips_with_prunes_reader(tmp_path: Path) -> None:
    """What `target set` writes, prune's `_configured_target` reads."""
    _write_spec(tmp_path, _base_spec())
    target_ops.set_target(tmp_path, "epic/x")
    assert app_mod._configured_target(tmp_path) == "epic/x"


def test_unset_removes_only_target(tmp_path: Path) -> None:
    _write_spec(tmp_path, _base_spec())
    target_ops.set_target(tmp_path, "epic/x")
    assert target_ops.unset_target(tmp_path) is True
    assert target_ops.show_target(tmp_path) is None
    assert app_mod._configured_target(tmp_path) is None

    import tomllib

    with (tmp_path / ".grip" / "workspace_spec.toml").open("rb") as fh:
        spec = tomllib.load(fh)
    assert spec["settings"]["merge_method"] == "merge"  # survived the unset


def test_unset_when_absent_is_a_no_op(tmp_path: Path) -> None:
    _write_spec(tmp_path, _base_spec())  # no target set
    assert target_ops.unset_target(tmp_path) is False


def test_show_is_none_when_unset(tmp_path: Path) -> None:
    _write_spec(tmp_path, _base_spec())
    assert target_ops.show_target(tmp_path) is None


def test_set_empty_branch_refuses(tmp_path: Path) -> None:
    _write_spec(tmp_path, _base_spec())
    with pytest.raises(target_ops.TargetError):
        target_ops.set_target(tmp_path, "")


def test_missing_spec_raises(tmp_path: Path) -> None:
    with pytest.raises(target_ops.TargetError):
        target_ops.show_target(tmp_path)  # no .grip/workspace_spec.toml


def test_write_is_atomic_no_temp_left_behind(tmp_path: Path) -> None:
    _write_spec(tmp_path, _base_spec())
    target_ops.set_target(tmp_path, "epic/x")
    leftovers = list((tmp_path / ".grip").glob(".workspace_spec.*"))
    assert leftovers == []  # temp file was replaced, none stranded


def test_toml_hostile_branch_name_round_trips(tmp_path: Path) -> None:
    """A branch name with TOML-special characters survives via the serializer,
    no hand-escaping."""
    _write_spec(tmp_path, _base_spec())
    weird = 'feat/with "quote" and \\ backslash'
    target_ops.set_target(tmp_path, weird)
    assert target_ops.show_target(tmp_path) == weird


# --- CLI: warn on absent ref, no-spec exit ------------------------------------

runner = CliRunner()


def _all_output(result: object) -> str:
    """stdout plus stderr, whichever the click version separates them into."""
    text = getattr(result, "output", "") or ""
    try:
        text += getattr(result, "stderr", "") or ""
    except ValueError:
        pass  # stderr not separately captured on this click version
    return text


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, text=True, capture_output=True, check=True
    ).stdout.strip()


def _git_repo_in(root: Path) -> Path:
    repo = root / "repos" / "grip"
    repo.mkdir(parents=True)
    _git(repo, "init", "-q", "-b", "dev")
    _git(repo, "config", "user.email", "t@example.invalid")
    _git(repo, "config", "user.name", "t")
    (repo / "f.txt").write_text("x\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "base")
    return repo


def test_cli_set_warns_when_ref_absent_but_still_writes(tmp_path: Path) -> None:
    _write_spec(tmp_path, _base_spec())
    repo = _git_repo_in(tmp_path)  # no origin/epic/x tracking ref
    result = runner.invoke(
        app_mod.app, ["target", "set", "epic/x", "--repo-path", str(repo)]
    )
    assert result.exit_code == 0
    assert "warning:" in result.stdout and "origin/epic/x not found" in result.stdout
    assert target_ops.show_target(tmp_path) == "epic/x"  # stored despite the warning


def test_cli_set_does_not_warn_when_ref_present(tmp_path: Path) -> None:
    _write_spec(tmp_path, _base_spec())
    repo = _git_repo_in(tmp_path)
    _git(repo, "update-ref", "refs/remotes/origin/epic/x", _git(repo, "rev-parse", "HEAD"))
    result = runner.invoke(
        app_mod.app, ["target", "set", "epic/x", "--repo-path", str(repo)]
    )
    assert result.exit_code == 0
    assert "warning:" not in result.stdout
    assert target_ops.show_target(tmp_path) == "epic/x"


def test_cli_no_workspace_spec_exits_1(tmp_path: Path) -> None:
    bare = tmp_path / "nowhere"
    bare.mkdir()
    result = runner.invoke(app_mod.app, ["target", "show", "--repo-path", str(bare)])
    assert result.exit_code == 1
    assert "no gr2 workspace spec" in _all_output(result)


def test_cli_show_prints_unset(tmp_path: Path) -> None:
    _write_spec(tmp_path, _base_spec())
    result = runner.invoke(app_mod.app, ["target", "show", "--repo-path", str(tmp_path)])
    assert result.exit_code == 0
    assert result.stdout.strip() == "unset"
