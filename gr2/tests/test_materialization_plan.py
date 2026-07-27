"""Tests for apply_materialization_plan (config#491 §6.2, §12.1, S4).

Consumes the neutral MaterializationPlan JSON schema directly (clone/venv/
editable_install/project_file operations) rather than workspace_spec.toml's
repo/unit model. Identity-free by construction: gr2 never reads an agent
name, org, role, or channel out of a plan, recursively -- not just at the
top level of each operation.

Sentinel r2 on PR#797 (2026-07-27) found five contract survivors in the
first pass: two parallel executors instead of one shared one (P1),
non-atomic clone publication (P2), incomplete clone/cache validation (P3),
too-loose project_file source containment (P4, refined from Stromus's r1),
and non-closed plan/receipt semantics (P5). Each finding gets its own test
class below, named for what it proves, not just what it covers.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from gr2.python_cli.spec_apply import (
    MaterializationPlanError,
    apply_materialization_plan,
    apply_plan,
    workspace_spec_path,
)


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=False)


class MaterializationPlanTestBase(unittest.TestCase):
    def setUp(self):
        import tempfile

        self.tmp = Path(tempfile.mkdtemp())
        self.workspace_root = self.tmp / "workspace"
        self.workspace_root.mkdir(parents=True)

    def tearDown(self):
        import shutil

        shutil.rmtree(self.tmp, ignore_errors=True)

    def _plan(self, operations: list[dict[str, object]], **overrides: object) -> dict[str, object]:
        plan: dict[str, object] = {
            "schema_version": 1,
            "plan_id": "mp_test",
            "unit_key": "u_test",
            "workspace_spec_sha256": "a" * 64,
            "operations": operations,
        }
        plan.update(overrides)
        return plan

    def _stage_source(self, name: str, content: bytes) -> str:
        """Stage a project_file source under .grip/staging/inputs/, matching
        config#491 §6.2's normative contract (Sentinel r2 P4) -- not an
        arbitrary workspace-relative path, and never outside the workspace."""
        relative = f".grip/staging/inputs/{name}"
        path = self.workspace_root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return relative

    def _init_bare_remote(self, name: str) -> str:
        """Create a real local bare repo with one commit; return its URL."""
        bare = self.tmp / f"{name}.git"
        _git(self.tmp, "init", "--bare", "--initial-branch=main", str(bare))
        work = self.tmp / f"{name}-seed"
        work.mkdir()
        _git(work, "init", "--initial-branch=main")
        _git(work, "config", "user.email", "test@example.com")
        _git(work, "config", "user.name", "Test")
        (work / "README.md").write_text(f"# {name}\n")
        _git(work, "add", ".")
        _git(work, "commit", "-m", "initial")
        _git(work, "remote", "add", "origin", str(bare))
        _git(work, "push", "origin", "main")
        return str(bare)


class TestPathSafety(MaterializationPlanTestBase):
    def test_clone_rejects_absolute_dest_path(self):
        plan = self._plan(
            [{"kind": "clone", "repo_url": "https://example.com/x.git", "dest_path": "/etc/passwd"}]
        )
        with self.assertRaises(MaterializationPlanError):
            apply_materialization_plan(self.workspace_root, plan, yes=True)

    def test_clone_rejects_dest_path_escaping_via_dotdot(self):
        plan = self._plan(
            [
                {
                    "kind": "clone",
                    "repo_url": "https://example.com/x.git",
                    "dest_path": "units/u1/../../../outside",
                }
            ]
        )
        with self.assertRaises(MaterializationPlanError):
            apply_materialization_plan(self.workspace_root, plan, yes=True)

    def test_clone_rejects_reference_base_escaping_workspace(self):
        """Sentinel r2 P3.1: reference_base was accepted as an absolute
        external path and passed straight to --reference-if-able, becoming
        its own 'approved' alternate. Must be containment-checked the same
        as dest_path.

        Round 2 catch (Sentinel, on my OWN test): this used repo_url =
        "https://example.com/x.git" -- a fake URL. Removing the
        reference_base containment check entirely still left this test
        GREEN, because the clone then failed later for an unrelated reason
        (DNS/network) and got converted to the same MaterializationPlanError
        the test asserts on. A real, working URL is required so the test's
        outcome is genuinely tied to the containment check, not a downstream
        failure that happens to raise the same exception type -- the exact
        class of mistake I'd already caught myself making once this session
        (the dotdot source_path test) and repeated here without noticing."""
        url = self._init_bare_remote("product")
        outside_cache = self.tmp / "outside.git"
        outside_cache.mkdir()
        plan = self._plan(
            [
                {
                    "kind": "clone",
                    "repo_url": url,
                    "dest_path": "units/u1/product",
                    "reference_base": str(outside_cache),
                }
            ]
        )
        with self.assertRaises(MaterializationPlanError):
            apply_materialization_plan(self.workspace_root, plan, yes=True)
        # If containment were broken, this would have cloned for real.
        self.assertFalse((self.workspace_root / "units" / "u1" / "product").exists())

    def test_project_file_rejects_absolute_dest_path(self):
        source_rel = self._stage_source("f_01", b"hello")
        plan = self._plan(
            [
                {
                    "kind": "project_file",
                    "source_path": source_rel,
                    "source_sha256": hashlib.sha256(b"hello").hexdigest(),
                    "dest_path": "/tmp/escape.md",
                    "mode": "copy",
                }
            ]
        )
        with self.assertRaises(MaterializationPlanError):
            apply_materialization_plan(self.workspace_root, plan, yes=True)

    def test_project_file_rejects_absolute_source_path(self):
        """Original Stromus r1 finding: source_path was read+deleted with
        zero containment check, unlike dest_path."""
        outside_source = self.tmp / "outside-workspace.md"
        outside_source.write_bytes(b"hello")
        plan = self._plan(
            [
                {
                    "kind": "project_file",
                    "source_path": str(outside_source),
                    "source_sha256": hashlib.sha256(b"hello").hexdigest(),
                    "dest_path": "units/u1/home/AGENTS.md",
                    "mode": "copy",
                }
            ]
        )
        with self.assertRaises(MaterializationPlanError):
            apply_materialization_plan(self.workspace_root, plan, yes=True)
        self.assertTrue(outside_source.exists())

    def test_project_file_rejects_source_path_escaping_via_dotdot(self):
        outside_source = self.tmp / "outside-workspace.md"
        outside_source.write_bytes(b"hello")
        plan = self._plan(
            [
                {
                    "kind": "project_file",
                    "source_path": f"../{outside_source.name}",
                    "source_sha256": hashlib.sha256(b"hello").hexdigest(),
                    "dest_path": "units/u1/home/AGENTS.md",
                    "mode": "copy",
                }
            ]
        )
        with self.assertRaises(MaterializationPlanError):
            apply_materialization_plan(self.workspace_root, plan, yes=True)
        self.assertTrue(outside_source.exists())

    def test_project_file_rejects_source_inside_workspace_but_outside_staging(self):
        """Sentinel r2 P4: workspace-relative is not sufficient by itself --
        source_path must resolve under .grip/staging/inputs/ specifically."""
        misplaced = self.workspace_root / "units" / "u1" / "not-staged.md"
        misplaced.parent.mkdir(parents=True)
        misplaced.write_bytes(b"hello")
        plan = self._plan(
            [
                {
                    "kind": "project_file",
                    "source_path": "units/u1/not-staged.md",
                    "source_sha256": hashlib.sha256(b"hello").hexdigest(),
                    "dest_path": "units/u1/home/AGENTS.md",
                    "mode": "copy",
                }
            ]
        )
        with self.assertRaises(MaterializationPlanError):
            apply_materialization_plan(self.workspace_root, plan, yes=True)
        self.assertTrue(misplaced.exists())

    def test_project_file_rejects_mode_other_than_copy(self):
        source_rel = self._stage_source("f_01", b"hello")
        plan = self._plan(
            [
                {
                    "kind": "project_file",
                    "source_path": source_rel,
                    "source_sha256": hashlib.sha256(b"hello").hexdigest(),
                    "dest_path": "units/u1/home/AGENTS.md",
                    "mode": "move",
                }
            ]
        )
        with self.assertRaises(MaterializationPlanError):
            apply_materialization_plan(self.workspace_root, plan, yes=True)

    def test_project_file_rejects_symlink_escape_inside_staging(self):
        """Round 2 (Sentinel): a symlink planted INSIDE .grip/staging/inputs/
        pointing outside the workspace -- a lexical staging-prefix check on
        the string alone would miss this; must actually resolve the
        filesystem path (following the symlink) and check containment of
        where it REALLY points, not just where its name lexically sits."""
        outside_target = self.tmp / "secret.txt"
        outside_target.write_bytes(b"secret content")
        staging_dir = self.workspace_root / ".grip" / "staging" / "inputs"
        staging_dir.mkdir(parents=True, exist_ok=True)
        symlink_path = staging_dir / "evil-link"
        symlink_path.symlink_to(outside_target)

        plan = self._plan(
            [
                {
                    "kind": "project_file",
                    "source_path": ".grip/staging/inputs/evil-link",
                    "source_sha256": hashlib.sha256(b"secret content").hexdigest(),
                    "dest_path": "units/u1/home/AGENTS.md",
                    "mode": "copy",
                }
            ]
        )
        with self.assertRaises(MaterializationPlanError):
            apply_materialization_plan(self.workspace_root, plan, yes=True)
        self.assertFalse((self.workspace_root / "units" / "u1" / "home" / "AGENTS.md").exists())


class TestIdentityFreedom(MaterializationPlanTestBase):
    def test_rejects_operation_with_top_level_identity_field(self):
        plan = self._plan(
            [
                {
                    "kind": "clone",
                    "repo_url": "https://example.com/x.git",
                    "dest_path": "units/u1/repo",
                    "agent_name": "apollo",
                }
            ]
        )
        with self.assertRaises(MaterializationPlanError):
            apply_materialization_plan(self.workspace_root, plan, yes=True)

    def test_rejects_operation_with_nested_identity_field(self):
        """Sentinel r2 P5: nested identity smuggling (e.g. metadata.channel)
        must be caught too -- not just a flat top-level key scan."""
        plan = self._plan(
            [
                {
                    "kind": "clone",
                    "repo_url": "https://example.com/x.git",
                    "dest_path": "units/u1/repo",
                    "metadata": {"channel": "dev"},
                }
            ]
        )
        with self.assertRaises(MaterializationPlanError):
            apply_materialization_plan(self.workspace_root, plan, yes=True)


class TestPlanShapeValidation(MaterializationPlanTestBase):
    """Sentinel r2 P5: the whole plan is validated before any operation
    executes -- an invalid operation later in the list must not let an
    earlier, valid-looking operation mutate anything first."""

    def test_missing_unit_key_rejected(self):
        plan = {
            "schema_version": 1,
            "plan_id": "mp_test",
            "operations": [
                {"kind": "clone", "repo_url": "https://example.com/x.git", "dest_path": "units/u1/repo"}
            ],
        }
        with self.assertRaises(MaterializationPlanError):
            apply_materialization_plan(self.workspace_root, plan, yes=True)

    def test_unsafe_plan_id_rejected(self):
        plan = self._plan(
            [{"kind": "clone", "repo_url": "https://example.com/x.git", "dest_path": "units/u1/repo"}],
            plan_id="../../../../escaped_receipt",
        )
        with self.assertRaises(MaterializationPlanError):
            apply_materialization_plan(self.workspace_root, plan, yes=True)

    def test_duplicate_dest_path_rejected(self):
        plan = self._plan(
            [
                {"kind": "venv", "dest_path": "units/u1/.venv", "engine": "uv", "python": ">=3.11"},
                {"kind": "clone", "repo_url": "https://example.com/x.git", "dest_path": "units/u1/.venv"},
            ]
        )
        with self.assertRaises(MaterializationPlanError):
            apply_materialization_plan(self.workspace_root, plan, yes=True)

    def test_late_invalid_operation_leaves_earlier_operation_untouched(self):
        """Exact Sentinel reproduction: op1 (venv) must not persist any
        mutation when op2's dest_path is invalid -- validation covers the
        whole plan before execution starts, not op-by-op interleaved."""
        plan = self._plan(
            [
                {"kind": "venv", "dest_path": "units/u1/.venv", "engine": "uv", "python": ">=3.11"},
                {"kind": "clone", "repo_url": "https://example.com/x.git", "dest_path": "/etc/passwd"},
            ]
        )
        with self.assertRaises(MaterializationPlanError):
            apply_materialization_plan(self.workspace_root, plan, yes=True)
        self.assertFalse((self.workspace_root / "units" / "u1" / ".venv").exists())

    def test_bad_engine_rejected(self):
        plan = self._plan(
            [{"kind": "venv", "dest_path": "units/u1/.venv", "engine": "conda", "python": ">=3.11"}]
        )
        with self.assertRaises(MaterializationPlanError):
            apply_materialization_plan(self.workspace_root, plan, yes=True)

    def test_rejects_unknown_top_level_field(self):
        plan = self._plan(
            [{"kind": "venv", "dest_path": "units/u1/.venv", "engine": "uv", "python": ">=3.11"}],
            org="synapt",
        )
        with self.assertRaises(MaterializationPlanError):
            apply_materialization_plan(self.workspace_root, plan, yes=True)

    def test_rejects_wrong_schema_version(self):
        plan = self._plan(
            [{"kind": "venv", "dest_path": "units/u1/.venv", "engine": "uv", "python": ">=3.11"}],
            schema_version=999,
        )
        with self.assertRaises(MaterializationPlanError):
            apply_materialization_plan(self.workspace_root, plan, yes=True)

    def test_rejects_unknown_operation_field(self):
        """Round 2 (Atlas/Sentinel): a blacklist only catches enumerated
        field names -- metadata.display_name="Apollo" was accepted because
        display_name was never on the forbidden-keys list. An ALLOWLIST
        rejects any field not explicitly permitted for that operation kind,
        by construction, regardless of what the field is named."""
        plan = self._plan(
            [
                {
                    "kind": "venv",
                    "dest_path": "units/u1/.venv",
                    "engine": "uv",
                    "python": ">=3.11",
                    "metadata": {"display_name": "Apollo"},
                }
            ]
        )
        with self.assertRaises(MaterializationPlanError):
            apply_materialization_plan(self.workspace_root, plan, yes=True)
        self.assertFalse((self.workspace_root / "units" / "u1" / ".venv").exists())

    def test_rejects_dot_normalized_duplicate_dest_path(self):
        """Round 2 (Sentinel): raw-string duplicate checking accepted
        "units/u1/.venv" and "units/u1/./.venv" as different destinations,
        even though they're the same real path -- op1 created the venv,
        then op2 failed for an unrelated reason, violating
        validate-before-touch in practice even though the code claims it.
        Canonical (resolved) comparison must catch this before either runs."""
        plan = self._plan(
            [
                {"kind": "venv", "dest_path": "units/u1/.venv", "engine": "uv", "python": ">=3.11"},
                {"kind": "clone", "repo_url": "https://example.com/x.git", "dest_path": "units/u1/./.venv"},
            ]
        )
        with self.assertRaises(MaterializationPlanError):
            apply_materialization_plan(self.workspace_root, plan, yes=True)
        self.assertFalse((self.workspace_root / "units" / "u1" / ".venv").exists())

    def test_rejects_forged_pyvenv_cfg_without_interpreter(self):
        """Round 2 (Sentinel): a directory containing only a forged
        pyvenv.cfg, with no actual interpreter binary, was accepted as a
        valid existing venv under python=">=99" -- an impossible
        constraint, which is exactly why this needed a real check rather
        than trusting the marker file's mere presence."""
        fake = self.workspace_root / "units" / "u1" / ".venv"
        fake.mkdir(parents=True)
        (fake / "pyvenv.cfg").write_text("home = /nonexistent\nversion = 3.99.0\n")

        plan = self._plan([{"kind": "venv", "dest_path": "units/u1/.venv", "engine": "uv", "python": ">=99"}])
        with self.assertRaises(MaterializationPlanError):
            apply_materialization_plan(self.workspace_root, plan, yes=True)

    def test_clone_evidence_includes_origin_and_cache(self):
        """config#491 §12.1: clone results must record observed origin and
        approved-alternate/cache evidence, not just repo_url/dest_path."""
        url = self._init_bare_remote("product")
        cache_dir = self.workspace_root / ".grip" / "cache" / "repos" / "product.git"
        cache_dir.parent.mkdir(parents=True, exist_ok=True)
        _git(self.workspace_root, "clone", "--mirror", url, str(cache_dir))
        plan = self._plan(
            [
                {
                    "kind": "clone",
                    "repo_url": url,
                    "dest_path": "units/u1/product",
                    "reference_base": ".grip/cache/repos/product.git",
                }
            ]
        )
        result = apply_materialization_plan(self.workspace_root, plan, yes=True)
        op_result = result["operations"][0]
        self.assertEqual(op_result["observed_origin"], url)
        self.assertTrue(op_result["alternate_approved"])
        self.assertEqual(op_result["cache_path"], ".grip/cache/repos/product.git")

    def test_venv_evidence_includes_interpreter(self):
        """config#491 §12.1: venv results must record the interpreter, not
        just created=True/False."""
        plan = self._plan(
            [{"kind": "venv", "dest_path": "units/u1/.venv", "engine": "uv", "python": ">=3.11"}]
        )
        result = apply_materialization_plan(self.workspace_root, plan, yes=True)
        self.assertIn("interpreter_path", result["operations"][0])
        self.assertTrue(result["operations"][0]["interpreter_path"])

    def test_receipt_publish_atomicity_proven_by_failed_rename(self):
        """Round 2 (Sentinel): a test asserting only "no temp file left
        behind" doesn't distinguish atomic-via-rename from a direct write --
        a direct write also trivially leaves no temp file. This makes the
        rename step itself fail and confirms no final receipt.json ever
        appears, proving the publish mechanism is genuinely rename-based."""
        url = self._init_bare_remote("product")
        plan = self._plan(
            [{"kind": "clone", "repo_url": url, "dest_path": "units/u1/product"}],
            plan_id="mp_atomic_proof",
        )

        original_rename = Path.rename

        def selective_fail_rename(self_path, target):
            if "materialization" in str(self_path) and ".tmp-" in str(self_path):
                raise OSError("simulated rename failure")
            return original_rename(self_path, target)

        with patch.object(Path, "rename", selective_fail_rename):
            with self.assertRaises(OSError):
                apply_materialization_plan(self.workspace_root, plan, yes=True)

        receipt_path = self.workspace_root / ".grip" / "state" / "materialization" / "mp_atomic_proof.json"
        self.assertFalse(receipt_path.exists())


