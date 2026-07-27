"""Tests for apply_materialization_plan (config#491 §6.2, S4).

Consumes the neutral MaterializationPlan JSON schema directly (clone/venv/
editable_install/project_file operations) rather than workspace_spec.toml's
repo/unit model. Identity-free by construction: gr2 never reads an agent
name, org, role, or channel out of a plan.

Shares clone_repo/git primitives with the existing build_plan/apply_plan
path (config#491 §7.3: "one apply_plan executor... not a second
materializer") -- this file tests the new entry point specifically.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import unittest
from pathlib import Path

from gr2.python_cli.spec_apply import (
    MaterializationPlanError,
    apply_materialization_plan,
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
        plan = {
            "schema_version": 1,
            "plan_id": "mp_test",
            "operations": [
                {"kind": "clone", "repo_url": "https://example.com/x.git", "dest_path": "/etc/passwd"}
            ],
        }
        with self.assertRaises(MaterializationPlanError):
            apply_materialization_plan(self.workspace_root, plan, yes=True)

    def test_clone_rejects_dest_path_escaping_via_dotdot(self):
        plan = {
            "schema_version": 1,
            "plan_id": "mp_test",
            "operations": [
                {
                    "kind": "clone",
                    "repo_url": "https://example.com/x.git",
                    "dest_path": "units/u1/../../../outside",
                }
            ],
        }
        with self.assertRaises(MaterializationPlanError):
            apply_materialization_plan(self.workspace_root, plan, yes=True)

    def test_project_file_rejects_absolute_dest_path(self):
        source = self.tmp / "staged.md"
        source.write_text("hello")
        plan = {
            "schema_version": 1,
            "plan_id": "mp_test",
            "operations": [
                {
                    "kind": "project_file",
                    "source_path": str(source),
                    "source_sha256": hashlib.sha256(b"hello").hexdigest(),
                    "dest_path": "/tmp/escape.md",
                    "mode": "copy",
                }
            ],
        }
        with self.assertRaises(MaterializationPlanError):
            apply_materialization_plan(self.workspace_root, plan, yes=True)


class TestIdentityFreedom(MaterializationPlanTestBase):
    def test_rejects_operation_with_identity_bearing_field(self):
        """config#491 §6.2: the plan must not carry agent name/role/org/etc."""
        plan = {
            "schema_version": 1,
            "plan_id": "mp_test",
            "operations": [
                {
                    "kind": "clone",
                    "repo_url": "https://example.com/x.git",
                    "dest_path": "units/u1/repo",
                    "agent_name": "apollo",
                }
            ],
        }
        with self.assertRaises(MaterializationPlanError):
            apply_materialization_plan(self.workspace_root, plan, yes=True)


class TestCloneOperation(MaterializationPlanTestBase):
    def test_clones_to_explicit_dest_path(self):
        """gap#4: uses the declared dest_path directly, not a repo-name-derived path."""
        url = self._init_bare_remote("product")
        plan = {
            "schema_version": 1,
            "plan_id": "mp_test",
            "operations": [
                {"kind": "clone", "repo_url": url, "dest_path": "units/u_7f3a/home/product"}
            ],
        }
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

        plan = {
            "schema_version": 1,
            "plan_id": "mp_test",
            "operations": [
                {
                    "kind": "clone",
                    "repo_url": url,
                    "dest_path": "units/u1/product",
                    "reference_base": ".grip/cache/repos/product.git",
                }
            ],
        }
        apply_materialization_plan(self.workspace_root, plan, yes=True)
        dest = self.workspace_root / "units" / "u1" / "product"
        alternates = dest / ".git" / "objects" / "info" / "alternates"
        self.assertTrue(alternates.exists())

    def test_clone_is_idempotent_for_existing_healthy_clone(self):
        url = self._init_bare_remote("product")
        plan = {
            "schema_version": 1,
            "plan_id": "mp_test",
            "operations": [{"kind": "clone", "repo_url": url, "dest_path": "units/u1/product"}],
        }
        apply_materialization_plan(self.workspace_root, plan, yes=True)
        second = apply_materialization_plan(self.workspace_root, plan, yes=True)
        self.assertFalse(second["operations"][0]["first_materialize"])

    def test_clone_rejects_worktree_linked_git_dir(self):
        """gap#6 / config#491 §8.1: .git as a worktree pointer file is forbidden."""
        dest = self.workspace_root / "units" / "u1" / "product"
        dest.mkdir(parents=True)
        (dest / ".git").write_text("gitdir: /somewhere/else/.git/worktrees/product\n")

        plan = {
            "schema_version": 1,
            "plan_id": "mp_test",
            "operations": [
                {"kind": "clone", "repo_url": "https://example.com/x.git", "dest_path": "units/u1/product"}
            ],
        }
        with self.assertRaises(MaterializationPlanError):
            apply_materialization_plan(self.workspace_root, plan, yes=True)


