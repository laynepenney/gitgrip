"""Receipt-keyed staged-input cleanup (S4 cleanup slice).

Carved out of S4-C by Stromus (2026-07-27) so a DELETE never shares a review
surface with a copy. C stages, projects, and publishes a receipt, and deletes
nothing. This slice is the only thing in the system permitted to remove a
staged input.

Spec: config/design/zero-to-team-gr2-materialization-spec-2026-07-26.md
      section 6.2.1 invariant 8.

    "Do not delete a staged project-file input until the final materialization
    receipt containing that operation's evidence has been atomically published
    and made durable. A successful destination write or in-memory operation
    result is not acknowledgement. If cleanup is interrupted after receipt
    publication, rerun performs the idempotent cleanup from the verified
    receipt."


THE PAIRED INVARIANT WITH C -- read this before the tests
---------------------------------------------------------
Cleanup deletes the ONLY remaining copy of the projected content. That is
survivable for exactly one reason: C can prove a projection is current from the
DESTINATION alone, by hashing it against `source_sha256`, so it never needs the
staged input again.

    Cleanup may delete a staged input only because C can re-establish currency
    from the destination alone. The two slices are safe only TOGETHER.

Neither slice can state that on its own, which is precisely why it is the thing
most likely to rot. `TestCrossSliceSeam` runs the whole sequence -- project ->
receipt -> cleanup -> project again -- and is the probe for the seam itself. If
someone later "simplifies" C to require its source, that test is what fails,
not a cleanup test and not a C test.


WHERE THE AUTHORITY COMES FROM, AND WHY IT IS SPLIT
---------------------------------------------------
The receipt answers "MAY I delete?" -- is this plan durably acknowledged.
The frozen ValidatedPlan answers "WHAT may I delete?" -- the validated paths.

The obvious design reads `source_path` out of the receipt. That is wrong, and
it is validation-vs-use masking one more time: nothing in the receipt is signed,
so anyone who can write that file can set `plan_hash` correctly (it is a public
value) and put an arbitrary path in the evidence. Those path strings were
validated as PLAN fields; the receipt is a different artifact read at a later
time, and its bytes are not the validated ones.

Invariant 8 says cleanup runs "from the VERIFIED receipt" -- verification is the
receipt's job. Taking the paths from the immutable capability instead loses
nothing, because a plan_hash match forecloses any receipt/plan disagreement.


Masking analysis, before implementation:

  1. "Delete what the receipt names" is masked by the happy path, where the
     receipt and the plan name the same files. Only a TAMPERED receipt
     separates them.
  2. "Never scan the filesystem" is masked by the happy path too: globbing
     .grip/staging/inputs/* removes exactly the right files when the directory
     holds only this plan's inputs. The probe needs an unrelated file sitting
     in that directory.
  3. plan_hash matching is masked by plan_id matching -- a re-emitted plan for
     the same unit can carry the same opaque plan_id with different operations.
     The probe must reuse the plan_id and change the content.
     CORRECTED AFTER IMPLEMENTATION: the plan_id comparison is itself masked by
     the CANONICAL-PATH guard, because the canonical receipt path is DERIVED
     from plan_id -- another plan's receipt is at the wrong path by
     construction and is refused before its contents are read. So the input
     that reaches the plan_id comparison is a receipt sitting at the RIGHT path
     with a tampered plan_id inside, which is also the shape tampering really
     takes: the filename is the one part an attacker cannot change without
     moving the file out of the canonical location. Both probes exist.
  4. The regular-file check is masked by unlink() itself: unlink on a symlink
     removes the LINK, which is already safe. The input that actually matters
     is a DIRECTORY, where the tempting fix is rmtree and the correct answer is
     to refuse.
"""
from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path

from gr2.python_cli.file_exec import execute_project_file_operation
from gr2.python_cli.spec_apply import (
    validate_materialization_plan,
    workspace_spec_path,
    write_materialization_receipt,
)
from gr2.python_cli.staging_cleanup import (
    StagingCleanupError,
    cleanup_staged_inputs,
)

FOUNDATION = b"# Foundation\n\ncharim toward the most high.\n"