class TestSharedExecutor(MaterializationPlanTestBase):
    """Sentinel r2 P1: sharing only clone_repo() as a leaf primitive does
    not satisfy "one executor, not a second materializer." Proof: the
    legacy workspace_spec.toml path must reject the exact same isolation
    violations the MaterializationPlan path rejects, because both now
    delegate to the same _clone_isolated function."""

    def test_legacy_converge_unit_repos_rejects_existing_repo_with_mismatched_origin(self):
        """Proof that apply_plan's converge_unit_repos now validates ALL a
        unit's declared repos (not just build_plan's cheap "missing" list)
        by delegating to the same _clone_isolated function the
        MaterializationPlan path uses. A unit with two declared repos, one
        genuinely absent (so build_plan schedules convergence at all -- its
        own existence pre-check is deliberately unchanged, doing real git
        validation on every plan-build would be a real cost) and one
        present with the wrong origin, must still fail on the second."""
        unit_root = self.workspace_root / "agents" / "atlas" / "home"
        unit_root.mkdir(parents=True)
        (unit_root / "unit.toml").write_text(
            'name = "atlas"\nkind = "unit"\nrepos = ["present-app", "missing-app"]\n'
        )

        present_repo_root = unit_root / "present-app"
        actual_origin_url = self._init_bare_remote("actual-present-app")
        _git(unit_root, "clone", actual_origin_url, str(present_repo_root))
        declared_url_for_present = self._init_bare_remote("declared-present-app")
        missing_app_url = self._init_bare_remote("missing-app")

        spec_path = workspace_spec_path(self.workspace_root)
        spec_path.parent.mkdir(parents=True, exist_ok=True)
        spec_path.write_text(
            '\n'.join(
                [
                    'workspace_name = "test"',
                    "",
                    "[[repos]]",
                    'name = "present-app"',
                    'path = "repos/present-app"',
                    f'url = "{declared_url_for_present}"',
                    "",
                    "[[repos]]",
                    'name = "missing-app"',
                    'path = "repos/missing-app"',
                    f'url = "{missing_app_url}"',
                    "",
                    "[[units]]",
                    'name = "atlas"',
                    'path = "agents/atlas/home"',
                    'repos = ["present-app", "missing-app"]',
                    "",
                ]
            )
        )
        with self.assertRaises(MaterializationPlanError):
            apply_plan(self.workspace_root, yes=True)

    def test_all_present_unit_repo_with_wrong_origin_still_caught(self):
        """Round 2 (Atlas/Sentinel), exact reproduction: the original P1
        fix proved "all declared repos validated" only via a scenario with
        a second, genuinely-missing repo to trigger scheduling at all --
        that's a scenario-specific fix, not a clause-complete one. This
        proves the actual clause: a SINGLE declared repo, fully PRESENT,
        with the wrong origin, must still be caught. build_plan now
        schedules converge_unit_repos whenever a unit has ANY declared
        repos, not only when something is missing."""
        unit_root = self.workspace_root / "agents" / "atlas" / "home"
        unit_root.mkdir(parents=True)
        (unit_root / "unit.toml").write_text('name = "atlas"\nkind = "unit"\nrepos = ["app"]\n')

        present_repo_root = unit_root / "app"
        actual_origin_url = self._init_bare_remote("actual-app")
        _git(unit_root, "clone", actual_origin_url, str(present_repo_root))
        declared_url = self._init_bare_remote("declared-app")

        spec_path = workspace_spec_path(self.workspace_root)
        spec_path.parent.mkdir(parents=True, exist_ok=True)
        spec_path.write_text(
            '\n'.join(
                [
                    'workspace_name = "test"',
                    "",
                    "[[repos]]",
                    'name = "app"',
                    'path = "repos/app"',
                    f'url = "{declared_url}"',
                    "",
                    "[[units]]",
                    'name = "atlas"',
                    'path = "agents/atlas/home"',
                    'repos = ["app"]',
                    "",
                ]
            )
        )
        with self.assertRaises(MaterializationPlanError):
            apply_plan(self.workspace_root, yes=True)