class TestVenvOperation(MaterializationPlanTestBase):
    def test_creates_venv_via_uv(self):
        plan = {
            "schema_version": 1,
            "plan_id": "mp_test",
            "operations": [
                {"kind": "venv", "dest_path": "units/u1/home/.venv", "engine": "uv", "python": ">=3.11"}
            ],
        }
        apply_materialization_plan(self.workspace_root, plan, yes=True)
        venv_path = self.workspace_root / "units" / "u1" / "home" / ".venv"
        self.assertTrue((venv_path / "bin" / "python").exists() or (venv_path / "bin" / "python3").exists())

    def test_venv_idempotent_when_already_exists(self):
        plan = {
            "schema_version": 1,
            "plan_id": "mp_test",
            "operations": [
                {"kind": "venv", "dest_path": "units/u1/home/.venv", "engine": "uv", "python": ">=3.11"}
            ],
        }
        apply_materialization_plan(self.workspace_root, plan, yes=True)
        second = apply_materialization_plan(self.workspace_root, plan, yes=True)
        self.assertFalse(second["operations"][0]["created"])


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

        plan = {
            "schema_version": 1,
            "plan_id": "mp_test",
            "operations": [
                {
                    "kind": "editable_install",
                    "venv_path": "units/u1/home/.venv",
                    "source_path": "units/u1/home/product",
                    "extras": [],
                }
            ],
        }
        result = apply_materialization_plan(self.workspace_root, plan, yes=True)
        self.assertEqual(result["operations"][0]["kind"], "editable_install")
        check = subprocess.run(
            [str(venv_path / "bin" / "python"), "-c", "import product"],
            capture_output=True, text=True,
        )
        self.assertEqual(check.returncode, 0, check.stderr)


class TestProjectFileOperation(MaterializationPlanTestBase):
    def test_copies_and_verifies_hash(self):
        source = self.tmp / "staged-AGENTS.md"
        content = b"# Foundation\nRole: neutral executor.\n"
        source.write_bytes(content)
        plan = {
            "schema_version": 1,
            "plan_id": "mp_test",
            "operations": [
                {
                    "kind": "project_file",
                    "source_path": str(source),
                    "source_sha256": hashlib.sha256(content).hexdigest(),
                    "dest_path": "units/u1/home/AGENTS.md",
                    "mode": "copy",
                }
            ],
        }
        apply_materialization_plan(self.workspace_root, plan, yes=True)
        dest = self.workspace_root / "units" / "u1" / "home" / "AGENTS.md"
        self.assertEqual(dest.read_bytes(), content)

    def test_rejects_hash_mismatch(self):
        source = self.tmp / "staged.md"
        source.write_bytes(b"real content")
        plan = {
            "schema_version": 1,
            "plan_id": "mp_test",
            "operations": [
                {
                    "kind": "project_file",
                    "source_path": str(source),
                    "source_sha256": hashlib.sha256(b"different content").hexdigest(),
                    "dest_path": "units/u1/home/AGENTS.md",
                    "mode": "copy",
                }
            ],
        }
        with self.assertRaises(MaterializationPlanError):
            apply_materialization_plan(self.workspace_root, plan, yes=True)

    def test_deletes_staging_source_after_copy(self):
        """config#491 §6.2: staging artifact is deleted after acknowledgement."""
        source = self.tmp / "staged.md"
        content = b"ephemeral"
        source.write_bytes(content)
        plan = {
            "schema_version": 1,
            "plan_id": "mp_test",
            "operations": [
                {
                    "kind": "project_file",
                    "source_path": str(source),
                    "source_sha256": hashlib.sha256(content).hexdigest(),
                    "dest_path": "units/u1/home/AGENTS.md",
                    "mode": "copy",
                }
            ],
        }
        apply_materialization_plan(self.workspace_root, plan, yes=True)
        self.assertFalse(source.exists())


class TestReceipts(MaterializationPlanTestBase):
    def test_writes_structured_receipt(self):
        url = self._init_bare_remote("product")
        plan = {
            "schema_version": 1,
            "plan_id": "mp_receipt_test",
            "workspace_spec_sha256": "abc123",
            "operations": [{"kind": "clone", "repo_url": url, "dest_path": "units/u1/product"}],
        }
        apply_materialization_plan(self.workspace_root, plan, yes=True)

        receipt_path = self.workspace_root / ".grip" / "state" / "materialization" / "mp_receipt_test.json"
        self.assertTrue(receipt_path.exists())
        receipt = json.loads(receipt_path.read_text())
        self.assertEqual(receipt["plan_id"], "mp_receipt_test")
        self.assertEqual(receipt["workspace_spec_sha256"], "abc123")
        self.assertIn("operations", receipt)
        self.assertEqual(len(receipt["operations"]), 1)

    def test_receipt_contains_no_identity_fields(self):
        """config#491 §12.1: neutral receipts carry no identity/org/channel/secret/memory."""
        url = self._init_bare_remote("product")
        plan = {
            "schema_version": 1,
            "plan_id": "mp_receipt_neutrality",
            "operations": [{"kind": "clone", "repo_url": url, "dest_path": "units/u1/product"}],
        }
        apply_materialization_plan(self.workspace_root, plan, yes=True)

        receipt_path = (
            self.workspace_root / ".grip" / "state" / "materialization" / "mp_receipt_neutrality.json"
        )
        raw = receipt_path.read_text().lower()
        for forbidden in ("agent_name", "agent_id", "role", "org", "channel", "secret", "memory"):
            self.assertNotIn(forbidden, raw)

    def test_rerun_is_resumable_not_duplicated(self):
        """A rerun of the same plan must not re-clone or duplicate receipt entries."""
        url = self._init_bare_remote("product")
        plan = {
            "schema_version": 1,
            "plan_id": "mp_resume_test",
            "operations": [{"kind": "clone", "repo_url": url, "dest_path": "units/u1/product"}],
        }
        apply_materialization_plan(self.workspace_root, plan, yes=True)
        second = apply_materialization_plan(self.workspace_root, plan, yes=True)

        receipt_path = self.workspace_root / ".grip" / "state" / "materialization" / "mp_resume_test.json"
        receipt = json.loads(receipt_path.read_text())
        self.assertEqual(len(receipt["operations"]), 1)
        self.assertFalse(second["operations"][0]["first_materialize"])


if __name__ == "__main__":
    unittest.main()