class StagingCleanupTestBase(unittest.TestCase):
    def setUp(self):
        import tempfile

        self.tmp = Path(tempfile.mkdtemp())
        self.workspace_root = self.tmp / "workspace"
        self.workspace_root.mkdir(parents=True)
        self.spec_sha256 = self._write_workspace_spec()

        self.source_rel = ".grip/staging/inputs/a_7f3a9c"
        self.source_path = self.workspace_root / self.source_rel
        self.source_path.parent.mkdir(parents=True, exist_ok=True)
        self.source_path.write_bytes(FOUNDATION)
        self.source_sha256 = hashlib.sha256(FOUNDATION).hexdigest()

        self.dest_rel = "units/u_test/home/FOUNDATION.md"
        self.dest_path = self.workspace_root / self.dest_rel

    def tearDown(self):
        import shutil

        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write_workspace_spec(self, content: str = 'workspace_name = "test"\n') -> str:
        spec_path = workspace_spec_path(self.workspace_root)
        spec_path.parent.mkdir(parents=True, exist_ok=True)
        spec_path.write_text(content)
        return hashlib.sha256(spec_path.read_bytes()).hexdigest()

    def _op(self, **overrides: object) -> dict[str, object]:
        op: dict[str, object] = {
            "kind": "project_file",
            "source_path": self.source_rel,
            "dest_path": self.dest_rel,
            "source_sha256": self.source_sha256,
            "mode": "copy",
        }
        op.update(overrides)
        return op

    def _validated(self, operations=None, **plan_overrides):
        plan: dict[str, object] = {
            "schema_version": 1,
            "plan_id": "mp_test",
            "unit_key": "u_test",
            "workspace_spec_sha256": self.spec_sha256,
            "operations": operations if operations is not None else [self._op()],
        }
        plan.update(plan_overrides)
        return validate_materialization_plan(self.workspace_root, plan)

    def _project_and_receipt(self, validated=None):
        """The state cleanup is entitled to act on: projected + acknowledged."""
        validated = validated if validated is not None else self._validated()
        evidence = execute_project_file_operation(
            validated, 0, workspace_root=self.workspace_root
        )
        receipt_path = write_materialization_receipt(
            self.workspace_root, validated, [evidence]
        )
        return validated, receipt_path

    def _cleanup(self, validated, receipt_path):
        return cleanup_staged_inputs(
            validated, workspace_root=self.workspace_root, receipt_path=receipt_path
        )


class TestAcknowledgementGate(StagingCleanupTestBase):
    def test_removes_staged_inputs_once_the_receipt_is_durable(self):
        validated, receipt_path = self._project_and_receipt()

        removed = self._cleanup(validated, receipt_path)

        self.assertEqual(removed, [self.source_rel])
        self.assertFalse(self.source_path.exists())
        self.assertEqual(self.dest_path.read_bytes(), FOUNDATION)

    def test_refuses_when_no_receipt_exists(self):
        """Invariant 8's core prohibition. The projection has succeeded and the
        destination is correct -- and that is explicitly NOT acknowledgement."""
        validated = self._validated()
        execute_project_file_operation(validated, 0, workspace_root=self.workspace_root)

        with self.assertRaises(StagingCleanupError) as ctx:
            self._cleanup(
                validated,
                self.workspace_root / ".grip" / "state" / "materialization" / "mp_test.json",
            )
        self.assertIn("no durable receipt", str(ctx.exception))
        self.assertTrue(self.source_path.exists())

    def test_refuses_a_receipt_from_another_plans_path(self):
        """Handing cleanup someone else's receipt. Caught by the canonical-path
        guard rather than by the plan_id comparison, because the canonical path
        is DERIVED from plan_id -- another plan's receipt is at the wrong path
        by construction, and is refused before its contents are read."""
        validated, receipt_path = self._project_and_receipt()
        other = self._validated(plan_id="mp_other")

        with self.assertRaises(StagingCleanupError) as ctx:
            self._cleanup(other, receipt_path)
        self.assertIn("not the canonical receipt", str(ctx.exception))
        self.assertTrue(self.source_path.exists())

    def test_refuses_a_receipt_whose_recorded_plan_id_disagrees(self):
        """The plan_id CONTENT check, at its own level. The path guard above
        cannot see this one: the receipt sits exactly where it belongs, and only
        its contents disagree -- which is the shape tampering actually takes,
        since the filename is the one part an attacker cannot change without
        moving the file out of the canonical location."""
        validated, receipt_path = self._project_and_receipt()
        receipt = json.loads(receipt_path.read_text())
        receipt["plan_id"] = "mp_someone_else"
        receipt_path.write_text(json.dumps(receipt))

        with self.assertRaises(StagingCleanupError) as ctx:
            self._cleanup(validated, receipt_path)
        self.assertIn("does not acknowledge", str(ctx.exception))
        self.assertTrue(self.source_path.exists())

    def test_refuses_a_receipt_whose_plan_hash_disagrees(self):
        """plan_id is an opaque token that may repeat across successive plans
        for the same unit. Matching it alone would let yesterday's receipt
        authorise today's deletions, so the bound is the CONTENT hash."""
        validated, receipt_path = self._project_and_receipt()
        receipt = json.loads(receipt_path.read_text())
        receipt["plan_hash"] = "0" * 64
        receipt_path.write_text(json.dumps(receipt))

        with self.assertRaises(StagingCleanupError) as ctx:
            self._cleanup(validated, receipt_path)
        self.assertIn("plan_hash", str(ctx.exception))
        self.assertTrue(self.source_path.exists())

    def test_refuses_a_receipt_that_is_not_in_the_canonical_location(self):
        """The receipt is the authority to delete. Accepting one from an
        arbitrary path makes the authority forgeable by anyone who can write a
        file anywhere in the workspace."""
        validated, receipt_path = self._project_and_receipt()
        planted = self.workspace_root / "units" / "u_test" / "planted-receipt.json"
        planted.parent.mkdir(parents=True, exist_ok=True)
        planted.write_text(receipt_path.read_text())

        with self.assertRaises(StagingCleanupError) as ctx:
            self._cleanup(validated, planted)
        self.assertIn("canonical", str(ctx.exception))
        self.assertTrue(self.source_path.exists())


