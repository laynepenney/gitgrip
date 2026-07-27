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
import os
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from gr2.python_cli import spec_apply
from gr2.python_cli.spec_apply import (
    MaterializationPlanError,
    apply_materialization_plan,
    apply_plan,
    compute_plan_hash,
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
        # config#492 §6.2.1 #1: the executor reopens the canonical
        # WorkspaceSpec and verifies its bytes hash to the plan's
        # workspace_spec_sha256, so every fixture needs a real one.
        self.spec_sha256 = self._write_workspace_spec()

    def tearDown(self):
        import shutil

        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write_workspace_spec(self, content: str = 'workspace_name = "test"\n') -> str:
        spec_path = workspace_spec_path(self.workspace_root)
        spec_path.parent.mkdir(parents=True, exist_ok=True)
        spec_path.write_text(content)
        return hashlib.sha256(spec_path.read_bytes()).hexdigest()

    def _plan(self, operations: list[dict[str, object]], **overrides: object) -> dict[str, object]:
        plan: dict[str, object] = {
            "schema_version": 1,
            "plan_id": "mp_test",
            "unit_key": "u_test",
            "workspace_spec_sha256": self.spec_sha256,
            "operations": operations,
        }
        plan.update(overrides)
        return plan

    def _clone_op(self, **fields: object) -> dict[str, object]:
        """A schema-complete clone operation. `branch` is REQUIRED by the
        pinned v1 schema (round 3) -- helper so every fixture carries it."""
        op: dict[str, object] = {"kind": "clone", "branch": "main"}
        op.update(fields)
        return op

    def _venv_op(self, **fields: object) -> dict[str, object]:
        op: dict[str, object] = {"kind": "venv", "engine": "uv", "python": ">=3.11"}
        op.update(fields)
        return op

    def _project_file_op(self, **fields: object) -> dict[str, object]:
        op: dict[str, object] = {"kind": "project_file", "mode": "copy"}
        op.update(fields)
        return op

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
            [{"kind": "clone", "branch": "main", "repo_url": "https://example.com/x.git", "dest_path": "/etc/passwd"}]
        )
        with self.assertRaises(MaterializationPlanError):
            apply_materialization_plan(self.workspace_root, plan, yes=True)

    def test_clone_rejects_dest_path_escaping_via_dotdot(self):
        plan = self._plan(
            [
                {
                    "kind": "clone",
                    "branch": "main",
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
                    "branch": "main",
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
                    "branch": "main",
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
                    "branch": "main",
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
                {"kind": "clone", "branch": "main", "repo_url": "https://example.com/x.git", "dest_path": "units/u1/repo"}
            ],
        }
        with self.assertRaises(MaterializationPlanError):
            apply_materialization_plan(self.workspace_root, plan, yes=True)

    def test_unsafe_plan_id_rejected(self):
        plan = self._plan(
            [{"kind": "clone", "branch": "main", "repo_url": "https://example.com/x.git", "dest_path": "units/u1/repo"}],
            plan_id="../../../../escaped_receipt",
        )
        with self.assertRaises(MaterializationPlanError):
            apply_materialization_plan(self.workspace_root, plan, yes=True)

    def test_duplicate_dest_path_rejected(self):
        plan = self._plan(
            [
                {"kind": "venv", "dest_path": "units/u1/.venv", "engine": "uv", "python": ">=3.11"},
                {"kind": "clone", "branch": "main", "repo_url": "https://example.com/x.git", "dest_path": "units/u1/.venv"},
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
                {"kind": "clone", "branch": "main", "repo_url": "https://example.com/x.git", "dest_path": "/etc/passwd"},
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
                {"kind": "clone", "branch": "main", "repo_url": "https://example.com/x.git", "dest_path": "units/u1/./.venv"},
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
                    "branch": "main",
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

    def test_receipt_publish_atomicity_proven_by_failed_replace(self):
        """Round 2 (Sentinel): a test asserting only "no temp file left
        behind" doesn't distinguish atomic-publish from a direct write --
        a direct write also trivially leaves no temp file. This makes the
        atomic-replace step itself fail and confirms no final receipt.json
        ever appears, proving the publish is genuinely replace-based."""
        url = self._init_bare_remote("product")
        plan = self._plan(
            [self._clone_op(repo_url=url, dest_path="units/u1/product")],
            plan_id="mp_atomic_proof",
        )

        original_replace = os.replace

        def selective_fail_replace(src, dst, **kwargs):
            if "materialization" in str(src):
                raise OSError("simulated replace failure")
            return original_replace(src, dst, **kwargs)

        with patch.object(spec_apply.os, "replace", selective_fail_replace):
            with self.assertRaises(OSError):
                apply_materialization_plan(self.workspace_root, plan, yes=True)

        receipt_path = self.workspace_root / ".grip" / "state" / "materialization" / "mp_atomic_proof.json"
        self.assertFalse(receipt_path.exists())

    def test_receipt_publish_fsyncs_file_and_parent_directory(self):
        """config#492 §6.2.1 #10, Sentinel round 3: publication performed
        write_text + rename with ZERO fsync calls. Rename success is not
        durable acknowledgement -- on power loss the rename can survive
        while the bytes don't, leaving a "published" receipt whose content
        never landed, after the staged inputs it acknowledges were deleted.
        Asserts both fsync calls happen AND that they precede the unlink."""
        content = b"durable"
        source_rel = self._stage_source("f_01", content)
        plan = self._plan(
            [
                self._project_file_op(
                    source_path=source_rel,
                    source_sha256=hashlib.sha256(content).hexdigest(),
                    dest_path="units/u1/home/AGENTS.md",
                )
            ],
            plan_id="mp_fsync_proof",
        )

        events: list[str] = []
        original_fsync = os.fsync
        original_unlink = Path.unlink

        def tracking_fsync(fd):
            events.append("fsync")
            return original_fsync(fd)

        def tracking_unlink(self_path, **kwargs):
            if "staging" in str(self_path):
                events.append("unlink")
            return original_unlink(self_path, **kwargs)

        with patch.object(spec_apply.os, "fsync", tracking_fsync):
            with patch.object(Path, "unlink", tracking_unlink):
                apply_materialization_plan(self.workspace_root, plan, yes=True)

        # Two fsyncs: the receipt file itself, then its parent directory.
        self.assertEqual(events.count("fsync"), 2, events)
        self.assertIn("unlink", events)
        self.assertLess(
            max(i for i, e in enumerate(events) if e == "fsync"),
            events.index("unlink"),
            f"both fsyncs must precede staging cleanup, got {events}",
        )

    def test_no_receipt_and_source_survives_when_fsync_fails(self):
        """The durability guarantee's failure face: if fsync raises, there
        must be no published receipt and the staged source must survive."""
        content = b"durable"
        source_rel = self._stage_source("f_01", content)
        plan = self._plan(
            [
                self._project_file_op(
                    source_path=source_rel,
                    source_sha256=hashlib.sha256(content).hexdigest(),
                    dest_path="units/u1/home/AGENTS.md",
                )
            ],
            plan_id="mp_fsync_fail",
        )

        with patch.object(spec_apply.os, "fsync", side_effect=OSError("simulated fsync failure")):
            with self.assertRaises(OSError):
                apply_materialization_plan(self.workspace_root, plan, yes=True)

        receipt_path = self.workspace_root / ".grip" / "state" / "materialization" / "mp_fsync_fail.json"
        self.assertFalse(receipt_path.exists())
        self.assertTrue((self.workspace_root / source_rel).exists())


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
            [{"kind": "clone", "branch": "main", "repo_url": url, "dest_path": "units/u_7f3a/home/product"}]
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
                    "branch": "main",
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
                    "branch": "main",
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
                    "branch": "main",
                    "repo_url": url_a,
                    "dest_path": "units/u1/product",
                    "reference_base": ".grip/cache/repos/product-a.git",
                }
            ]
        )
        with self.assertRaises(MaterializationPlanError):
            apply_materialization_plan(self.workspace_root, plan, yes=True)

    def test_clone_rejects_when_common_dir_check_cannot_run(self):
        """config#492 §6.2.1: fail CLOSED, not open -- if the common-dir
        probe cannot run, that is a rejection, not "assume it's fine".

        Round-3 mutation sweep caught this test itself passing for the
        WRONG reason: its old fixture was a bare `.git` directory with no
        git internals, which ALSO fails the origin check further down the
        same function, so a type-only assertRaises stayed green with the
        fail-closed branch removed entirely. Worse, I had already written
        that exact masking into a sibling test's docstring and never came
        back to repair this one.

        Now isolated properly: a HEALTHY clone with a CORRECT origin,
        where only the --git-common-dir probe is forced to fail, plus an
        assertion on the specific message so no other guard can satisfy
        it."""
        url = self._init_bare_remote("product")
        dest = self.workspace_root / "units" / "u1" / "product"
        dest.parent.mkdir(parents=True)
        _git(self.workspace_root, "clone", url, str(dest))

        real_run = subprocess.run

        def fake_run(cmd, *args, **kwargs):
            if isinstance(cmd, list) and "--git-common-dir" in cmd:
                return subprocess.CompletedProcess(cmd, 128, stdout="", stderr="simulated probe failure")
            return real_run(cmd, *args, **kwargs)

        plan = self._plan([self._clone_op(repo_url=url, dest_path="units/u1/product")])
        with patch.object(spec_apply.subprocess, "run", fake_run):
            with self.assertRaises(MaterializationPlanError) as ctx:
                apply_materialization_plan(self.workspace_root, plan, yes=True)
        self.assertIn("cannot verify isolation", str(ctx.exception))

    def test_clone_is_idempotent_for_existing_healthy_clone(self):
        url = self._init_bare_remote("product")
        plan = self._plan([{"kind": "clone", "branch": "main", "repo_url": url, "dest_path": "units/u1/product"}])
        apply_materialization_plan(self.workspace_root, plan, yes=True)
        second = apply_materialization_plan(self.workspace_root, plan, yes=True)
        self.assertFalse(second["operations"][0]["first_materialize"])

    def test_clone_rejects_worktree_linked_git_dir(self):
        """config#491 §8.1: .git as a worktree pointer file is forbidden."""
        dest = self.workspace_root / "units" / "u1" / "product"
        dest.mkdir(parents=True)
        (dest / ".git").write_text("gitdir: /somewhere/else/.git/worktrees/product\n")

        plan = self._plan(
            [{"kind": "clone", "branch": "main", "repo_url": "https://example.com/x.git", "dest_path": "units/u1/product"}]
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

        plan = self._plan([{"kind": "clone", "branch": "main", "repo_url": url, "dest_path": "units/u1/product"}])
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

        plan = self._plan([{"kind": "clone", "branch": "main", "repo_url": url_b, "dest_path": "units/u1/product"}])
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
                    "branch": "main",
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
            [{"kind": "clone", "branch": "main", "repo_url": url, "dest_path": "units/u1/product"}],
            plan_id="mp_receipt_test",
            workspace_spec_sha256=self.spec_sha256,
        )
        apply_materialization_plan(self.workspace_root, plan, yes=True)

        receipt_path = self.workspace_root / ".grip" / "state" / "materialization" / "mp_receipt_test.json"
        self.assertTrue(receipt_path.exists())
        receipt = json.loads(receipt_path.read_text())
        # Exact receipt schema (Sentinel round 3: "checks only that broad
        # keys exist" left field-deletion mutants green).
        self.assertEqual(
            set(receipt),
            {
                "plan_id",
                "unit_key",
                "plan_hash",
                "schema_version",
                "workspace_spec_sha256",
                "stage",
                "applied_at",
                "operations",
            },
        )
        self.assertEqual(receipt["plan_id"], "mp_receipt_test")
        self.assertEqual(receipt["unit_key"], "u_test")
        self.assertEqual(receipt["stage"], "MATERIALIZED")
        self.assertEqual(receipt["workspace_spec_sha256"], self.spec_sha256)
        self.assertEqual(len(receipt["operations"]), 1)
        # Recompute independently from the pinned canonical serialization:
        # a constant plan_hash mutant dies here (Sentinel: "0"*64 left all
        # seven receipt tests green).
        expected_hash = hashlib.sha256(
            json.dumps(plan, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        ).hexdigest()
        self.assertEqual(receipt["plan_hash"], expected_hash)

    def test_plan_hash_uses_pinned_canonical_serialization(self):
        """config#492 §6.2.1 #9. Two independent proofs that this is the
        PINNED serialization, not merely deterministic:
        (a) equals the exact pinned recipe;
        (b) does NOT equal the default-separators / ensure_ascii variants
            the round-2 code actually used -- with a non-ASCII value in the
            plan so ensure_ascii genuinely differs."""
        plan = self._plan(
            [self._venv_op(dest_path="units/u1/.venv")],
            plan_id="mp_hash",
            unit_key="u_straße",
        )
        pinned = hashlib.sha256(
            json.dumps(plan, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        ).hexdigest()
        self.assertEqual(compute_plan_hash(plan), pinned)

        default_separators = hashlib.sha256(
            json.dumps(plan, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()
        escaped_ascii = hashlib.sha256(
            json.dumps(plan, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
        ).hexdigest()
        self.assertNotEqual(compute_plan_hash(plan), default_separators)
        self.assertNotEqual(compute_plan_hash(plan), escaped_ascii)

    def test_receipt_contains_no_identity_fields(self):
        """config#491 §12.1: neutral receipts carry no identity/org/channel/secret/memory."""
        url = self._init_bare_remote("product")
        plan = self._plan(
            [{"kind": "clone", "branch": "main", "repo_url": url, "dest_path": "units/u1/product"}],
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
            [{"kind": "clone", "branch": "main", "repo_url": url, "dest_path": "units/u1/product"}],
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
            [{"kind": "clone", "branch": "main", "repo_url": url, "dest_path": "units/u1/product"}],
            plan_id="mp_atomic_test",
        )
        apply_materialization_plan(self.workspace_root, plan, yes=True)
        state_dir = self.workspace_root / ".grip" / "state" / "materialization"
        leftovers = [p for p in state_dir.glob("*.tmp-*")]
        self.assertEqual(leftovers, [])


class TestPinnedSchemaConformance(MaterializationPlanTestBase):
    """Round 3 (Atlas + Sentinel): a hand-rolled allowlist is a separate,
    looser contract by construction -- config#492's malformed fixtures
    were only 8/12 RED against it. These pin conformance to the PINNED
    schema itself (SHA a5061501...590231c), including the exact survivors
    both reviewers enumerated."""

    def test_packaged_schema_matches_pinned_sha256(self):
        raw = spec_apply._read_plan_schema_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), spec_apply._PLAN_SCHEMA_SHA256)

    def test_schema_load_fails_closed_on_hash_mismatch(self):
        """A tampered/unpinned schema must refuse to validate at all,
        rather than silently enforcing a different contract."""
        spec_apply._plan_validator = None
        try:
            with patch.object(spec_apply, "_read_plan_schema_bytes", return_value=b"{}"):
                with self.assertRaises(MaterializationPlanError) as ctx:
                    apply_materialization_plan(
                        self.workspace_root,
                        self._plan([self._venv_op(dest_path="units/u1/.venv")]),
                        yes=True,
                    )
            self.assertIn("hash mismatch", str(ctx.exception))
        finally:
            spec_apply._plan_validator = None

    def _assert_rejected(self, plan: dict[str, object], label: str) -> None:
        with self.assertRaises(MaterializationPlanError, msg=f"{label} must be rejected"):
            apply_materialization_plan(self.workspace_root, plan, yes=True)

    def test_clone_without_branch_rejected(self):
        self._assert_rejected(
            self._plan([{"kind": "clone", "repo_url": "https://e.com/x.git", "dest_path": "units/u1/p"}]),
            "clone without required branch",
        )

    def test_venv_without_engine_or_python_rejected(self):
        self._assert_rejected(
            self._plan([{"kind": "venv", "dest_path": "units/u1/.venv"}]),
            "venv without required engine/python",
        )

    def test_editable_install_without_extras_rejected(self):
        self._assert_rejected(
            self._plan(
                [{"kind": "editable_install", "venv_path": "units/u1/.venv", "source_path": "units/u1/src"}]
            ),
            "editable_install without required extras",
        )

    def test_project_file_without_mode_rejected(self):
        source_rel = self._stage_source("f_01", b"x")
        self._assert_rejected(
            self._plan(
                [
                    {
                        "kind": "project_file",
                        "source_path": source_rel,
                        "source_sha256": hashlib.sha256(b"x").hexdigest(),
                        "dest_path": "units/u1/AGENTS.md",
                    }
                ]
            ),
            "project_file without required mode",
        )

    def test_short_workspace_spec_sha_rejected(self):
        self._assert_rejected(
            self._plan([self._venv_op(dest_path="units/u1/.venv")], workspace_spec_sha256="abc123"),
            "six-character workspace_spec_sha256",
        )

    def test_dot_path_segment_rejected(self):
        self._assert_rejected(
            self._plan([self._venv_op(dest_path="units/./u1/.venv")]),
            "literal '.' path segment",
        )

    def test_backslash_path_rejected(self):
        self._assert_rejected(
            self._plan([self._venv_op(dest_path="units\\u1\\.venv")]),
            "backslash path",
        )

    def test_duplicate_extras_rejected(self):
        self._assert_rejected(
            self._plan(
                [
                    {
                        "kind": "editable_install",
                        "venv_path": "units/u1/.venv",
                        "source_path": "units/u1/src",
                        "extras": ["dev", "dev"],
                    }
                ]
            ),
            "duplicate extras (uniqueItems)",
        )

    def test_overlong_plan_id_rejected(self):
        self._assert_rejected(
            self._plan([self._venv_op(dest_path="units/u1/.venv")], plan_id="p" * 129),
            "129-character plan_id",
        )

    def test_nested_staged_input_path_rejected(self):
        nested = self.workspace_root / ".grip" / "staging" / "inputs" / "a"
        nested.mkdir(parents=True, exist_ok=True)
        (nested / "b").write_bytes(b"x")
        self._assert_rejected(
            self._plan(
                [
                    self._project_file_op(
                        source_path=".grip/staging/inputs/a/b",
                        source_sha256=hashlib.sha256(b"x").hexdigest(),
                        dest_path="units/u1/AGENTS.md",
                    )
                ]
            ),
            "nested staged input path",
        )

    def test_boolean_schema_version_rejected(self):
        """schema_version=True passes a naive `!= 1` check because bool is
        an int subclass in Python (True == 1); JSON Schema's const:1
        distinguishes the types correctly."""
        self._assert_rejected(
            self._plan([self._venv_op(dest_path="units/u1/.venv")], schema_version=True),
            "boolean schema_version",
        )

    def test_invalid_opaque_token_rejected(self):
        self._assert_rejected(
            self._plan([self._venv_op(dest_path="units/u1/.venv")], unit_key="../escape"),
            "invalid opaque unit_key",
        )

    def test_missing_workspace_spec_file_rejected(self):
        """config#492 §6.2.1 #1: the executor applied with no canonical
        WorkspaceSpec at all, so the declared hash was never verified."""
        workspace_spec_path(self.workspace_root).unlink()
        self._assert_rejected(
            self._plan([self._venv_op(dest_path="units/u1/.venv")]),
            "absent canonical WorkspaceSpec",
        )

    def test_workspace_spec_hash_mismatch_rejected(self):
        """The declared hash must equal the REOPENED bytes -- a plan
        compiled against different workspace state must not apply."""
        self._write_workspace_spec('workspace_name = "drifted"\n')
        self._assert_rejected(
            self._plan([self._venv_op(dest_path="units/u1/.venv")]),
            "workspace_spec_sha256 vs reopened bytes mismatch",
        )


class TestCanonicalizationDefenseInDepth(MaterializationPlanTestBase):
    """Round-3 mutation sweep: deleting the raw-segment guards inside
    _canonicalize_workspace_path left all 98 tests GREEN, because the
    pinned schema's workspaceRelativePath pattern is a strictly stronger
    FIRST gate -- every plan-level path test was being satisfied by the
    schema, never reaching canonicalization. The defense-in-depth layer
    had no independent coverage at all.

    That matters precisely because it IS defense in depth: if the schema
    is ever loosened, or a call site is added that reaches canonicalization
    without schema validation (the legacy apply_plan adapter already does
    exactly that), this layer is the only thing standing. So it gets tested
    directly, at its own level, not through the schema that shadows it."""

    def _reject(self, relative: str) -> None:
        with self.assertRaises(MaterializationPlanError, msg=f"{relative!r} must be rejected"):
            spec_apply._canonicalize_workspace_path(
                self.workspace_root, relative, field_name="probe"
            )

    def test_rejects_single_dot_segment(self):
        self._reject("a/./b")

    def test_rejects_dotdot_segment(self):
        self._reject("a/../b")

    def test_rejects_empty_segment(self):
        self._reject("a//b")

    def test_rejects_backslash(self):
        self._reject("a\\b")

    def test_rejects_nul_byte(self):
        """Without the raw guard this escapes as an UNCAUGHT ValueError
        from Path.resolve() ("embedded null character"), i.e. a crash-class
        regression rather than a clean rejection."""
        self._reject("a/b\x00c")

    def test_rejects_absolute_and_tilde(self):
        self._reject("/etc/passwd")
        self._reject("~/secrets")

    def test_accepts_ordinary_relative_path(self):
        """The positive face -- these guards must not reject legitimate paths."""
        resolved = spec_apply._canonicalize_workspace_path(
            self.workspace_root, "units/u1/product", field_name="probe"
        )
        self.assertEqual(resolved, (self.workspace_root / "units" / "u1" / "product").resolve())


class TestUnicodeCollisionGuards(MaterializationPlanTestBase):
    """Sentinel round 3: removing .casefold() left all 13 plan-shape tests
    GREEN because no case-only collision fixture existed."""

    def test_case_only_duplicate_dest_paths_rejected(self):
        with self.assertRaises(MaterializationPlanError):
            apply_materialization_plan(
                self.workspace_root,
                self._plan(
                    [
                        self._venv_op(dest_path="units/u1/.venv"),
                        self._venv_op(dest_path="units/u1/.VENV"),
                    ]
                ),
                yes=True,
            )

    def test_unicode_casefold_duplicate_dest_paths_rejected(self):
        """Specifically kills a `.lower()` substitution: lower() leaves 'ß'
        alone, only casefold() folds it to 'ss' -- so these two paths
        collide under casefold and do not under lower."""
        with self.assertRaises(MaterializationPlanError):
            apply_materialization_plan(
                self.workspace_root,
                self._plan(
                    [
                        self._venv_op(dest_path="units/straße/.venv"),
                        self._venv_op(dest_path="units/STRASSE/.venv"),
                    ]
                ),
                yes=True,
            )


class TestCommonDirComparisonGuard(MaterializationPlanTestBase):
    """Sentinel round 3: disabling the `common_dir != git_path` COMPARISON
    left all 48 materialization tests GREEN. My round-2 test only exercised
    the returncode!=0 fail-closed branch (and even that was masked, since
    its .git-with-no-internals fixture also fails the origin check). This
    isolates the comparison itself: a HEALTHY clone with a CORRECT origin,
    where only the common-dir probe reports a foreign path."""

    def test_rejects_common_dir_pointing_at_another_checkout(self):
        url = self._init_bare_remote("product")
        dest = self.workspace_root / "units" / "u1" / "product"
        dest.parent.mkdir(parents=True)
        _git(self.workspace_root, "clone", url, str(dest))
        foreign = self.workspace_root / "elsewhere" / ".git"
        foreign.mkdir(parents=True)

        real_run = subprocess.run

        def fake_run(cmd, *args, **kwargs):
            if isinstance(cmd, list) and "--git-common-dir" in cmd:
                return subprocess.CompletedProcess(cmd, 0, stdout=f"{foreign}\n", stderr="")
            return real_run(cmd, *args, **kwargs)

        plan = self._plan([self._clone_op(repo_url=url, dest_path="units/u1/product")])
        with patch.object(spec_apply.subprocess, "run", fake_run):
            with self.assertRaises(MaterializationPlanError) as ctx:
                apply_materialization_plan(self.workspace_root, plan, yes=True)
        # Match the SPECIFIC failure, not just "some error was raised" --
        # the mistake that masked the round-2 version of this test.
        self.assertIn("git-common-dir", str(ctx.exception))


class TestExecutorSeamIsShared(MaterializationPlanTestBase):
    """Sentinel round 3: replacing the legacy converge_unit_repos call to
    _apply_clone_operation with a behavior-equivalent direct
    _clone_isolated call left 11/11 GREEN -- behavior parity is not proof
    of a shared seam. A spy proves the legacy adapter genuinely routes
    through the shared operation executor; a bypass mutant makes it RED."""

    def test_legacy_apply_plan_routes_clones_through_shared_operation_executor(self):
        url = self._init_bare_remote("app")
        spec_path = workspace_spec_path(self.workspace_root)
        spec_path.write_text(
            "\n".join(
                [
                    'workspace_name = "test"',
                    "",
                    "[[repos]]",
                    'name = "app"',
                    'path = "repos/app"',
                    f'url = "{url}"',
                    "",
                    "[[units]]",
                    'name = "atlas"',
                    'path = "agents/atlas/home"',
                    'repos = ["app"]',
                    "",
                ]
            )
        )

        seen: list[dict[str, object]] = []
        real_apply_clone = spec_apply._apply_clone_operation

        def spy(workspace_root, op):
            seen.append(op)
            return real_apply_clone(workspace_root, op)

        with patch.object(spec_apply, "_apply_clone_operation", spy):
            apply_plan(self.workspace_root, yes=True)

        # Both the workspace-level repo clone AND the unit's own checkout
        # must have gone through the shared operation dispatch.
        self.assertGreaterEqual(len(seen), 2, seen)
        dests = {op["dest_path"] for op in seen}
        self.assertIn("repos/app", dests)
        self.assertIn("agents/atlas/home/app", dests)


class TestVenvProbeStrength(MaterializationPlanTestBase):
    """config#492 §6.2.1 #6 -- production-shaped mutants both reviewers
    reported surviving the round-2 file-presence check."""

    def _forge_venv(self, body: str) -> Path:
        venv = self.workspace_root / "units" / "u1" / ".venv"
        (venv / "bin").mkdir(parents=True)
        (venv / "pyvenv.cfg").write_text("home = /nonexistent\nversion = 3.99.0\n")
        interp = venv / "bin" / "python3"
        interp.write_text(body)
        interp.chmod(0o755)
        return venv

    def test_rejects_executable_shell_script_masquerading_as_interpreter(self):
        """Atlas: pyvenv.cfg + an executable SHELL SCRIPT at bin/python3
        was accepted and receipted as an existing venv."""
        self._forge_venv("#!/bin/sh\necho fake\n")
        with self.assertRaises(MaterializationPlanError):
            apply_materialization_plan(
                self.workspace_root,
                self._plan([self._venv_op(dest_path="units/u1/.venv")]),
                yes=True,
            )

    def test_rejects_interpreter_that_exits_nonzero(self):
        """Sentinel: executable bin/python whose body exits 42."""
        self._forge_venv("#!/bin/sh\nexit 42\n")
        with self.assertRaises(MaterializationPlanError):
            apply_materialization_plan(
                self.workspace_root,
                self._plan([self._venv_op(dest_path="units/u1/.venv")]),
                yes=True,
            )

    def test_rejects_real_venv_failing_declared_python_constraint(self):
        """Sentinel: a real-shaped venv was accepted under python=">=99",
        an unsatisfiable constraint no genuine interpreter can meet. The
        probe must check the DECLARED constraint, not just venv-ness."""
        venv_path = self.workspace_root / "units" / "u1" / ".venv"
        venv_path.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["uv", "venv", "--python", ">=3.11", str(venv_path)], check=True, capture_output=True
        )
        with self.assertRaises(MaterializationPlanError):
            apply_materialization_plan(
                self.workspace_root,
                self._plan([self._venv_op(dest_path="units/u1/.venv", python=">=99")]),
                yes=True,
            )

    def test_accepts_real_venv_satisfying_declared_constraint(self):
        """The positive face: the probe must not reject genuine venvs."""
        venv_path = self.workspace_root / "units" / "u1" / ".venv"
        venv_path.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["uv", "venv", "--python", ">=3.11", str(venv_path)], check=True, capture_output=True
        )
        result = apply_materialization_plan(
            self.workspace_root,
            self._plan([self._venv_op(dest_path="units/u1/.venv")]),
            yes=True,
        )
        self.assertFalse(result["operations"][0]["created"])
        self.assertTrue(result["operations"][0]["interpreter_path"])


class TestBranchDesiredState(MaterializationPlanTestBase):
    """Atlas round 3: an existing healthy clone on `main` accepted a plan
    declaring branch `feature` and remained on `main` -- required plan
    fields are desired state validated on every apply, not inputs consumed
    only during first creation."""

    def test_existing_clone_on_wrong_branch_rejected(self):
        url = self._init_bare_remote("product")
        dest = self.workspace_root / "units" / "u1" / "product"
        dest.parent.mkdir(parents=True)
        _git(self.workspace_root, "clone", url, str(dest))

        plan = self._plan([self._clone_op(repo_url=url, dest_path="units/u1/product", branch="feature")])
        with self.assertRaises(MaterializationPlanError) as ctx:
            apply_materialization_plan(self.workspace_root, plan, yes=True)
        self.assertIn("branch", str(ctx.exception))
        # Never force-switched (prior source ruling on §8.3).
        self.assertEqual(_git(dest, "branch", "--show-current").stdout.strip(), "main")


class TestCacheProvenance(MaterializationPlanTestBase):
    """config#492 §6.2.1 #5 -- fail CLOSED on unverifiable cache identity."""

    def test_rejects_non_git_directory_at_canonical_cache_path(self):
        """Atlas/Sentinel: a non-Git directory at the canonical path was
        accepted, the clone silently proceeded WITHOUT an alternate, and
        the receipt still claimed alternate_approved=True."""
        url = self._init_bare_remote("product")
        cache = self.workspace_root / ".grip" / "cache" / "repos" / "product.git"
        cache.mkdir(parents=True)
        (cache / "not-a-repo.txt").write_text("nope")

        plan = self._plan(
            [
                self._clone_op(
                    repo_url=url,
                    dest_path="units/u1/product",
                    reference_base=".grip/cache/repos/product.git",
                )
            ]
        )
        with self.assertRaises(MaterializationPlanError):
            apply_materialization_plan(self.workspace_root, plan, yes=True)
        self.assertFalse((self.workspace_root / "units" / "u1" / "product").exists())

    def test_rejects_cache_with_no_canonical_origin(self):
        """A bare repo with no origin remote: provenance is ABSENT, which
        the round-2 code fail-opened on (`if origin is not None and ...`)."""
        url = self._init_bare_remote("product")
        cache = self.workspace_root / ".grip" / "cache" / "repos" / "product.git"
        cache.parent.mkdir(parents=True, exist_ok=True)
        _git(self.workspace_root, "init", "--bare", str(cache))

        plan = self._plan(
            [
                self._clone_op(
                    repo_url=url,
                    dest_path="units/u1/product",
                    reference_base=".grip/cache/repos/product.git",
                )
            ]
        )
        with self.assertRaises(MaterializationPlanError):
            apply_materialization_plan(self.workspace_root, plan, yes=True)

    def test_rejects_declared_cache_that_does_not_exist(self):
        url = self._init_bare_remote("product")
        plan = self._plan(
            [
                self._clone_op(
                    repo_url=url,
                    dest_path="units/u1/product",
                    reference_base=".grip/cache/repos/product.git",
                )
            ]
        )
        with self.assertRaises(MaterializationPlanError):
            apply_materialization_plan(self.workspace_root, plan, yes=True)

    def test_alternate_evidence_is_observed_not_assumed(self):
        """Receipt evidence must come from the actual alternates file."""
        url = self._init_bare_remote("product")
        cache = self.workspace_root / ".grip" / "cache" / "repos" / "product.git"
        cache.parent.mkdir(parents=True, exist_ok=True)
        _git(self.workspace_root, "clone", "--mirror", url, str(cache))

        plan = self._plan(
            [
                self._clone_op(
                    repo_url=url,
                    dest_path="units/u1/product",
                    reference_base=".grip/cache/repos/product.git",
                )
            ]
        )
        result = apply_materialization_plan(self.workspace_root, plan, yes=True)
        op_result = result["operations"][0]
        observed = op_result["observed_alternate"]
        self.assertIsNotNone(observed)
        self.assertEqual(Path(observed).resolve(), (cache / "objects").resolve())
        self.assertTrue(op_result["alternate_approved"])

    def test_declared_reference_producing_no_alternate_is_rejected(self):
        """Round-3 mutation sweep: the happy-path test above cannot
        distinguish observed-from-disk evidence from evidence assumed off
        the request, because when git DOES create the alternate both are
        true. This forces the discriminating case -- a declared reference
        that yields NO alternate -- by making the clone step produce a repo
        without one. Observation-based evidence rejects; request-based
        evidence would sail through and receipt alternate_approved=True for
        a clone that shares no objects at all."""
        url = self._init_bare_remote("product")
        cache = self.workspace_root / ".grip" / "cache" / "repos" / "product.git"
        cache.parent.mkdir(parents=True, exist_ok=True)
        _git(self.workspace_root, "clone", "--mirror", url, str(cache))

        real_clone_repo = spec_apply.clone_repo

        def clone_without_alternate(repo_url, target, *, reference_repo_root=None):
            # Clone for real, but WITHOUT the reference -- simulating git
            # declining to use a nominally-valid cache.
            return real_clone_repo(repo_url, target, reference_repo_root=None)

        plan = self._plan(
            [
                self._clone_op(
                    repo_url=url,
                    dest_path="units/u1/product",
                    reference_base=".grip/cache/repos/product.git",
                )
            ]
        )
        with patch.object(spec_apply, "clone_repo", clone_without_alternate):
            with self.assertRaises(MaterializationPlanError) as ctx:
                apply_materialization_plan(self.workspace_root, plan, yes=True)
        self.assertIn("carries no alternate", str(ctx.exception))
        # Rolled back, not left half-published.
        self.assertFalse((self.workspace_root / "units" / "u1" / "product").exists())


class TestStagingSymlinkGuards(MaterializationPlanTestBase):
    """config#492 §6.2.1 #2/#7 -- any EXISTING symlink in the prefix, and
    a non-symlink regular source. Sentinel round 3's exact fixtures."""

    def test_rejects_symlink_alias_inside_staging(self):
        """`.grip/staging/inputs/alias -> .../inputs/real` was accepted;
        the projection ran and cleanup unlinked the RESOLVED target,
        leaving the alias dangling. Resolve-based containment can't see
        this -- both sides are legitimately inside staging."""
        staging = self.workspace_root / ".grip" / "staging" / "inputs"
        staging.mkdir(parents=True, exist_ok=True)
        real = staging / "real"
        content = b"payload"
        real.write_bytes(content)
        (staging / "alias").symlink_to(real)

        plan = self._plan(
            [
                self._project_file_op(
                    source_path=".grip/staging/inputs/alias",
                    source_sha256=hashlib.sha256(content).hexdigest(),
                    dest_path="units/u1/AGENTS.md",
                )
            ]
        )
        with self.assertRaises(MaterializationPlanError):
            apply_materialization_plan(self.workspace_root, plan, yes=True)
        self.assertTrue(real.exists(), "the resolved target must not be unlinked")
        self.assertFalse((self.workspace_root / "units" / "u1" / "AGENTS.md").exists())

    def test_rejects_symlinked_staging_directory_prefix(self):
        """`.grip/staging/inputs -> <workspace>/rogue`: both the candidate
        and the staging root resolve THROUGH the same link, so a
        resolve-only containment check holds while the bytes come from
        outside staging entirely."""
        rogue = self.workspace_root / "rogue"
        rogue.mkdir()
        content = b"rogue payload"
        (rogue / "f_01").write_bytes(content)
        staging_parent = self.workspace_root / ".grip" / "staging"
        staging_parent.mkdir(parents=True, exist_ok=True)
        (staging_parent / "inputs").symlink_to(rogue)

        plan = self._plan(
            [
                self._project_file_op(
                    source_path=".grip/staging/inputs/f_01",
                    source_sha256=hashlib.sha256(content).hexdigest(),
                    dest_path="units/u1/AGENTS.md",
                )
            ]
        )
        with self.assertRaises(MaterializationPlanError):
            apply_materialization_plan(self.workspace_root, plan, yes=True)
        self.assertTrue((rogue / "f_01").exists())
        self.assertFalse((self.workspace_root / "units" / "u1" / "AGENTS.md").exists())


class TestIdempotentCleanup(MaterializationPlanTestBase):
    """config#492 §6.2.1 #8: if cleanup is interrupted AFTER receipt
    publication, a rerun performs the idempotent cleanup from the verified
    receipt rather than failing or re-copying."""

    def _project_plan(self, content: bytes, source_rel: str) -> dict[str, object]:
        return self._plan(
            [
                self._project_file_op(
                    source_path=source_rel,
                    source_sha256=hashlib.sha256(content).hexdigest(),
                    dest_path="units/u1/AGENTS.md",
                )
            ],
            plan_id="mp_idempotent",
        )

    def test_rerun_after_successful_apply_succeeds_with_source_gone(self):
        content = b"payload"
        source_rel = self._stage_source("f_01", content)
        plan = self._project_plan(content, source_rel)
        apply_materialization_plan(self.workspace_root, plan, yes=True)
        self.assertFalse((self.workspace_root / source_rel).exists())

        result = apply_materialization_plan(self.workspace_root, plan, yes=True)
        self.assertTrue(result["operations"][0]["already_projected"])
        self.assertEqual(
            (self.workspace_root / "units" / "u1" / "AGENTS.md").read_bytes(), content
        )

    def test_rerun_cleans_up_source_left_by_interrupted_cleanup(self):
        content = b"payload"
        source_rel = self._stage_source("f_01", content)
        plan = self._project_plan(content, source_rel)
        apply_materialization_plan(self.workspace_root, plan, yes=True)

        # Simulate cleanup interrupted after the receipt was published.
        (self.workspace_root / source_rel).write_bytes(content)
        apply_materialization_plan(self.workspace_root, plan, yes=True)
        self.assertFalse((self.workspace_root / source_rel).exists())


class TestPerOperationReceiptSchemas(MaterializationPlanTestBase):
    """Sentinel round 3 asked for EXACT per-operation receipt schemas, not
    just top-level ones: "deletion of every operation-specific evidence
    field remains GREEN". Pinning the exact key set per kind means any
    evidence field removed or renamed turns this RED."""

    def test_clone_receipt_evidence_schema_is_exact(self):
        url = self._init_bare_remote("product")
        cache = self.workspace_root / ".grip" / "cache" / "repos" / "product.git"
        cache.parent.mkdir(parents=True, exist_ok=True)
        _git(self.workspace_root, "clone", "--mirror", url, str(cache))
        plan = self._plan(
            [
                self._clone_op(
                    repo_url=url,
                    dest_path="units/u1/product",
                    reference_base=".grip/cache/repos/product.git",
                )
            ]
        )
        op = apply_materialization_plan(self.workspace_root, plan, yes=True)["operations"][0]
        self.assertEqual(
            set(op),
            {
                "kind",
                "repo_url",
                "dest_path",
                "first_materialize",
                "head_sha",
                "observed_origin",
                "cache_path",
                "observed_alternate",
                "alternate_approved",
            },
        )
        self.assertTrue(op["head_sha"])
        self.assertEqual(op["observed_origin"], url)

    def test_venv_receipt_evidence_schema_is_exact(self):
        plan = self._plan([self._venv_op(dest_path="units/u1/.venv")])
        op = apply_materialization_plan(self.workspace_root, plan, yes=True)["operations"][0]
        self.assertEqual(set(op), {"kind", "dest_path", "created", "interpreter_path"})

    def test_editable_install_receipt_evidence_schema_is_exact(self):
        venv_path = self.workspace_root / "units" / "u1" / ".venv"
        venv_path.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["uv", "venv", "--python", ">=3.11", str(venv_path)], check=True, capture_output=True
        )
        source = self.workspace_root / "units" / "u1" / "product"
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
                    "venv_path": "units/u1/.venv",
                    "source_path": "units/u1/product",
                    "extras": [],
                }
            ]
        )
        op = apply_materialization_plan(self.workspace_root, plan, yes=True)["operations"][0]
        self.assertEqual(
            set(op),
            {"kind", "venv_path", "source_path", "extras", "distribution", "pep610_evidence"},
        )
        self.assertEqual(op["distribution"], "product")

    def test_project_file_receipt_evidence_schema_is_exact(self):
        content = b"payload"
        source_rel = self._stage_source("f_01", content)
        plan = self._plan(
            [
                self._project_file_op(
                    source_path=source_rel,
                    source_sha256=hashlib.sha256(content).hexdigest(),
                    dest_path="units/u1/AGENTS.md",
                )
            ]
        )
        op = apply_materialization_plan(self.workspace_root, plan, yes=True)["operations"][0]
        self.assertEqual(
            set(op), {"kind", "source_path", "dest_path", "source_sha256", "already_projected"}
        )


class TestProjectFileReceiptEvidence(MaterializationPlanTestBase):
    """Sentinel round 3: the observed project-file receipt had only kind,
    dest_path, and source_sha256 -- §12.1 also requires the source path."""

    def test_receipt_records_project_file_source_path(self):
        content = b"payload"
        source_rel = self._stage_source("f_01", content)
        plan = self._plan(
            [
                self._project_file_op(
                    source_path=source_rel,
                    source_sha256=hashlib.sha256(content).hexdigest(),
                    dest_path="units/u1/AGENTS.md",
                )
            ],
            plan_id="mp_pf_evidence",
        )
        apply_materialization_plan(self.workspace_root, plan, yes=True)
        receipt = json.loads(
            (
                self.workspace_root / ".grip" / "state" / "materialization" / "mp_pf_evidence.json"
            ).read_text()
        )
        op = receipt["operations"][0]
        self.assertEqual(op["source_path"], source_rel)
        self.assertEqual(op["dest_path"], "units/u1/AGENTS.md")
        self.assertEqual(op["source_sha256"], hashlib.sha256(content).hexdigest())
        self.assertNotIn("_pending_unlink", op, "internal orchestration key must never be receipted")


if __name__ == "__main__":
    unittest.main()
