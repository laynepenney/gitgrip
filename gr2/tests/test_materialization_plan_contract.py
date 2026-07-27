"""Plan-contract tests for the neutral MaterializationPlan v1 (S4-A).

Covers the PLAN-LEVEL contract only: pinned-schema conformance, the
schema SHA pin, identity-freedom, opaque-token safety, WorkspaceSpec
binding, path canonicalization, destination-collision detection, and
durable receipt publication.

Operation EXECUTION is deliberately absent from S4-A and lands with
S4-B (clone/cache/alternates), S4-C (staging/project_file), and S4-D
(venv/editable + PEP 610), each with its own domain validation and
mutation set -- see the grip#797 split.

Testing discipline carried forward from that review cycle: assert WHICH
invariant fired, not merely that some MaterializationPlanError was
raised. A fixture broken enough to trip the invariant under test is
usually broken enough to trip its neighbours too, and a type-only
assertRaises cannot tell them apart.
"""
from __future__ import annotations

import hashlib
import json
import os
import stat
import unittest
from pathlib import Path
from unittest.mock import patch

from gr2.python_cli import spec_apply
from gr2.python_cli.spec_apply import (
    MaterializationPlanError,
    canonicalize_workspace_path,
    compute_plan_hash,
    materialization_receipt_path,
    validate_materialization_plan,
    workspace_spec_path,
    write_materialization_receipt,
)


class PlanContractTestBase(unittest.TestCase):
    def setUp(self):
        import tempfile

        self.tmp = Path(tempfile.mkdtemp())
        self.workspace_root = self.tmp / "workspace"
        self.workspace_root.mkdir(parents=True)
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
        op: dict[str, object] = {
            "kind": "clone",
            "branch": "main",
            "repo_url": "https://example.com/product.git",
            "dest_path": "units/u1/product",
        }
        op.update(fields)
        return op

    def _venv_op(self, **fields: object) -> dict[str, object]:
        op: dict[str, object] = {
            "kind": "venv",
            "dest_path": "units/u1/.venv",
            "engine": "uv",
            "python": ">=3.11",
        }
        op.update(fields)
        return op

    def _project_file_op(self, **fields: object) -> dict[str, object]:
        op: dict[str, object] = {
            "kind": "project_file",
            "source_path": ".grip/staging/inputs/f_01",
            "source_sha256": "a" * 64,
            "dest_path": "units/u1/AGENTS.md",
            "mode": "copy",
        }
        op.update(fields)
        return op

    def _reject(self, plan: dict[str, object], expected_fragment: str, label: str) -> None:
        with self.assertRaises(MaterializationPlanError, msg=f"{label} must be rejected") as ctx:
            validate_materialization_plan(self.workspace_root, plan)
        self.assertIn(expected_fragment, str(ctx.exception), f"{label}: wrong invariant fired")


class TestSchemaPin(PlanContractTestBase):
    def test_packaged_schema_matches_pinned_sha256(self):
        raw = spec_apply._read_plan_schema_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), spec_apply._PLAN_SCHEMA_SHA256)

    def test_schema_load_fails_closed_on_hash_mismatch(self):
        """A tampered or unpinned schema must refuse to validate at all,
        rather than silently enforcing a different contract."""
        spec_apply._plan_validator = None
        try:
            with patch.object(spec_apply, "_read_plan_schema_bytes", return_value=b"{}"):
                self._reject(
                    self._plan([self._venv_op()]),
                    "hash mismatch",
                    "tampered schema bytes",
                )
        finally:
            spec_apply._plan_validator = None