class TestCloneOperation(MaterializationPlanTestBase):
    def test_clones_to_explicit_dest_path(self):
        """gap#4: uses the declared dest_path directly, not a repo-name-derived path."""
        url = self._init_bare_remote("product")
        plan = self._plan(
            [{"kind": "clone", "repo_url": url, "dest_path": "units/u_7f3a/home/product"}]
        )
        result = apply_materialization_plan(self.workspace_root, plan, yes=True)
        dest = self.workspace_root / "units" / "u_7f3a" / "home" / "product"
        self.assertTrue((dest / "README.md").exists())
        self.assertTrue((dest / ".git").is_dir())
        self.assertEqual(result["operation_count"], 1)

    def test_clone_uses_reference_base_as_alternate(self):
        url = self._init_bare_remote("product")
        cache_dir = self.workspace_root / ".grip" / "cache" / "repos" / "product.git"
        cache_dir.parent.mkdir(parents=True, exist_ok=True)
        _git(self.workspace_root, "clone", "--mirror", url, str(cache_dir))

        plan = self._plan(
            [
                {
                    "kind": "clone",
                    "repo_url": url,
                    "dest_path": "units/u1/product",
                    "reference_base": ".grip/cache/repos/product.git",
                }
            ]
        )
        apply_materialization_plan(self.workspace_root, plan, yes=True)
        dest = self.workspace_root / "units" / "u1" / "product"
        alternates = dest / ".git" / "objects" / "info" / "alternates"
        self.assertTrue(alternates.exists())

    def test_clone_rejects_in_workspace_cache_outside_declared_namespace(self):
        """Sentinel r2 P3.1: a real, working in-workspace mirror was
        accepted as reference_base and retained as the clone's alternate,
        even though config#491 §8.2 confines this to
        .grip/cache/repos/<declared-repo>.git specifically -- containment
        alone (is it inside the workspace at all) isn't the actual rule."""
        url = self._init_bare_remote("product")
        rogue_cache = self.workspace_root / "units" / "u1" / "rogue-cache.git"
        rogue_cache.parent.mkdir(parents=True)
        _git(self.workspace_root, "clone", "--mirror", url, str(rogue_cache))

        plan = self._plan(
            [
                {
                    "kind": "clone",
                    "repo_url": url,
                    "dest_path": "units/u1/product",
                    "reference_base": "units/u1/rogue-cache.git",
                }
            ]
        )
        with self.assertRaises(MaterializationPlanError):
            apply_materialization_plan(self.workspace_root, plan, yes=True)
        self.assertFalse((self.workspace_root / "units" / "u1" / "product").exists())

    def test_clone_rejects_cache_with_wrong_canonical_origin(self):
        """Sentinel r2 P3.1: a cache backed by a DIFFERENT remote than the
        one being cloned must not be usable as reference_base, even if it
        sits at the canonically-correct namespace path."""
        url_a = self._init_bare_remote("product-a")
        url_b = self._init_bare_remote("product-b")
        cache_dir = self.workspace_root / ".grip" / "cache" / "repos" / "product-a.git"
        cache_dir.parent.mkdir(parents=True, exist_ok=True)
        _git(self.workspace_root, "clone", "--mirror", url_b, str(cache_dir))

        plan = self._plan(
            [
                {
                    "kind": "clone",
                    "repo_url": url_a,
                    "dest_path": "units/u1/product",
                    "reference_base": ".grip/cache/repos/product-a.git",
                }
            ]
        )
        with self.assertRaises(MaterializationPlanError):
            apply_materialization_plan(self.workspace_root, plan, yes=True)

    def test_clone_rejects_when_common_dir_check_cannot_run(self):
        """Round 2 (Sentinel): fail CLOSED, not open. A .git that exists as
        a real directory but isn't actually a valid git repository
        internally makes `git rev-parse --git-common-dir` fail -- the prior
        version silently skipped the whole check in that case (treated
        "cannot verify" as "assume it's fine"). Must reject instead."""
        dest = self.workspace_root / "units" / "u1" / "product"
        (dest / ".git").mkdir(parents=True)
        # .git exists as a real directory (passes the worktree-pointer-file
        # and nested-worktrees checks) but has no actual git internals, so
        # `git rev-parse --git-common-dir` run inside it fails for real.

        plan = self._plan(
            [{"kind": "clone", "repo_url": "https://example.com/x.git", "dest_path": "units/u1/product"}]
        )
        with self.assertRaises(MaterializationPlanError):
            apply_materialization_plan(self.workspace_root, plan, yes=True)

    def test_clone_is_idempotent_for_existing_healthy_clone(self):
        url = self._init_bare_remote("product")
        plan = self._plan([{"kind": "clone", "repo_url": url, "dest_path": "units/u1/product"}])
        apply_materialization_plan(self.workspace_root, plan, yes=True)
        second = apply_materialization_plan(self.workspace_root, plan, yes=True)
        self.assertFalse(second["operations"][0]["first_materialize"])

    def test_clone_rejects_worktree_linked_git_dir(self):
        """config#491 §8.1: .git as a worktree pointer file is forbidden."""
        dest = self.workspace_root / "units" / "u1" / "product"
        dest.mkdir(parents=True)
        (dest / ".git").write_text("gitdir: /somewhere/else/.git/worktrees/product\n")

        plan = self._plan(
            [{"kind": "clone", "repo_url": "https://example.com/x.git", "dest_path": "units/u1/product"}]
        )
        with self.assertRaises(MaterializationPlanError):
            apply_materialization_plan(self.workspace_root, plan, yes=True)

    def test_clone_rejects_existing_clone_with_nested_worktrees(self):
        """Sentinel r2 P3.3: a real .git directory that is itself hosting
        linked worktrees (.git/worktrees present) must be rejected -- it is
        not an isolated single clone."""
        url = self._init_bare_remote("product")
        dest = self.workspace_root / "units" / "u1" / "product"
        dest.parent.mkdir(parents=True)
        _git(self.workspace_root, "clone", url, str(dest))
        (dest / ".git" / "worktrees").mkdir()

        plan = self._plan([{"kind": "clone", "repo_url": url, "dest_path": "units/u1/product"}])
        with self.assertRaises(MaterializationPlanError):
            apply_materialization_plan(self.workspace_root, plan, yes=True)

    def test_clone_rejects_existing_clone_with_mismatched_origin(self):
        """Sentinel r2 P3.2: an existing clone whose actual origin is
        remote A must not be silently accepted under a plan declaring
        remote B."""
        url_a = self._init_bare_remote("product-a")
        url_b = self._init_bare_remote("product-b")
        dest = self.workspace_root / "units" / "u1" / "product"
        dest.parent.mkdir(parents=True)
        _git(self.workspace_root, "clone", url_a, str(dest))

        plan = self._plan([{"kind": "clone", "repo_url": url_b, "dest_path": "units/u1/product"}])
        with self.assertRaises(MaterializationPlanError):
            apply_materialization_plan(self.workspace_root, plan, yes=True)

    def test_clone_publication_is_atomic_on_checkout_failure(self):
        """Sentinel r2 P2, exact reproduction: a valid remote with a
        nonexistent branch must leave NOTHING at dest_path -- not a
        partially-published clone on the wrong branch."""
        url = self._init_bare_remote("product")
        plan = self._plan(
            [
                {
                    "kind": "clone",
                    "repo_url": url,
                    "dest_path": "units/u1/product",
                    "branch": "does-not-exist",
                }
            ]
        )
        with self.assertRaises(MaterializationPlanError):
            apply_materialization_plan(self.workspace_root, plan, yes=True)
        dest = self.workspace_root / "units" / "u1" / "product"
        self.assertFalse(dest.exists())
        # No stray staging directory left behind either.
        leftovers = list((self.workspace_root / "units" / "u1").glob(".product.staging-*"))
        self.assertEqual(leftovers, [])