class TestPathsComeFromThePlanNotTheReceipt(StagingCleanupTestBase):
    def test_a_tampered_receipt_cannot_redirect_the_delete(self):
        """The centre of this slice. Nothing in the receipt is signed, so an
        attacker who can write it can keep plan_hash correct -- it is a public
        value -- and point the evidence anywhere. Paths must come from the
        frozen, validated capability; the receipt only proves acknowledgement."""
        validated, receipt_path = self._project_and_receipt()
        victim = self.workspace_root / "units" / "u_test" / "precious.md"
        victim.parent.mkdir(parents=True, exist_ok=True)
        victim.write_text("someone's real work\n")

        receipt = json.loads(receipt_path.read_text())
        receipt["operations"][0]["source_path"] = "units/u_test/precious.md"
        receipt_path.write_text(json.dumps(receipt))

        self._cleanup(validated, receipt_path)

        self.assertTrue(victim.exists(), "a tampered receipt redirected the delete")
        self.assertFalse(self.source_path.exists())

    def test_unrelated_files_in_the_staging_directory_are_untouched(self):
        """'Recover from the receipt, not the filesystem.' Globbing
        .grip/staging/inputs/* removes exactly the right files whenever the
        directory holds only this plan's inputs, so the happy path cannot tell
        the two implementations apart. Another plan's pending input can."""
        validated, receipt_path = self._project_and_receipt()
        bystander = self.source_path.parent / "a_other_plan"
        bystander.write_bytes(b"another plan's staged input, not yet projected\n")

        removed = self._cleanup(validated, receipt_path)

        self.assertEqual(removed, [self.source_rel])
        self.assertTrue(
            bystander.exists(),
            "cleanup scanned the directory instead of reading the plan",
        )

    def test_the_projected_destination_is_never_removed(self):
        validated, receipt_path = self._project_and_receipt()
        self._cleanup(validated, receipt_path)
        self.assertEqual(self.dest_path.read_bytes(), FOUNDATION)


