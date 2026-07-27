"""Tests for gr2 apply convergence (grip#539).

Tests that build_plan() detects missing repo checkouts inside existing units
and that apply_plan() converges them idempotently.

Acceptance criteria:
- Planning emits an operation when declared unit repos are absent even if
  unit.toml and unit path exist
- Apply clones/converges the missing nested repos idempotently
- Regression test covers the scenario
"""
from __future__ import annotations

import json
import textwrap
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock, call

from gr2.python_cli.spec_apply import (
    build_plan,
    apply_plan,
    render_unit_toml,
    workspace_spec_path,
    repo_cache_path,
)


def _fake_clone_repo(url, target_repo_root, *, reference_repo_root=None):
    """Stand-in for gitops.clone_repo that actually creates a directory.

    _clone_isolated clones into a sibling staging path and then
    staging.rename(dest)'s it into place -- a bare `return_value=True` mock
    leaves nothing on disk for that rename to find. This creates just
    enough (a directory + a .git marker) for the atomic-publish step to
    succeed; _validate_clone_isolation is mocked separately in these tests
    since real git-state validation is covered by test_materialization_plan.py.
    """
    target_repo_root.mkdir(parents=True, exist_ok=True)
    (target_repo_root / ".git").mkdir(exist_ok=True)
    return True


class ConvergenceTestBase(unittest.TestCase):
    """Base class that creates a minimal workspace with unit metadata."""

    def setUp(self):
        import tempfile
        self.tmp = tempfile.mkdtemp()
        self.workspace = Path(self.tmp)

        grip_dir = self.workspace / ".grip"
        grip_dir.mkdir(parents=True)

        self.repo_specs = [
            {"name": "repo-a", "path": "repos/repo-a", "url": "https://example.com/repo-a.git"},
            {"name": "repo-b", "path": "repos/repo-b", "url": "https://example.com/repo-b.git"},
        ]

        self.unit_spec = {
            "name": "test-unit",
            "path": "agents/test-unit",
            "repos": ["repo-a", "repo-b"],
        }

        self._write_spec(self.repo_specs, [self.unit_spec])

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write_spec(self, repos, units):
        lines = ['workspace_name = "test-workspace"', ""]
        for repo in repos:
            lines.extend([
                "[[repos]]",
                f'name = "{repo["name"]}"',
                f'path = "{repo["path"]}"',
                f'url = "{repo["url"]}"',
                "",
            ])
        for unit in units:
            repos_str = "[" + ", ".join(f'"{r}"' for r in unit["repos"]) + "]"
            lines.extend([
                "[[units]]",
                f'name = "{unit["name"]}"',
                f'path = "{unit["path"]}"',
                f"repos = {repos_str}",
                "",
            ])
        workspace_spec_path(self.workspace).write_text("\n".join(lines))

    def _create_unit_on_disk(self, unit, *, with_repos=None):
        """Create unit dir + unit.toml, optionally with repo checkout dirs."""
        unit_root = self.workspace / unit["path"]
        unit_root.mkdir(parents=True, exist_ok=True)
        (unit_root / "unit.toml").write_text(render_unit_toml(unit))
        if with_repos:
            for repo_name in with_repos:
                repo_dir = unit_root / repo_name
                repo_dir.mkdir(parents=True, exist_ok=True)
                (repo_dir / ".git").mkdir()

    def _create_workspace_repo(self, repo):
        """Create a fake workspace-level repo directory."""
        path = self.workspace / repo["path"]
        path.mkdir(parents=True, exist_ok=True)
        (path / ".git").mkdir()

    def _create_repo_cache(self, repo_name):
        """Create a fake bare repo cache directory."""
        cache = repo_cache_path(self.workspace, repo_name)
        cache.mkdir(parents=True, exist_ok=True)

    def _fully_materialize(self):
        """Set up workspace as if initial apply completed: repos, caches, unit with checkouts."""
        for repo in self.repo_specs:
            self._create_workspace_repo(repo)
            self._create_repo_cache(repo["name"])
        self._create_unit_on_disk(self.unit_spec, with_repos=["repo-a", "repo-b"])