class TestVenvOperation(MaterializationPlanTestBase):
    def test_creates_venv_via_uv(self):
        plan = self._plan(
            [{"kind": "venv", "dest_path": "units/u1/home/.venv", "engine": "uv", "python": ">=3.11"}]
        )
        apply_materialization_plan(self.workspace_root, plan, yes=True)
        venv_path = self.workspace_root / "units" / "u1" / "home" / ".venv"
        self.assertTrue((venv_path / "pyvenv.cfg").exists())

    def test_venv_idempotent_when_already_exists(self):
        plan = self._plan(
            [{"kind": "venv", "dest_path": "units/u1/home/.venv", "engine": "uv", "python": ">=3.11"}]
        )
        apply_materialization_plan(self.workspace_root, plan, yes=True)
        second = apply_materialization_plan(self.workspace_root, plan, yes=True)
        self.assertFalse(second["operations"][0]["created"])

    def test_rejects_fake_existing_venv(self):
        """Sentinel r2 P5: an arbitrary directory at dest_path must not be
        accepted as a valid venv just because something exists there."""
        fake = self.workspace_root / "units" / "u1" / "home" / ".venv"
        fake.mkdir(parents=True)
        (fake / "not-a-real-venv.txt").write_text("nope")

        plan = self._plan(
            [{"kind": "venv", "dest_path": "units/u1/home/.venv", "engine": "uv", "python": ">=99"}]
        )
        with self.assertRaises(MaterializationPlanError):
            apply_materialization_plan(self.workspace_root, plan, yes=True)