class TestPinnedSchemaConformance(PlanContractTestBase):
    """config#492's malformed-plan set. A hand-rolled validator is a
    separate, looser contract by construction; these pin conformance to
    the pinned schema itself."""

    def test_valid_plan_accepted(self):
        validate_materialization_plan(self.workspace_root, self._plan([self._venv_op()]))

    def test_clone_without_branch_rejected(self):
        op = self._clone_op()
        del op["branch"]
        self._reject(self._plan([op]), "schema", "clone without required branch")

    def test_venv_without_engine_and_python_rejected(self):
        self._reject(
            self._plan([{"kind": "venv", "dest_path": "units/u1/.venv"}]),
            "schema",
            "venv without required engine/python",
        )

    def test_editable_install_without_extras_rejected(self):
        self._reject(
            self._plan(
                [{"kind": "editable_install", "venv_path": "units/u1/.venv", "source_path": "units/u1/src"}]
            ),
            "schema",
            "editable_install without required extras",
        )

    def test_project_file_without_mode_rejected(self):
        op = self._project_file_op()
        del op["mode"]
        self._reject(self._plan([op]), "schema", "project_file without required mode")

    def test_short_workspace_spec_sha_rejected(self):
        self._reject(
            self._plan([self._venv_op()], workspace_spec_sha256="abc123"),
            "schema",
            "six-character workspace_spec_sha256",
        )

    def test_dot_path_segment_rejected(self):
        self._reject(
            self._plan([self._venv_op(dest_path="units/./u1/.venv")]),
            "schema",
            "literal '.' path segment",
        )

    def test_backslash_path_rejected(self):
        self._reject(
            self._plan([self._venv_op(dest_path="units\\u1\\.venv")]),
            "schema",
            "backslash path",
        )

    def test_duplicate_extras_rejected(self):
        self._reject(
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
            "schema",
            "duplicate extras (uniqueItems)",
        )

    def test_overlong_plan_id_rejected(self):
        self._reject(
            self._plan([self._venv_op()], plan_id="p" * 129),
            "schema",
            "129-character plan_id",
        )

    def test_nested_staged_input_path_rejected(self):
        self._reject(
            self._plan([self._project_file_op(source_path=".grip/staging/inputs/a/b")]),
            "schema",
            "nested staged input path",
        )

    def test_boolean_schema_version_rejected(self):
        """bool is an int subclass in Python, so True == 1 slips a naive
        `!= 1` check; JSON Schema's const:1 distinguishes the types."""
        self._reject(
            self._plan([self._venv_op()], schema_version=True),
            "schema",
            "boolean schema_version",
        )

    def test_invalid_opaque_unit_key_rejected(self):
        self._reject(
            self._plan([self._venv_op()], unit_key="../escape"),
            "schema",
            "invalid opaque unit_key",
        )

    def test_reference_base_outside_cache_namespace_rejected(self):
        """The schema confines reference_base syntactically to
        .grip/cache/repos/<name>.git. Filesystem provenance (is it a real
        bare cache with the right origin) is S4-B's."""
        self._reject(
            self._plan([self._clone_op(reference_base="units/u1/rogue-cache.git")]),
            "schema",
            "reference_base outside the cache namespace",
        )

    def test_unknown_top_level_field_rejected(self):
        self._reject(self._plan([self._venv_op()], org="synapt"), "schema", "unknown top-level field")

    def test_unknown_operation_field_rejected(self):
        """An allowlist rejects any field not explicitly permitted, by
        construction -- a blacklist only catches names someone enumerated."""
        self._reject(
            self._plan([self._venv_op(metadata={"display_name": "Apollo"})]),
            "schema",
            "unknown operation field",
        )

    def test_empty_operations_rejected(self):
        self._reject(self._plan([]), "schema", "empty operations list")


class TestIdentityFreedom(PlanContractTestBase):
    def test_rejects_top_level_identity_field_on_operation(self):
        self._reject(
            self._plan([self._clone_op(agent_name="apollo")]),
            "schema",
            "operation carrying agent_name",
        )

    def test_recursive_identity_rejection_is_reachable(self):
        """Defence in depth beneath the allowlist: even inside an allowed
        field's VALUE, an identity-shaped key must be rejected. Exercised
        directly since the allowlist would reject the carrier field first."""
        with self.assertRaises(MaterializationPlanError) as ctx:
            spec_apply._reject_identity_fields_recursive(
                {"extras": [{"channel": "dev"}]}, path="operations[0]"
            )
        self.assertIn("identity-bearing", str(ctx.exception))


