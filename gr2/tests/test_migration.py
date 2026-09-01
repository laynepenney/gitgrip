"""TDD specs for grip#563: gr1 to gr2 migration commands.

Tests the full migration flow: detect -> migrate -> validate -> apply,
plus coexistence state awareness and the workspace status command.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import subprocess
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from gr2.python_cli.app import app
from gr2.python_cli import migration
from gr2.python_cli.migration import (
    bootstrap_gr1_workspace,
    compile_gr1_to_workspace_spec,
    detect_gr1_workspace,
    migrate_gr1_workspace,
    regenerate_gr1_workspace,
    rollback_gr1_workspace,
    render_workspace_spec,
    workspace_status,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _write_gr1_workspace(root: Path) -> None:
    """Create a realistic gr1 workspace on disk."""
    gitgrip = root / ".gitgrip"
    (gitgrip / "spaces" / "main").mkdir(parents=True)
    (gitgrip / "spaces" / "main" / "gripspace.yml").write_text(
        yaml.dump({
            "version": 2,
            "manifest": {"url": "git@github.com:synapt-dev/synapt-gripspace.git"},
            "repos": {
                "grip": {
                    "url": "git@github.com:synapt-dev/grip.git",
                    "path": "./gitgrip",
                    "revision": "main",
                },
                "synapt": {
                    "url": "git@github.com:synapt-dev/synapt.git",
                    "path": "./synapt",
                    "revision": "main",
                },
                "mem0": {
                    "url": "https://github.com/mem0ai/mem0.git",
                    "path": "reference/mem0",
                    "default_branch": "main",
                    "reference": True,
                },
            },
        })
    )
    (gitgrip / "agents.toml").write_text(
        "[agents.atlas]\n"
        'worktree = "main"\n'
        'channel = "dev"\n\n'
        "[agents.apollo]\n"
        'worktree = "main"\n'
        'channel = "dev"\n'
    )
    (gitgrip / "state.json").write_text(
        json.dumps({"branchToPr": {"feat/auth": 123}})
    )
    (gitgrip / "sync-state.json").write_text(
        json.dumps({"timestamp": "2026-04-14T12:00:00Z"})
    )


@pytest.fixture
def gr1_workspace(tmp_path: Path) -> Path:
    _write_gr1_workspace(tmp_path)
    return tmp_path


# ---------------------------------------------------------------------------
# detect-gr1
# ---------------------------------------------------------------------------

class TestDetectGr1:
    def test_detects_valid_gr1_workspace(self, gr1_workspace: Path) -> None:
        result = detect_gr1_workspace(gr1_workspace)
        assert result["detected"] is True
        assert result["repo_count"] == 3
        assert set(result["agents"]) == {"apollo", "atlas"}

    def test_classifies_reference_repos(self, gr1_workspace: Path) -> None:
        result = detect_gr1_workspace(gr1_workspace)
        assert result["reference_repos"] == ["mem0"]
        assert "mem0" not in result["writable_repos"]

    def test_returns_false_for_non_gr1(self, tmp_path: Path) -> None:
        result = detect_gr1_workspace(tmp_path)
        assert result["detected"] is False

    def test_includes_state_files(self, gr1_workspace: Path) -> None:
        result = detect_gr1_workspace(gr1_workspace)
        assert "state_json" in result["state_files"]
        assert "sync_state_json" in result["state_files"]


# ---------------------------------------------------------------------------
# compile + migrate
# ---------------------------------------------------------------------------

class TestCompileGr1:
    def test_generates_spec_with_repos_and_units(self, gr1_workspace: Path) -> None:
        manifest = yaml.safe_load(
            (gr1_workspace / ".gitgrip" / "spaces" / "main" / "gripspace.yml").read_text()
        )
        import tomllib
        with (gr1_workspace / ".gitgrip" / "agents.toml").open("rb") as fh:
            agents_doc = tomllib.load(fh)
        compiled = compile_gr1_to_workspace_spec(gr1_workspace, manifest, agents_doc)
        assert len(compiled["repos"]) == 3
        assert len(compiled["units"]) == 2
        unit_names = {u["name"] for u in compiled["units"]}
        assert unit_names == {"apollo", "atlas"}

    def test_reference_repos_marked(self, gr1_workspace: Path) -> None:
        manifest = yaml.safe_load(
            (gr1_workspace / ".gitgrip" / "spaces" / "main" / "gripspace.yml").read_text()
        )
        compiled = compile_gr1_to_workspace_spec(gr1_workspace, manifest, {})
        mem0 = next(r for r in compiled["repos"] if r["name"] == "mem0")
        assert mem0.get("reference") is True

    def test_writable_repos_only_in_units(self, gr1_workspace: Path) -> None:
        manifest = yaml.safe_load(
            (gr1_workspace / ".gitgrip" / "spaces" / "main" / "gripspace.yml").read_text()
        )
        import tomllib
        with (gr1_workspace / ".gitgrip" / "agents.toml").open("rb") as fh:
            agents_doc = tomllib.load(fh)
        compiled = compile_gr1_to_workspace_spec(gr1_workspace, manifest, agents_doc)
        for unit in compiled["units"]:
            assert "mem0" not in unit["repos"]

    def test_normalizes_safe_nested_repo_path(self, gr1_workspace: Path) -> None:
        compiled = compile_gr1_to_workspace_spec(
            gr1_workspace,
            {"repos": {"safe": {"path": "./nested//safe", "url": "https://example.invalid/safe.git"}}},
            {"agents": {"atlas": {}}},
        )

        assert compiled["repos"] == [{"name": "safe", "path": "nested/safe", "url": "https://example.invalid/safe.git"}]
        assert compiled["units"][0]["path"] == "agents/atlas/home"


class TestMigrateGr1:
    def test_creates_grip_dir_and_spec(self, gr1_workspace: Path) -> None:
        result = migrate_gr1_workspace(gr1_workspace)
        assert (gr1_workspace / ".grip" / "workspace_spec.toml").exists()
        assert result["repo_count"] == 3
        assert result["unit_count"] == 2

    def test_preserves_gr1_state_snapshots(self, gr1_workspace: Path) -> None:
        result = migrate_gr1_workspace(gr1_workspace)
        migration_dir = gr1_workspace / ".grip" / "migrations" / "gr1"
        assert migration_dir.exists()
        assert (migration_dir / "state.json").exists()
        assert (migration_dir / "sync-state.json").exists()
        assert (migration_dir / "migration-summary.json").exists()

    def test_does_not_modify_gr1_manifest(self, gr1_workspace: Path) -> None:
        manifest_path = gr1_workspace / ".gitgrip" / "spaces" / "main" / "gripspace.yml"
        before = manifest_path.read_text()
        migrate_gr1_workspace(gr1_workspace)
        after = manifest_path.read_text()
        assert before == after

    def test_blocks_overwrite_without_force(self, gr1_workspace: Path) -> None:
        migrate_gr1_workspace(gr1_workspace)
        with pytest.raises(SystemExit, match="refusing to overwrite"):
            migrate_gr1_workspace(gr1_workspace)

    def test_allows_overwrite_with_force(self, gr1_workspace: Path) -> None:
        migrate_gr1_workspace(gr1_workspace)
        result = migrate_gr1_workspace(gr1_workspace, force=True)
        assert result["repo_count"] == 3

    def test_generated_spec_is_valid_toml(self, gr1_workspace: Path) -> None:
        migrate_gr1_workspace(gr1_workspace)
        spec_text = (gr1_workspace / ".grip" / "workspace_spec.toml").read_text()
        import tomllib
        parsed = tomllib.loads(spec_text)
        assert parsed["workspace_name"] == gr1_workspace.name
        assert len(parsed["repos"]) == 3
        assert len(parsed["units"]) == 2


# ---------------------------------------------------------------------------
# manifest bootstrap: compile the canonical gr1 manifest and initialize grip
# ---------------------------------------------------------------------------

class TestBootstrapGr1:
    def test_compiles_manifest_and_initializes_grip_object_store(self, gr1_workspace: Path) -> None:
        """The production bootstrap makes a usable gr2 control plane, not a hand-written spec."""
        result = bootstrap_gr1_workspace(gr1_workspace)

        assert result["status"] == "initialized"
        assert (gr1_workspace / ".grip" / ".git").is_dir()
        spec_path = gr1_workspace / ".grip" / "workspace_spec.toml"
        assert result["workspace_spec_path"] == str(spec_path)

        import tomllib
        spec = tomllib.loads(spec_path.read_text())
        assert {repo["name"] for repo in spec["repos"]} == {"grip", "synapt", "mem0"}
        assert [unit["name"] for unit in spec["units"]] == ["apollo", "atlas"]

    def test_invalid_manifest_refuses_before_creating_grip_state(self, gr1_workspace: Path) -> None:
        manifest_path = gr1_workspace / ".gitgrip" / "spaces" / "main" / "gripspace.yml"
        manifest_path.write_text("repos: [not-a-map]\n")

        with pytest.raises(SystemExit, match="repos"):
            bootstrap_gr1_workspace(gr1_workspace)

        assert not (gr1_workspace / ".grip").exists()

    @pytest.mark.parametrize(
        ("repo_name", "repo_path", "agent_name"),
        [
            ("escape", "../outside", "atlas"),
            ("escape", "/outside", "atlas"),
            ("escape", "nested/../outside", "atlas"),
            ("escape", "C:/outside", "atlas"),
            ("../repo", "safe", "atlas"),
            ("repo/child", "safe", "atlas"),
            ("escape", "safe", "../unit"),
            ("escape", "safe", "unit/child"),
            ("escape", "safe", "C:"),
        ],
    )
    def test_path_escapes_refuse_before_creating_grip_state(
        self, gr1_workspace: Path, repo_name: str, repo_path: str, agent_name: str
    ) -> None:
        manifest_path = gr1_workspace / ".gitgrip" / "spaces" / "main" / "gripspace.yml"
        manifest_path.write_text(yaml.dump({"repos": {repo_name: {"path": repo_path, "url": "https://example.invalid/escape.git"}}}))
        (gr1_workspace / ".gitgrip" / "agents.toml").write_text(f"[agents.\"{agent_name}\"]\nworktree = \"main\"\n")

        with pytest.raises(SystemExit, match="cannot compile canonical gripspace manifest"):
            bootstrap_gr1_workspace(gr1_workspace)

        assert not (gr1_workspace / ".grip").exists()

    def test_deleting_repo_path_guard_recreates_the_unsafe_store_side_effect(
        self, gr1_workspace: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Mutation control: without the source guard, valid TOML alone is unsafe."""
        manifest_path = gr1_workspace / ".gitgrip" / "spaces" / "main" / "gripspace.yml"
        manifest_path.write_text(yaml.dump({"repos": {"escape": {"path": "../outside", "url": "https://example.invalid/escape.git"}}}))
        monkeypatch.setattr(migration, "_safe_workspace_relative_path", lambda value, _field: str(value))

        bootstrap_gr1_workspace(gr1_workspace)

        assert (gr1_workspace / ".grip" / ".git").is_dir()

    def test_deleting_unit_name_guard_recreates_the_unsafe_store_side_effect(
        self, gr1_workspace: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Mutation control: unit validation protects the generated agents/<unit>/home path."""
        (gr1_workspace / ".gitgrip" / "agents.toml").write_text('[agents."../unit"]\nworktree = "main"\n')
        monkeypatch.setattr(migration, "_safe_workspace_component", lambda value, _field: str(value))

        bootstrap_gr1_workspace(gr1_workspace)

        assert (gr1_workspace / ".grip" / ".git").is_dir()

    def test_idempotent_bootstrap_preserves_compiled_bytes(self, gr1_workspace: Path) -> None:
        bootstrap_gr1_workspace(gr1_workspace)
        spec_path = gr1_workspace / ".grip" / "workspace_spec.toml"
        before = spec_path.read_bytes()

        result = bootstrap_gr1_workspace(gr1_workspace)

        assert result["status"] == "already_initialized"
        assert spec_path.read_bytes() == before

    def test_existing_empty_grip_directory_is_completed(self, gr1_workspace: Path) -> None:
        """Repair the observed partial control-plane shape without accepting corrupt git state."""
        (gr1_workspace / ".grip").mkdir()

        result = bootstrap_gr1_workspace(gr1_workspace)

        assert result["status"] == "initialized"
        assert (gr1_workspace / ".grip" / ".git").is_dir()
        assert (gr1_workspace / ".grip" / "workspace_spec.toml").is_file()

    @pytest.mark.parametrize("surface", ["grip", "git", "spec"])
    def test_symlinked_control_plane_refuses_before_external_write(
        self, gr1_workspace: Path, tmp_path: Path, surface: str
    ) -> None:
        external = tmp_path / "external"
        external.mkdir()
        grip_dir = gr1_workspace / ".grip"
        if surface == "grip":
            grip_dir.symlink_to(external, target_is_directory=True)
        elif surface == "git":
            grip_dir.mkdir()
            (grip_dir / ".git").symlink_to(external, target_is_directory=True)
        else:
            grip_dir.mkdir()
            (grip_dir / "workspace_spec.toml").symlink_to(external / "spec")

        with pytest.raises(SystemExit, match="must not be a symlink"):
            bootstrap_gr1_workspace(gr1_workspace)

        assert not (external / ".git").exists()
        assert not (external / "workspace_spec.toml").exists()

    def test_deleting_symlink_guard_recreates_external_write(
        self, gr1_workspace: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        external = tmp_path / "external"
        external.mkdir()
        (gr1_workspace / ".grip").symlink_to(external, target_is_directory=True)
        monkeypatch.setattr(migration, "_refuse_symlink", lambda _path, _label: None)

        bootstrap_gr1_workspace(gr1_workspace)

        assert (external / ".git").is_dir()
        assert (external / "workspace_spec.toml").is_file()

    def test_publish_failure_rolls_back_new_object_store(
        self, gr1_workspace: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(migration, "_atomic_write", lambda _path, _content: (_ for _ in ()).throw(OSError("injected publish failure")))

        with pytest.raises(OSError, match="injected publish failure"):
            bootstrap_gr1_workspace(gr1_workspace)

        assert not (gr1_workspace / ".grip").exists()

    def test_publish_failure_preserves_preexisting_partial_directory(
        self, gr1_workspace: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        grip_dir = gr1_workspace / ".grip"
        grip_dir.mkdir()
        monkeypatch.setattr(migration, "_atomic_write", lambda _path, _content: (_ for _ in ()).throw(OSError("injected publish failure")))

        with pytest.raises(OSError, match="injected publish failure"):
            bootstrap_gr1_workspace(gr1_workspace)

        assert grip_dir.is_dir()
        assert not (grip_dir / ".git").exists()
        assert not (grip_dir / "workspace_spec.toml").exists()

    def test_deleting_rollback_recreates_partial_object_store(
        self, gr1_workspace: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(migration, "_atomic_write", lambda _path, _content: (_ for _ in ()).throw(OSError("injected publish failure")))
        monkeypatch.setattr(migration, "_rollback_bootstrap", lambda *_args: None)

        with pytest.raises(OSError, match="injected publish failure"):
            bootstrap_gr1_workspace(gr1_workspace)

        assert (gr1_workspace / ".grip" / ".git").is_dir()

    @pytest.mark.parametrize("preexisting_grip", [False, True])
    def test_nonzero_git_init_refuses_without_spec_and_rolls_back_created_state(
        self, gr1_workspace: Path, monkeypatch: pytest.MonkeyPatch, preexisting_grip: bool
    ) -> None:
        if preexisting_grip:
            (gr1_workspace / ".grip").mkdir()
        real_git = migration.grip.git

        def fail_init(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
            if args == ("init",):
                return subprocess.CompletedProcess(["git", *args], 1, "", "injected init failure")
            return real_git(cwd, *args)

        monkeypatch.setattr(migration.grip, "git", fail_init)
        with pytest.raises(SystemExit, match="git init failed: injected init failure"):
            bootstrap_gr1_workspace(gr1_workspace)

        assert not (gr1_workspace / ".grip" / "workspace_spec.toml").exists()
        assert (gr1_workspace / ".grip").exists() is preexisting_grip
        assert not (gr1_workspace / ".grip" / ".git").exists()

    @pytest.mark.parametrize("config_key", ["user.email", "user.name"])
    @pytest.mark.parametrize("preexisting_grip", [False, True])
    def test_nonzero_git_config_refuses_and_rolls_back_new_store(
        self, gr1_workspace: Path, monkeypatch: pytest.MonkeyPatch, config_key: str, preexisting_grip: bool
    ) -> None:
        if preexisting_grip:
            (gr1_workspace / ".grip").mkdir()
        real_git = migration.grip.git

        def fail_config(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
            if args[:2] == ("config", config_key):
                return subprocess.CompletedProcess(["git", *args], 1, "", f"injected {config_key} failure")
            return real_git(cwd, *args)

        monkeypatch.setattr(migration.grip, "git", fail_config)
        with pytest.raises(SystemExit, match=f"git config {config_key} failed"):
            bootstrap_gr1_workspace(gr1_workspace)

        assert not (gr1_workspace / ".grip" / "workspace_spec.toml").exists()
        assert (gr1_workspace / ".grip").exists() is preexisting_grip
        assert not (gr1_workspace / ".grip" / ".git").exists()

    def test_deleting_git_process_guard_recreates_spec_without_store(
        self, gr1_workspace: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        real_git = migration.grip.git

        def missing_init_but_plausible_probe(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
            if args == ("init",):
                return subprocess.CompletedProcess(["git", *args], 1, "", "injected init failure")
            if args == ("rev-parse", "--is-inside-work-tree"):
                return subprocess.CompletedProcess(["git", *args], 0, "true\n", "")
            return real_git(cwd, *args)

        monkeypatch.setattr(migration.grip, "git", missing_init_but_plausible_probe)
        monkeypatch.setattr(migration.grip, "_require_git_success", lambda _proc, _action: None)

        result = bootstrap_gr1_workspace(gr1_workspace)

        assert result["status"] == "initialized"
        assert (gr1_workspace / ".grip" / "workspace_spec.toml").is_file()
        assert not (gr1_workspace / ".grip" / ".git").exists()

    def test_conflicting_existing_spec_refuses_before_initializing_store(self, gr1_workspace: Path) -> None:
        grip_dir = gr1_workspace / ".grip"
        grip_dir.mkdir()
        (grip_dir / "workspace_spec.toml").write_text('workspace_name = "not-derived"\n')

        with pytest.raises(SystemExit, match="existing generated spec differs"):
            bootstrap_gr1_workspace(gr1_workspace)

        assert not (grip_dir / ".git").exists()

    def test_invalid_existing_git_directory_refuses_without_replacing_spec(self, gr1_workspace: Path) -> None:
        grip_dir = gr1_workspace / ".grip"
        (grip_dir / ".git").mkdir(parents=True)
        manifest = yaml.safe_load(
            (gr1_workspace / ".gitgrip" / "spaces" / "main" / "gripspace.yml").read_text()
        )
        import tomllib
        with (gr1_workspace / ".gitgrip" / "agents.toml").open("rb") as fh:
            agents_doc = tomllib.load(fh)
        expected = render_workspace_spec(
            compile_gr1_to_workspace_spec(gr1_workspace, manifest, agents_doc)
        ).encode()
        (grip_dir / "workspace_spec.toml").write_bytes(expected)

        with pytest.raises(SystemExit, match="not a valid git object store"):
            bootstrap_gr1_workspace(gr1_workspace)

        assert (grip_dir / "workspace_spec.toml").read_bytes() == expected

    def test_cli_reports_the_single_bootstrap_outcome(self, gr1_workspace: Path) -> None:
        result = CliRunner().invoke(app, ["workspace", "bootstrap-gr1", str(gr1_workspace), "--json"])

        assert result.exit_code == 0, result.stdout
        payload = json.loads(result.stdout)
        assert payload["status"] == "initialized"
        assert payload["manifest_path"].endswith(".gitgrip/spaces/main/gripspace.yml")


class TestRegenerateGr1Workspace:
    """Regeneration is deliberately narrower than bootstrap and materialization."""

    def _prepared(self, workspace: Path) -> tuple[Path, str]:
        bootstrap_gr1_workspace(workspace)
        spec_path = workspace / ".grip" / "workspace_spec.toml"
        return spec_path, hashlib.sha256(spec_path.read_bytes()).hexdigest()

    def _url_only_manifest_change(self, workspace: Path) -> None:
        manifest_path = workspace / ".gitgrip" / "spaces" / "main" / "gripspace.yml"
        manifest = yaml.safe_load(manifest_path.read_text())
        manifest["repos"]["synapt"]["url"] = "git@github.com:synapt-dev/recall.git"
        manifest_path.write_text(yaml.dump(manifest))

    def test_url_only_change_replaces_only_generated_spec_and_emits_nonmaterializing_receipt(
        self, gr1_workspace: Path, tmp_path: Path
    ) -> None:
        spec_path, expected = self._prepared(gr1_workspace)
        before_git = (gr1_workspace / ".grip" / ".git").stat().st_ino
        self._url_only_manifest_change(gr1_workspace)
        receipt = tmp_path / "receipt.json"

        result = regenerate_gr1_workspace(
            gr1_workspace, expected_spec_sha256=expected, receipt_path=receipt
        )

        assert result["status"] == "regenerated"
        assert result["materialization"] is False
        assert result["expected_old_spec_sha256"] == expected
        assert result["new_spec_sha256"] != expected
        assert (gr1_workspace / ".grip" / ".git").stat().st_ino == before_git
        assert "recall.git" in spec_path.read_text()
        assert json.loads(receipt.read_text())["new_spec_sha256"] == result["new_spec_sha256"]

    def test_wrong_expected_hash_refuses_before_replacing_spec(self, gr1_workspace: Path, tmp_path: Path) -> None:
        spec_path, _ = self._prepared(gr1_workspace)
        before = spec_path.read_bytes()
        self._url_only_manifest_change(gr1_workspace)

        with pytest.raises(SystemExit, match="expected old spec hash"):
            regenerate_gr1_workspace(
                gr1_workspace, expected_spec_sha256="0" * 64, receipt_path=tmp_path / "receipt.json"
            )

        assert spec_path.read_bytes() == before
        assert not (tmp_path / "receipt.json").exists()

    def test_dirty_object_store_refuses_before_replacing_spec(self, gr1_workspace: Path, tmp_path: Path) -> None:
        spec_path, expected = self._prepared(gr1_workspace)
        before = spec_path.read_bytes()
        self._url_only_manifest_change(gr1_workspace)
        (gr1_workspace / ".grip" / "unexpected").write_text("dirty\n")

        with pytest.raises(SystemExit, match="dirty object store"):
            regenerate_gr1_workspace(
                gr1_workspace, expected_spec_sha256=expected, receipt_path=tmp_path / "receipt.json"
            )

        assert spec_path.read_bytes() == before

    def test_active_lane_and_lease_refuse_before_replacing_spec(self, gr1_workspace: Path, tmp_path: Path) -> None:
        spec_path, expected = self._prepared(gr1_workspace)
        before = spec_path.read_bytes()
        self._url_only_manifest_change(gr1_workspace)
        current = gr1_workspace / ".grip" / "state" / "current_lane" / "apollo.json"
        current.parent.mkdir(parents=True)
        current.write_text(json.dumps({"current": {"lane_name": "review"}}))

        with pytest.raises(SystemExit, match="active lanes"):
            regenerate_gr1_workspace(gr1_workspace, expected_spec_sha256=expected, receipt_path=tmp_path / "receipt.json")
        assert spec_path.read_bytes() == before

        current.write_text(json.dumps({"current": None}))
        leases = gr1_workspace / "agents" / "apollo" / "lanes" / "review" / "leases.json"
        leases.parent.mkdir(parents=True)
        leases.write_text(json.dumps([{"actor": "apollo"}]))
        with pytest.raises(SystemExit, match="active lane leases"):
            regenerate_gr1_workspace(gr1_workspace, expected_spec_sha256=expected, receipt_path=tmp_path / "receipt.json")
        assert spec_path.read_bytes() == before

    def test_atomic_publish_failure_preserves_old_spec(self, gr1_workspace: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        spec_path, expected = self._prepared(gr1_workspace)
        before = spec_path.read_bytes()
        self._url_only_manifest_change(gr1_workspace)
        monkeypatch.setattr(migration, "_atomic_write", lambda _path, _content: (_ for _ in ()).throw(OSError("injected atomic failure")))

        with pytest.raises(OSError, match="injected atomic failure"):
            regenerate_gr1_workspace(gr1_workspace, expected_spec_sha256=expected, receipt_path=tmp_path / "receipt.json")
        assert spec_path.read_bytes() == before

    def test_lock_rechecks_expected_hash_after_a_competing_writer(self, gr1_workspace: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        spec_path, expected = self._prepared(gr1_workspace)
        before = spec_path.read_bytes()
        self._url_only_manifest_change(gr1_workspace)

        @contextlib.contextmanager
        def competing_writer(_path: Path):
            spec_path.write_bytes(b"competing bytes\n")
            yield

        monkeypatch.setattr(migration.lane_proto, "exclusive_lock", competing_writer)
        with pytest.raises(SystemExit, match="expected old spec hash"):
            regenerate_gr1_workspace(gr1_workspace, expected_spec_sha256=expected, receipt_path=tmp_path / "receipt.json")
        assert spec_path.read_bytes() == b"competing bytes\n"
        assert not (tmp_path / "receipt.json").exists()

    def test_symlinked_generated_spec_refuses_without_touching_target(self, gr1_workspace: Path, tmp_path: Path) -> None:
        spec_path, expected = self._prepared(gr1_workspace)
        external = tmp_path / "external-spec"
        external.write_bytes(spec_path.read_bytes())
        spec_path.unlink()
        spec_path.symlink_to(external)
        self._url_only_manifest_change(gr1_workspace)

        with pytest.raises(SystemExit, match="must not be a symlink"):
            regenerate_gr1_workspace(gr1_workspace, expected_spec_sha256=expected, receipt_path=tmp_path / "receipt.json")
        assert external.read_bytes() != b""

    def test_cli_requires_caller_selected_receipt_for_regeneration(self, gr1_workspace: Path) -> None:
        _spec_path, expected = self._prepared(gr1_workspace)
        self._url_only_manifest_change(gr1_workspace)
        result = CliRunner().invoke(
            app,
            ["workspace", "bootstrap-gr1", str(gr1_workspace), "--regenerate", "--expected-spec-sha256", expected],
        )
        assert result.exit_code != 0
        assert "--receipt" in result.output

    def test_receipt_bound_round_trip_restores_exact_old_bytes(self, gr1_workspace: Path, tmp_path: Path) -> None:
        spec_path, expected = self._prepared(gr1_workspace)
        before = spec_path.read_bytes()
        self._url_only_manifest_change(gr1_workspace)
        forward_receipt = tmp_path / "forward.json"
        forward = regenerate_gr1_workspace(gr1_workspace, expected_spec_sha256=expected, receipt_path=forward_receipt)
        sidecar = tmp_path / json.loads(forward_receipt.read_text())["sidecar_relative_path"]
        assert sidecar.read_bytes() == before
        assert forward["sidecar_sha256"] == expected

        rollback = rollback_gr1_workspace(
            gr1_workspace,
            rollback_receipt_path=forward_receipt,
            expected_current_spec_sha256=forward["new_spec_sha256"],
            receipt_path=tmp_path / "rollback.json",
        )
        assert spec_path.read_bytes() == before
        assert rollback["status"] == "rolled_back"
        assert rollback["materialization"] is False

    def test_rollback_refuses_stale_or_tampered_authority(self, gr1_workspace: Path, tmp_path: Path) -> None:
        spec_path, expected = self._prepared(gr1_workspace)
        before = spec_path.read_bytes()
        self._url_only_manifest_change(gr1_workspace)
        forward_receipt = tmp_path / "forward.json"
        forward = regenerate_gr1_workspace(gr1_workspace, expected_spec_sha256=expected, receipt_path=forward_receipt)

        with pytest.raises(SystemExit, match="current spec hash"):
            rollback_gr1_workspace(gr1_workspace, rollback_receipt_path=forward_receipt, expected_current_spec_sha256=expected, receipt_path=tmp_path / "stale.json")
        assert spec_path.read_bytes() != before

        sidecar = tmp_path / json.loads(forward_receipt.read_text())["sidecar_relative_path"]
        sidecar.write_text("tampered\n")
        with pytest.raises(SystemExit, match="sidecar hash"):
            rollback_gr1_workspace(gr1_workspace, rollback_receipt_path=forward_receipt, expected_current_spec_sha256=forward["new_spec_sha256"], receipt_path=tmp_path / "tampered.json")

    def test_existing_receipt_and_unsafe_sidecar_path_refuse(self, gr1_workspace: Path, tmp_path: Path) -> None:
        _spec_path, expected = self._prepared(gr1_workspace)
        self._url_only_manifest_change(gr1_workspace)
        receipt = tmp_path / "forward.json"
        receipt.write_text("existing\n")
        with pytest.raises(SystemExit, match="overwrite"):
            regenerate_gr1_workspace(gr1_workspace, expected_spec_sha256=expected, receipt_path=receipt)

        receipt.write_text(json.dumps({"schema": "gr2-workspace-regeneration/v2", "workspace_root": str(gr1_workspace), "workspace_spec_path": str(gr1_workspace / ".grip" / "workspace_spec.toml"), "grip_repo_path": str(gr1_workspace / ".grip"), "manifest_sha256": hashlib.sha256((gr1_workspace / ".gitgrip" / "spaces" / "main" / "gripspace.yml").read_bytes()).hexdigest(), "object_store_head": "x", "object_store_status": [], "lane_snapshot": {"files": []}, "observed_old_spec_sha256": "0" * 64, "new_spec_sha256": "0" * 64, "sidecar_sha256": "0" * 64, "materialization": False, "sidecar_relative_path": "../escape"}))
        with pytest.raises(SystemExit, match="sidecar path is unsafe"):
            rollback_gr1_workspace(gr1_workspace, rollback_receipt_path=receipt, expected_current_spec_sha256="0" * 64, receipt_path=tmp_path / "out.json")

    def test_rollback_refuses_altered_receipt_workspace_and_symlinked_sidecar(self, gr1_workspace: Path, tmp_path: Path) -> None:
        _spec_path, expected = self._prepared(gr1_workspace)
        self._url_only_manifest_change(gr1_workspace)
        receipt = tmp_path / "forward.json"
        forward = regenerate_gr1_workspace(gr1_workspace, expected_spec_sha256=expected, receipt_path=receipt)
        doc = json.loads(receipt.read_text())
        doc["workspace_root"] = "/wrong/workspace"
        receipt.write_text(json.dumps(doc))
        with pytest.raises(SystemExit, match="workspace binding"):
            rollback_gr1_workspace(gr1_workspace, rollback_receipt_path=receipt, expected_current_spec_sha256=forward["new_spec_sha256"], receipt_path=tmp_path / "wrong-workspace.json")

        doc["workspace_root"] = str(gr1_workspace)
        receipt.write_text(json.dumps(doc))
        sidecar = tmp_path / doc["sidecar_relative_path"]
        copy = tmp_path / "sidecar-copy"
        copy.write_bytes(sidecar.read_bytes())
        sidecar.unlink()
        sidecar.symlink_to(copy)
        with pytest.raises(SystemExit, match="must not be a symlink"):
            rollback_gr1_workspace(gr1_workspace, rollback_receipt_path=receipt, expected_current_spec_sha256=forward["new_spec_sha256"], receipt_path=tmp_path / "symlink.json")


# ---------------------------------------------------------------------------
# workspace status (new command)
# ---------------------------------------------------------------------------

class TestWorkspaceStatus:
    def test_pure_gr1_workspace(self, gr1_workspace: Path) -> None:
        status = workspace_status(gr1_workspace)
        assert status["gr1"] is True
        assert status["gr2"] is False
        assert status["coexistence"] is False
        assert status["phase"] == "gr1-only"

    def test_pure_gr2_workspace(self, tmp_path: Path) -> None:
        grip = tmp_path / ".grip"
        grip.mkdir()
        (grip / "workspace_spec.toml").write_text('workspace_name = "test"\n')
        status = workspace_status(tmp_path)
        assert status["gr1"] is False
        assert status["gr2"] is True
        assert status["coexistence"] is False
        assert status["phase"] == "gr2-only"

    def test_coexistence_after_migration(self, gr1_workspace: Path) -> None:
        migrate_gr1_workspace(gr1_workspace)
        status = workspace_status(gr1_workspace)
        assert status["gr1"] is True
        assert status["gr2"] is True
        assert status["coexistence"] is True
        assert status["phase"] == "coexistence"
        assert status["migration_snapshot"] is True

    def test_no_workspace(self, tmp_path: Path) -> None:
        status = workspace_status(tmp_path)
        assert status["gr1"] is False
        assert status["gr2"] is False
        assert status["phase"] == "none"

    def test_includes_repo_counts(self, gr1_workspace: Path) -> None:
        migrate_gr1_workspace(gr1_workspace)
        status = workspace_status(gr1_workspace)
        assert status["gr1_repo_count"] == 3
        assert status["gr2_repo_count"] == 3


# ---------------------------------------------------------------------------
# End-to-end: detect -> migrate -> validate -> apply
# ---------------------------------------------------------------------------

class TestMigrationEndToEnd:
    def test_full_flow_detect_migrate_validate(self, gr1_workspace: Path) -> None:
        """The full migration path must work without errors."""
        detection = detect_gr1_workspace(gr1_workspace)
        assert detection["detected"] is True

        migration_result = migrate_gr1_workspace(gr1_workspace)
        assert migration_result["repo_count"] == 3

        status = workspace_status(gr1_workspace)
        assert status["coexistence"] is True

        spec_text = (gr1_workspace / ".grip" / "workspace_spec.toml").read_text()
        import tomllib
        spec = tomllib.loads(spec_text)
        assert spec["workspace_name"] == gr1_workspace.name
        for unit in spec["units"]:
            assert "repos" in unit
            assert len(unit["repos"]) > 0