class TestEditableInstallOperation(MaterializationPlanTestBase):
    def test_installs_editable_source_via_uv(self):
        venv_path = self.workspace_root / "units" / "u1" / "home" / ".venv"
        subprocess.run(["uv", "venv", "--python", ">=3.11", str(venv_path)], check=True, capture_output=True)

        source = self.workspace_root / "units" / "u1" / "home" / "product"
        source.mkdir(parents=True)
        (source / "pyproject.toml").write_text(
            '[project]\nname = "product"\nversion = "0.1.0"\n'
            '[build-system]\nrequires = ["setuptools>=68"]\nbuild-backend = "setuptools.build_meta"\n'
        )
        (source / "product").mkdir()
        (source / "product" / "__init__.py").write_text("")

        plan = self._plan(
            [
                {
                    "kind": "editable_install",
                    "venv_path": "units/u1/home/.venv",
                    "source_path": "units/u1/home/product",
                    "extras": [],
                }
            ]
        )
        result = apply_materialization_plan(self.workspace_root, plan, yes=True)
        op_result = result["operations"][0]
        self.assertEqual(op_result["kind"], "editable_install")
        self.assertIsNotNone(op_result["pep610_evidence"])
        # config#491 §12.1 evidence: editable source path, extras, distribution.
        self.assertEqual(op_result["extras"], [])
        self.assertEqual(op_result["distribution"], "product")
        check = subprocess.run(
            [str(venv_path / "bin" / "python"), "-c", "import product"],
            capture_output=True, text=True,
        )
        self.assertEqual(check.returncode, 0, check.stderr)