class TestBuildPlanConvergence(ConvergenceTestBase):
    """Tests that build_plan detects missing repo checkouts inside existing units."""

    @patch("gr2.python_cli.spec_apply.load_repo_hooks", return_value=None)
    @patch("gr2.python_cli.spec_apply.is_git_dir", return_value=True)
    @patch("gr2.python_cli.spec_apply.is_git_repo", return_value=True)
    def test_detects_missing_unit_repo_checkouts(self, _repo, _dir, _hooks):
        """Unit dir + unit.toml exist but repos inside unit missing -> converge_unit_repos."""
        for repo in self.repo_specs:
            self._create_workspace_repo(repo)
            self._create_repo_cache(repo["name"])
        self._create_unit_on_disk(self.unit_spec, with_repos=[])

        _, operations = build_plan(self.workspace)

        converge_ops = [op for op in operations if op.kind == "converge_unit_repos"]
        self.assertEqual(len(converge_ops), 1)
        self.assertEqual(converge_ops[0].subject, "test-unit")
        self.assertIn("repo-a", converge_ops[0].details["missing_repos"])
        self.assertIn("repo-b", converge_ops[0].details["missing_repos"])

    @patch("gr2.python_cli.spec_apply.load_repo_hooks", return_value=None)
    @patch("gr2.python_cli.spec_apply.is_git_dir", return_value=True)
    @patch("gr2.python_cli.spec_apply.is_git_repo", return_value=True)
    def test_detects_partial_missing_repos(self, _repo, _dir, _hooks):
        """Only some repos missing inside unit -> converge lists only the missing ones."""
        for repo in self.repo_specs:
            self._create_workspace_repo(repo)
            self._create_repo_cache(repo["name"])
        self._create_unit_on_disk(self.unit_spec, with_repos=["repo-a"])

        _, operations = build_plan(self.workspace)

        converge_ops = [op for op in operations if op.kind == "converge_unit_repos"]
        self.assertEqual(len(converge_ops), 1)
        self.assertEqual(converge_ops[0].details["missing_repos"], ["repo-b"])

    @patch("gr2.python_cli.spec_apply.load_repo_hooks", return_value=None)
    @patch("gr2.python_cli.spec_apply.is_git_dir", return_value=True)
    @patch("gr2.python_cli.spec_apply.is_git_repo", return_value=True)
    def test_fully_materialized_still_schedules_validation_but_nothing_missing(self, _repo, _dir, _hooks):
        """Round 2 (Atlas/Sentinel P1): converge_unit_repos is now scheduled
        whenever a unit has ANY declared repos, not only when build_plan's
        cheap existence check finds something missing -- that's what makes
        apply-time's real _clone_isolated validation (origin/isolation)
        actually run on every pass, not just the first one. All repos
        present still schedules the op (for validation), but its own
        details correctly report nothing missing."""
        self._fully_materialize()

        _, operations = build_plan(self.workspace)

        converge_ops = [op for op in operations if op.kind == "converge_unit_repos"]
        self.assertEqual(len(converge_ops), 1)
        self.assertEqual(converge_ops[0].details["missing_repos"], [])
        self.assertEqual(len(operations), 1)

    @patch("gr2.python_cli.spec_apply.load_repo_hooks", return_value=None)
    @patch("gr2.python_cli.spec_apply.is_git_dir", return_value=True)
    @patch("gr2.python_cli.spec_apply.is_git_repo", return_value=True)
    def test_new_unit_also_converges_repos_in_first_pass(self, _repo, _dir, _hooks):
        """grip#539: a brand-new unit (no dir, no toml) must schedule its repo
        checkouts in the SAME planning pass as create_unit_root/write_unit_metadata,
        not require a second apply to notice they're missing."""
        for repo in self.repo_specs:
            self._create_workspace_repo(repo)
            self._create_repo_cache(repo["name"])

        _, operations = build_plan(self.workspace)

        kinds = [op.kind for op in operations]
        self.assertIn("create_unit_root", kinds)
        self.assertIn("write_unit_metadata", kinds)
        self.assertIn("converge_unit_repos", kinds)
        converge_ops = [op for op in operations if op.kind == "converge_unit_repos"]
        self.assertEqual(len(converge_ops), 1)
        self.assertEqual(set(converge_ops[0].details["missing_repos"]), {"repo-a", "repo-b"})

    @patch("gr2.python_cli.spec_apply.load_repo_hooks", return_value=None)
    @patch("gr2.python_cli.spec_apply.is_git_dir", return_value=True)
    @patch("gr2.python_cli.spec_apply.is_git_repo", return_value=True)
    def test_stale_unit_toml_triggers_converge(self, _repo, _dir, _hooks):
        """Unit.toml lists fewer repos than spec -> converge for the new repo."""
        for repo in self.repo_specs:
            self._create_workspace_repo(repo)
            self._create_repo_cache(repo["name"])
        stale_unit = {**self.unit_spec, "repos": ["repo-a"]}
        self._create_unit_on_disk(stale_unit, with_repos=["repo-a"])

        _, operations = build_plan(self.workspace)

        converge_ops = [op for op in operations if op.kind == "converge_unit_repos"]
        self.assertEqual(len(converge_ops), 1)
        self.assertEqual(converge_ops[0].details["missing_repos"], ["repo-b"])