class TestWorkspaceSpecBinding(PlanContractTestBase):
    def test_missing_workspace_spec_file_rejected(self):
        workspace_spec_path(self.workspace_root).unlink()
        self._reject(
            self._plan([self._venv_op()]),
            "cannot be verified",
            "absent canonical WorkspaceSpec",
        )

    def test_workspace_spec_hash_mismatch_rejected(self):
        self._write_workspace_spec('workspace_name = "drifted"\n')
        self._reject(
            self._plan([self._venv_op()]),
            "workspace_spec_sha256 mismatch",
            "plan compiled against different workspace state",
        )


class TestDestinationCollisions(PlanContractTestBase):
    def test_case_only_duplicate_dest_paths_rejected(self):
        self._reject(
            self._plan([self._venv_op(dest_path="units/u1/.venv"), self._venv_op(dest_path="units/u1/.VENV")]),
            "collides",
            "case-only destination collision",
        )

    def test_unicode_casefold_duplicate_dest_paths_rejected(self):
        """Kills a `.lower()` substitution specifically: lower() leaves 'ß'
        alone, only casefold() folds it to 'ss'."""
        self._reject(
            self._plan(
                [
                    self._venv_op(dest_path="units/straße/.venv"),
                    self._venv_op(dest_path="units/STRASSE/.venv"),
                ]
            ),
            "collides",
            "Unicode casefold collision",
        )

    def test_distinct_destinations_accepted(self):
        validate_materialization_plan(
            self.workspace_root,
            self._plan(
                [self._venv_op(dest_path="units/a/.venv"), self._venv_op(dest_path="units/b/.venv")]
            ),
        )


class TestCanonicalizationDefenseInDepth(PlanContractTestBase):
    """The pinned schema's workspaceRelativePath pattern is a strictly
    stronger FIRST gate, so plan-level tests never reach canonicalization.
    That makes this layer invisible to them -- and it is genuinely
    load-bearing, because the legacy apply_plan adapter and the S4-B/C/D
    handlers call it without schema validation. Tested directly, at its
    own level."""

    def _reject_path(self, relative: str, fragment: str) -> None:
        with self.assertRaises(MaterializationPlanError, msg=f"{relative!r} must be rejected") as ctx:
            canonicalize_workspace_path(self.workspace_root, relative, field_name="probe")
        self.assertIn(fragment, str(ctx.exception))

    def test_rejects_single_dot_segment(self):
        self._reject_path("a/./b", "segments")

    def test_rejects_dotdot_segment(self):
        self._reject_path("a/../b", "segments")

    def test_rejects_empty_segment(self):
        self._reject_path("a//b", "segments")

    def test_rejects_backslash(self):
        self._reject_path("a\\b", "backslashes or NUL")

    def test_rejects_nul_byte(self):
        """Without the raw guard this escapes as an uncaught ValueError from
        Path.resolve() ("embedded null character") -- crash-class, not just
        a weakened check."""
        self._reject_path("a/b\x00c", "backslashes or NUL")

    def test_rejects_absolute_path(self):
        self._reject_path("/etc/passwd", "relative to the workspace root")

    def test_rejects_tilde(self):
        self._reject_path("~/secrets", "relative to the workspace root")

    def test_rejects_symlinked_directory_prefix(self):
        """A resolve()-only containment check cannot catch this: with a
        prefix directory that is itself a symlink, both the candidate and
        the root resolve THROUGH the same link."""
        outside = self.tmp / "outside"
        outside.mkdir()
        (self.workspace_root / "linked").symlink_to(outside)
        self._reject_path("linked/payload", "symlink")

    def test_rejects_symlinked_final_component(self):
        outside = self.tmp / "secret.txt"
        outside.write_text("x")
        (self.workspace_root / "alias").symlink_to(outside)
        self._reject_path("alias", "symlink")

    def test_accepts_ordinary_relative_path(self):
        resolved = canonicalize_workspace_path(
            self.workspace_root, "units/u1/product", field_name="probe"
        )
        self.assertEqual(resolved, (self.workspace_root / "units" / "u1" / "product").resolve())