class TestProjectFileOperation(MaterializationPlanTestBase):
    def test_copies_and_verifies_hash(self):
        content = b"# Foundation\nRole: neutral executor.\n"
        source_rel = self._stage_source("f_01", content)
        plan = self._plan(
            [
                {
                    "kind": "project_file",
                    "source_path": source_rel,
                    "source_sha256": hashlib.sha256(content).hexdigest(),
                    "dest_path": "units/u1/home/AGENTS.md",
                    "mode": "copy",
                }
            ]
        )
        apply_materialization_plan(self.workspace_root, plan, yes=True)
        dest = self.workspace_root / "units" / "u1" / "home" / "AGENTS.md"
        self.assertEqual(dest.read_bytes(), content)

    def test_rejects_hash_mismatch(self):
        source_rel = self._stage_source("f_01", b"real content")
        plan = self._plan(
            [
                {
                    "kind": "project_file",
                    "source_path": source_rel,
                    "source_sha256": hashlib.sha256(b"different content").hexdigest(),
                    "dest_path": "units/u1/home/AGENTS.md",
                    "mode": "copy",
                }
            ]
        )
        with self.assertRaises(MaterializationPlanError):
            apply_materialization_plan(self.workspace_root, plan, yes=True)

    def test_deletes_staging_source_after_copy(self):
        """config#491 §6.2: staging artifact is deleted after acknowledgement."""
        content = b"ephemeral"
        source_rel = self._stage_source("f_01", content)
        plan = self._plan(
            [
                {
                    "kind": "project_file",
                    "source_path": source_rel,
                    "source_sha256": hashlib.sha256(content).hexdigest(),
                    "dest_path": "units/u1/home/AGENTS.md",
                    "mode": "copy",
                }
            ]
        )
        apply_materialization_plan(self.workspace_root, plan, yes=True)
        self.assertFalse((self.workspace_root / source_rel).exists())

    def test_source_survives_receipt_write_failure(self):
        """Sentinel r2 P4, exact reproduction: faulting the receipt write
        after a valid project_file operation left source_exists=False,
        dest_exists=True, receipt_exists=False -- the staged artifact was
        deleted before durable acknowledgement (the receipt) existed. The
        source must survive when the receipt write fails."""
        content = b"important"
        source_rel = self._stage_source("f_01", content)
        plan = self._plan(
            [
                {
                    "kind": "project_file",
                    "source_path": source_rel,
                    "source_sha256": hashlib.sha256(content).hexdigest(),
                    "dest_path": "units/u1/home/AGENTS.md",
                    "mode": "copy",
                }
            ],
            plan_id="mp_receipt_fail_test",
        )

        with patch(
            "gr2.python_cli.spec_apply._write_materialization_receipt",
            side_effect=OSError("simulated disk full"),
        ):
            with self.assertRaises(OSError):
                apply_materialization_plan(self.workspace_root, plan, yes=True)

        source_exists = (self.workspace_root / source_rel).exists()
        dest_exists = (self.workspace_root / "units" / "u1" / "home" / "AGENTS.md").exists()
        receipt_exists = (
            self.workspace_root / ".grip" / "state" / "materialization" / "mp_receipt_fail_test.json"
        ).exists()
        self.assertTrue(source_exists, "source must survive an acknowledgement failure")
        self.assertTrue(dest_exists, "the copy itself is not rolled back, only the deletion is deferred")
        self.assertFalse(receipt_exists)