class TestApplyConvergence(ConvergenceTestBase):
    """Tests that apply_plan handles converge_unit_repos correctly."""

    @patch("gr2.python_cli.spec_apply._validate_clone_isolation")
    @patch("gr2.python_cli.spec_apply.run_lifecycle_stage")
    @patch("gr2.python_cli.spec_apply.apply_file_projections", return_value=[])
    @patch("gr2.python_cli.spec_apply.load_repo_hooks", return_value=None)
    @patch("gr2.python_cli.spec_apply.is_git_dir", return_value=True)
    @patch("gr2.python_cli.spec_apply.is_git_repo", return_value=True)
    @patch("gr2.python_cli.spec_apply.clone_repo", side_effect=_fake_clone_repo)
    def test_apply_clones_missing_repos_into_unit(self, mock_clone, _repo, _dir, _hooks, _proj, _lc, _isolation):
        """Apply should clone missing repos into the unit directory.

        _validate_clone_isolation is mocked here (not just clone_repo):
        this test's job is orchestration (does apply_plan call clone for the
        right repos at the right paths), not real git state -- that's
        covered by test_materialization_plan.py's dedicated validation
        tests, which use real git repos throughout, not mocks.
        """
        for repo in self.repo_specs:
            self._create_workspace_repo(repo)
            self._create_repo_cache(repo["name"])
        self._create_unit_on_disk(self.unit_spec, with_repos=[])

        result = apply_plan(self.workspace, yes=True)

        self.assertGreater(result["operation_count"], 0)
        # _clone_isolated clones into a sibling staging path and atomically
        # renames it into place (config#491 §8.3) -- clone_repo's own call
        # args now legitimately show that staging path, not the final
        # destination, so this checks the real observable outcome instead
        # of an internal-implementation-detail mock argument.
        unit_root = self.workspace / "agents" / "test-unit"
        self.assertTrue((unit_root / "repo-a" / ".git").exists())
        self.assertTrue((unit_root / "repo-b" / ".git").exists())
        cloned_names = set()
        for args, _kwargs in mock_clone.call_args_list:
            basename = Path(args[1]).name
            cloned_names.add(basename.split(".staging-")[0].lstrip("."))
        self.assertEqual(cloned_names, {"repo-a", "repo-b"})

    @patch("gr2.python_cli.spec_apply._validate_clone_isolation")
    @patch("gr2.python_cli.spec_apply.run_lifecycle_stage")
    @patch("gr2.python_cli.spec_apply.apply_file_projections", return_value=[])
    @patch("gr2.python_cli.spec_apply.load_repo_hooks", return_value=None)
    @patch("gr2.python_cli.spec_apply.is_git_dir", return_value=True)
    @patch("gr2.python_cli.spec_apply.is_git_repo", return_value=True)
    @patch("gr2.python_cli.spec_apply.clone_repo", side_effect=_fake_clone_repo)
    def test_apply_updates_stale_unit_toml(self, _clone, _repo, _dir, _hooks, _proj, _lc, _isolation):
        """After convergence, unit.toml should reflect the full spec repo list."""
        for repo in self.repo_specs:
            self._create_workspace_repo(repo)
            self._create_repo_cache(repo["name"])
        stale_unit = {**self.unit_spec, "repos": ["repo-a"]}
        self._create_unit_on_disk(stale_unit, with_repos=["repo-a"])

        apply_plan(self.workspace, yes=True)

        unit_toml = self.workspace / "agents" / "test-unit" / "unit.toml"
        content = unit_toml.read_text()
        self.assertIn("repo-a", content)
        self.assertIn("repo-b", content)

    @patch("gr2.python_cli.spec_apply.run_lifecycle_stage")
    @patch("gr2.python_cli.spec_apply.apply_file_projections", return_value=[])
    @patch("gr2.python_cli.spec_apply.load_repo_hooks", return_value=None)
    @patch("gr2.python_cli.spec_apply.is_git_dir", return_value=True)
    @patch("gr2.python_cli.spec_apply.is_git_repo", return_value=True)
    @patch("gr2.python_cli.spec_apply.clone_repo", side_effect=_fake_clone_repo)
    def test_convergence_is_idempotent(self, mock_clone, _repo, _dir, _hooks, _proj, _lc):
        """After apply, a second build_plan schedules validation (round 2:
        always scheduled when a unit has declared repos -- see
        test_fully_materialized_still_schedules_validation_but_nothing_missing)
        but performs no NEW clone work: idempotence means zero mutation on
        a rerun, not zero operations scheduled."""
        self._fully_materialize()

        _, operations = build_plan(self.workspace)

        self.assertEqual(len(operations), 1)
        self.assertEqual(operations[0].kind, "converge_unit_repos")
        self.assertEqual(operations[0].details["missing_repos"], [])
        mock_clone.assert_not_called()

    @patch("gr2.python_cli.spec_apply._validate_clone_isolation")
    @patch("gr2.python_cli.spec_apply.run_lifecycle_stage")
    @patch("gr2.python_cli.spec_apply.apply_file_projections", return_value=[])
    @patch("gr2.python_cli.spec_apply.load_repo_hooks", return_value=None)
    @patch("gr2.python_cli.spec_apply.is_git_dir", return_value=True)
    @patch("gr2.python_cli.spec_apply.is_git_repo", return_value=True)
    @patch("gr2.python_cli.spec_apply.clone_repo", side_effect=_fake_clone_repo)
    def test_apply_reports_converged_repos(self, _clone, _repo, _dir, _hooks, _proj, _lc, _isolation):
        """Apply result should list what was converged."""
        for repo in self.repo_specs:
            self._create_workspace_repo(repo)
            self._create_repo_cache(repo["name"])
        self._create_unit_on_disk(self.unit_spec, with_repos=[])

        result = apply_plan(self.workspace, yes=True)

        converge_actions = [a for a in result["applied"] if "converge" in a.lower()]
        self.assertGreater(len(converge_actions), 0)


if __name__ == "__main__":
    unittest.main()