class TestIdempotenceAndPartialFailure(StagingCleanupTestBase):
    def test_a_second_cleanup_is_a_no_op_not_an_error(self):
        """Invariant 8's tail: an interrupted cleanup is completed on rerun.
        That only works if a completed cleanup is also safe to repeat, since
        neither the caller nor the receipt records which state it is in."""
        validated, receipt_path = self._project_and_receipt()
        self.assertEqual(self._cleanup(validated, receipt_path), [self.source_rel])
        self.assertEqual(self._cleanup(validated, receipt_path), [])

    def test_an_already_absent_input_does_not_block_its_siblings(self):
        """The interrupted-midway state, which is the one invariant 8 actually
        describes: some inputs already gone, some still present."""
        second_rel = ".grip/staging/inputs/a_second"
        second_path = self.workspace_root / second_rel
        second_path.write_bytes(b"second staged input\n")
        second_dest = "units/u_test/home/SECOND.md"
        validated = self._validated(
            [
                self._op(),
                self._op(
                    source_path=second_rel,
                    dest_path=second_dest,
                    source_sha256=hashlib.sha256(b"second staged input\n").hexdigest(),
                ),
            ]
        )
        results = [
            execute_project_file_operation(validated, i, workspace_root=self.workspace_root)
            for i in (0, 1)
        ]
        receipt_path = write_materialization_receipt(self.workspace_root, validated, results)
        self.source_path.unlink()  # interrupted after removing the first

        removed = self._cleanup(validated, receipt_path)

        self.assertEqual(removed, [second_rel])
        self.assertFalse(second_path.exists())

    def test_a_staged_path_that_became_a_directory_is_refused_not_recursed(self):
        """Between C's execute and this call the path could become a directory.
        unlink() on a symlink removes the link and is already safe; a directory
        is the input that matters, because the tempting fix is rmtree and the
        correct answer is to refuse. Cleanup must never escalate."""
        validated, receipt_path = self._project_and_receipt()
        self.source_path.unlink()
        self.source_path.mkdir()
        (self.source_path / "someone-elses-file").write_text("x\n")

        with self.assertRaises(StagingCleanupError) as ctx:
            self._cleanup(validated, receipt_path)
        self.assertIn("regular file", str(ctx.exception))
        self.assertTrue((self.source_path / "someone-elses-file").exists())


class TestCrossSliceSeam(StagingCleanupTestBase):
    def test_projection_survives_cleanup_and_a_later_apply_still_succeeds(self):
        """THE PAIRED INVARIANT, and the probe for the seam itself.

        Cleanup removes the only remaining source. That is survivable solely
        because C proves currency from the destination alone. Run the whole
        sequence -- project, receipt, cleanup, project again -- because neither
        slice's own suite can see this: C's tests never delete, and cleanup's
        tests never re-apply.

        If someone later 'simplifies' C to require its staged input, this is
        what fails."""
        validated, receipt_path = self._project_and_receipt()
        self._cleanup(validated, receipt_path)
        self.assertFalse(self.source_path.exists())

        evidence = execute_project_file_operation(
            self._validated(), 0, workspace_root=self.workspace_root
        )

        self.assertIs(evidence["written"], False)
        self.assertEqual(self.dest_path.read_bytes(), FOUNDATION)

    def test_cleanup_after_a_destroyed_projection_cannot_be_recovered_from(self):
        """The honest edge of the pairing, pinned so nobody discovers it in
        production. Once cleanup has run, the staged input is gone; if the
        destination is then destroyed, this workspace cannot re-project and the
        next apply must FAIL LOUDLY rather than leave a silently absent
        destination. gr2 does not re-stage, and its job here is to refuse to
        pretend it can."""
        validated, receipt_path = self._project_and_receipt()
        self._cleanup(validated, receipt_path)
        self.dest_path.unlink()

        from gr2.python_cli.file_exec import ProjectFileExecutionError

        with self.assertRaises(ProjectFileExecutionError) as ctx:
            execute_project_file_operation(
                self._validated(), 0, workspace_root=self.workspace_root
            )
        self.assertIn("staged input", str(ctx.exception))


class TestExecutorBinding(StagingCleanupTestBase):
    def test_a_tampered_capability_cannot_authorise_a_delete(self):
        validated, receipt_path = self._project_and_receipt()
        object.__setattr__(validated, "plan_id", "mp_swapped")

        with self.assertRaises(Exception) as ctx:
            self._cleanup(validated, receipt_path)
        self.assertIn("capability is invalid", str(ctx.exception))
        self.assertTrue(self.source_path.exists())

    def test_a_copied_capability_cannot_authorise_a_delete(self):
        import dataclasses

        validated, receipt_path = self._project_and_receipt()
        with self.assertRaises(Exception) as ctx:
            self._cleanup(dataclasses.replace(validated), receipt_path)
        self.assertIn("capability is invalid", str(ctx.exception))
        self.assertTrue(self.source_path.exists())

    def test_cleanup_against_a_different_workspace_root_is_rejected(self):
        validated, receipt_path = self._project_and_receipt()
        other_root = self.tmp / "other-workspace"
        other_spec = workspace_spec_path(other_root)
        other_spec.parent.mkdir(parents=True, exist_ok=True)
        other_spec.write_text('workspace_name = "other"\n')

        with self.assertRaises(StagingCleanupError) as ctx:
            cleanup_staged_inputs(
                validated, workspace_root=other_root, receipt_path=receipt_path
            )
        self.assertIn("WorkspaceSpec", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