class TestReceipts(MaterializationPlanTestBase):
    def test_writes_structured_receipt(self):
        url = self._init_bare_remote("product")
        plan = self._plan(
            [{"kind": "clone", "repo_url": url, "dest_path": "units/u1/product"}],
            plan_id="mp_receipt_test",
            workspace_spec_sha256="abc123",
        )
        apply_materialization_plan(self.workspace_root, plan, yes=True)

        receipt_path = self.workspace_root / ".grip" / "state" / "materialization" / "mp_receipt_test.json"
        self.assertTrue(receipt_path.exists())
        receipt = json.loads(receipt_path.read_text())
        self.assertEqual(receipt["plan_id"], "mp_receipt_test")
        self.assertEqual(receipt["unit_key"], "u_test")
        self.assertIn("plan_hash", receipt)
        self.assertEqual(receipt["workspace_spec_sha256"], "abc123")
        self.assertIn("operations", receipt)
        self.assertEqual(len(receipt["operations"]), 1)

    def test_receipt_contains_no_identity_fields(self):
        """config#491 §12.1: neutral receipts carry no identity/org/channel/secret/memory."""
        url = self._init_bare_remote("product")
        plan = self._plan(
            [{"kind": "clone", "repo_url": url, "dest_path": "units/u1/product"}],
            plan_id="mp_receipt_neutrality",
        )
        apply_materialization_plan(self.workspace_root, plan, yes=True)

        receipt_path = (
            self.workspace_root / ".grip" / "state" / "materialization" / "mp_receipt_neutrality.json"
        )
        raw = receipt_path.read_text().lower()
        for forbidden in ("agent_name", "role", "org", "channel", "secret", "memory"):
            self.assertNotIn(forbidden, raw)

    def test_rerun_is_resumable_not_duplicated(self):
        """A rerun of the same plan must not re-clone or duplicate receipt entries."""
        url = self._init_bare_remote("product")
        plan = self._plan(
            [{"kind": "clone", "repo_url": url, "dest_path": "units/u1/product"}],
            plan_id="mp_resume_test",
        )
        apply_materialization_plan(self.workspace_root, plan, yes=True)
        second = apply_materialization_plan(self.workspace_root, plan, yes=True)

        receipt_path = self.workspace_root / ".grip" / "state" / "materialization" / "mp_resume_test.json"
        receipt = json.loads(receipt_path.read_text())
        self.assertEqual(len(receipt["operations"]), 1)
        self.assertFalse(second["operations"][0]["first_materialize"])

    def test_receipt_write_leaves_no_temp_file_behind(self):
        """Atomic write: temp file is renamed into place, never left dangling."""
        url = self._init_bare_remote("product")
        plan = self._plan(
            [{"kind": "clone", "repo_url": url, "dest_path": "units/u1/product"}],
            plan_id="mp_atomic_test",
        )
        apply_materialization_plan(self.workspace_root, plan, yes=True)
        state_dir = self.workspace_root / ".grip" / "state" / "materialization"
        leftovers = [p for p in state_dir.glob("*.tmp-*")]
        self.assertEqual(leftovers, [])


if __name__ == "__main__":
    unittest.main()