class TestPlanHash(PlanContractTestBase):
    def test_uses_pinned_canonical_serialization(self):
        """Two independent proofs that this is the PINNED serialization,
        not merely a deterministic one: it equals the pinned recipe, and it
        does NOT equal the default-separator / ensure_ascii variants."""
        plan = self._plan([self._venv_op()], unit_key="u_straße")
        pinned = hashlib.sha256(
            json.dumps(plan, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        ).hexdigest()
        self.assertEqual(compute_plan_hash(plan), pinned)
        self.assertNotEqual(
            compute_plan_hash(plan),
            hashlib.sha256(json.dumps(plan, sort_keys=True).encode()).hexdigest(),
        )
        self.assertNotEqual(
            compute_plan_hash(plan),
            hashlib.sha256(
                json.dumps(plan, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
            ).hexdigest(),
        )

    def test_hash_changes_with_plan_content(self):
        a = self._plan([self._venv_op(dest_path="units/a/.venv")])
        b = self._plan([self._venv_op(dest_path="units/b/.venv")])
        self.assertNotEqual(compute_plan_hash(a), compute_plan_hash(b))


class TestReceiptPublication(PlanContractTestBase):
    def _validated(self, **overrides: object):
        plan = self._plan([self._venv_op()], plan_id="mp_receipt", **overrides)
        return validate_materialization_plan(self.workspace_root, plan)

    def _evidence(self) -> list[dict[str, object]]:
        """Evidence must correspond to the plan's operations, in order."""
        return [{"kind": "venv", "dest_path": "units/u1/.venv"}]

    def test_receipt_schema_is_exact(self):
        validated = self._validated()
        write_materialization_receipt(self.workspace_root, validated, self._evidence())
        receipt = json.loads(materialization_receipt_path(self.workspace_root, "mp_receipt").read_text())
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
        self.assertEqual(receipt["stage"], "MATERIALIZED")
        self.assertEqual(receipt["unit_key"], "u_test")
        self.assertEqual(receipt["workspace_spec_sha256"], self.spec_sha256)
        # Recomputed independently -- a constant-hash mutant dies here.
        self.assertEqual(receipt["plan_hash"], compute_plan_hash(validated.plan))

    def test_publication_requires_a_validated_plan_capability(self):
        """Atlas P1: the writer used to accept the raw live plan. Holding a
        ValidatedPlan IS the proof the contract ran; a raw dict is not."""
        raw = self._plan([self._venv_op()], plan_id="mp_receipt")
        with self.assertRaises(MaterializationPlanError) as ctx:
            write_materialization_receipt(self.workspace_root, raw, self._evidence())
        self.assertIn("requires a ValidatedPlan", str(ctx.exception))

    def test_validated_plan_cannot_be_forged(self):
        """The capability is only mintable by the validator -- otherwise it
        would be a naming convention rather than a guarantee."""
        with self.assertRaises(MaterializationPlanError) as ctx:
            spec_apply.ValidatedPlan(
                plan={},
                plan_id="../../escaped",
                unit_key="u",
                schema_version=1,
                workspace_spec_sha256="a" * 64,
                operation_kinds=(),
                _token=object(),
            )
        self.assertIn("only be constructed by", str(ctx.exception))

    def test_invalid_plan_id_cannot_reach_publication(self):
        """Atlas P1 fruit: plan_id="../../escaped" published
        .grip/escaped.json outside the receipt directory. It can no longer
        be validated, so it can no longer be published."""
        with self.assertRaises(MaterializationPlanError) as ctx:
            validate_materialization_plan(
                self.workspace_root, self._plan([self._venv_op()], plan_id="../../escaped")
            )
        self.assertIn("schema", str(ctx.exception))
        self.assertFalse((self.workspace_root / ".grip" / "escaped.json").exists())

    def test_empty_evidence_cannot_claim_materialized(self):
        """Atlas P1 fruit: a one-operation plan with op_results=[] published
        stage=MATERIALIZED with no evidence at all."""
        with self.assertRaises(MaterializationPlanError) as ctx:
            write_materialization_receipt(self.workspace_root, self._validated(), [])
        self.assertIn("evidence for every operation", str(ctx.exception))
        self.assertFalse(materialization_receipt_path(self.workspace_root, "mp_receipt").exists())

    def test_wrong_kind_evidence_rejected(self):
        with self.assertRaises(MaterializationPlanError) as ctx:
            write_materialization_receipt(
                self.workspace_root, self._validated(), [{"kind": "clone"}]
            )
        self.assertIn("must correspond to its operation", str(ctx.exception))

    def test_direct_identity_field_in_evidence_rejected(self):
        with self.assertRaises(MaterializationPlanError) as ctx:
            write_materialization_receipt(
                self.workspace_root, self._validated(), [{"kind": "venv", "secret": "TOKEN"}]
            )
        self.assertIn("identity-bearing", str(ctx.exception))

    def test_nested_identity_field_in_evidence_rejected(self):
        """Atlas P1 fruit, the real smuggling boundary: the plan's closed
        schema permits no nested object carrier, but the RESULT graph is
        open and is what gets persisted."""
        with self.assertRaises(MaterializationPlanError) as ctx:
            write_materialization_receipt(
                self.workspace_root,
                self._validated(),
                [{"kind": "venv", "nested": {"memory_body": "PRIVATE"}}],
            )
        self.assertIn("identity-bearing", str(ctx.exception))
        self.assertFalse(materialization_receipt_path(self.workspace_root, "mp_receipt").exists())

    def test_publication_order_is_exact(self):
        """Atlas P3: counting two fsync calls does not pin the SEQUENCE --
        moving the parent-directory fsync before os.replace left all five
        prior tests green. This asserts the ordered chain with fd roles,
        distinguishing the file fsync from the directory fsync via fstat,
        so the reorder mutant dies for THIS invariant rather than through
        some unrelated failure."""
        events: list[str] = []
        original_fsync = os.fsync
        original_replace = os.replace

        def tracking_fsync(fd):
            kind = "dir" if stat.S_ISDIR(os.fstat(fd).st_mode) else "file"
            events.append(f"fsync:{kind}")
            return original_fsync(fd)

        def tracking_replace(src, dst, **kwargs):
            events.append("replace")
            return original_replace(src, dst, **kwargs)

        with patch.object(spec_apply.os, "fsync", tracking_fsync):
            with patch.object(spec_apply.os, "replace", tracking_replace):
                write_materialization_receipt(
                    self.workspace_root, self._validated(), self._evidence()
                )

        self.assertEqual(events, ["fsync:file", "replace", "fsync:dir"], events)

    def test_no_receipt_published_when_fsync_fails(self):
        with patch.object(spec_apply.os, "fsync", side_effect=OSError("simulated fsync failure")):
            with self.assertRaises(OSError):
                write_materialization_receipt(
                    self.workspace_root, self._validated(), self._evidence()
                )
        self.assertFalse(materialization_receipt_path(self.workspace_root, "mp_receipt").exists())

    def test_publication_is_atomic_replace_not_direct_write(self):
        """Asserting only "no temp file left behind" cannot distinguish
        atomic publication from a direct write -- a direct write also
        trivially leaves no temp file. Failing the replace step itself can."""
        original_replace = os.replace

        def failing_replace(src, dst, **kwargs):
            if "materialization" in str(src):
                raise OSError("simulated replace failure")
            return original_replace(src, dst, **kwargs)

        with patch.object(spec_apply.os, "replace", failing_replace):
            with self.assertRaises(OSError):
                write_materialization_receipt(
                    self.workspace_root, self._validated(), self._evidence()
                )
        self.assertFalse(materialization_receipt_path(self.workspace_root, "mp_receipt").exists())

    def test_no_temp_file_left_behind_on_success(self):
        write_materialization_receipt(self.workspace_root, self._validated(), self._evidence())
        state_dir = self.workspace_root / ".grip" / "state" / "materialization"
        self.assertEqual(list(state_dir.glob("*.tmp-*")), [])

    def test_temp_file_failure_leaves_no_residue(self):
        with patch.object(spec_apply.os, "fsync", side_effect=OSError("boom")):
            with self.assertRaises(OSError):
                write_materialization_receipt(
                    self.workspace_root, self._validated(), self._evidence()
                )
        state_dir = self.workspace_root / ".grip" / "state" / "materialization"
        self.assertEqual(list(state_dir.glob("*.tmp-*")), [])


class TestDerivedPathHardening(PlanContractTestBase):
    """Atlas P2: §6.2.1 #2 applies to the A-owned DERIVED paths (canonical
    WorkspaceSpec, receipt directory, receipt temp file), not only to
    operation paths. All three probes succeeded before this closure."""

    def test_symlinked_workspace_spec_rejected(self):
        """A symlink at .grip/workspace_spec.toml pointing outside the team
        root was accepted whenever its bytes hashed to the declared value.
        The hash confirms CONTENT; it says nothing about whether the file
        read is inside the workspace."""
        outside = self.tmp / "outside_spec.toml"
        outside.write_text('workspace_name = "outside"\n')
        outside_sha = hashlib.sha256(outside.read_bytes()).hexdigest()

        spec_path = workspace_spec_path(self.workspace_root)
        spec_path.unlink()
        spec_path.symlink_to(outside)

        with self.assertRaises(MaterializationPlanError) as ctx:
            validate_materialization_plan(
                self.workspace_root,
                self._plan([self._venv_op()], workspace_spec_sha256=outside_sha),
            )
        self.assertIn("symlink", str(ctx.exception))

    def test_symlinked_receipt_directory_rejected(self):
        """A symlinked .grip/state/materialization published the terminal
        receipt outside the team root entirely."""
        outside_dir = self.tmp / "outside_receipts"
        outside_dir.mkdir()
        state_dir = self.workspace_root / ".grip" / "state"
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "materialization").symlink_to(outside_dir)

        validated = validate_materialization_plan(
            self.workspace_root, self._plan([self._venv_op()], plan_id="mp_escape")
        )
        with self.assertRaises(MaterializationPlanError) as ctx:
            write_materialization_receipt(
                self.workspace_root, validated, [{"kind": "venv"}]
            )
        self.assertIn("symlink", str(ctx.exception))
        self.assertEqual(list(outside_dir.iterdir()), [])

    def test_pre_created_temp_symlink_is_not_followed(self):
        """The temp name is predictable (mp_<id>.json.tmp-<pid>), so a plain
        open() followed a pre-created symlink, overwrote the external
        target, and then published that symlink as the final receipt.
        O_EXCL|O_NOFOLLOW refuses instead."""
        outside_target = self.tmp / "victim.txt"
        outside_target.write_text("ORIGINAL")

        receipt_dir = self.workspace_root / ".grip" / "state" / "materialization"
        receipt_dir.mkdir(parents=True, exist_ok=True)
        validated = validate_materialization_plan(
            self.workspace_root, self._plan([self._venv_op()], plan_id="mp_receipt")
        )
        (receipt_dir / f"mp_receipt.json.tmp-{os.getpid()}").symlink_to(outside_target)

        with self.assertRaises(OSError):
            write_materialization_receipt(
                self.workspace_root, validated, [{"kind": "venv"}]
            )
        self.assertEqual(outside_target.read_text(), "ORIGINAL")
        self.assertFalse(materialization_receipt_path(self.workspace_root, "mp_receipt").exists())


if __name__ == "__main__":
    unittest.main()
