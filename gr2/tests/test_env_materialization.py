"""venv + editable_install executor tests (S4-D).

The last two materialization handlers. With these the A -> B -> C -> D path is
complete.

Contract: MaterializationPlan v1 environment invariant 6 and
          acceptance fruit 10/11/12.

Prototype posture (Layne 2026-07-27): working end-to-end, not exhaustively
hardened. The probes below cover the guards the spec names explicitly; broader
adversarial coverage is filed as deferred-hardening.

INVARIANT 6 NAMES ITS OWN MASK, which is unusual and worth reading closely:
"FILE PRESENCE ALONE IS NOT VENV EVIDENCE." `pyvenv.cfg exists` is the cheap
check that LOOKS like venv validation and stays true for a venv whose
interpreter was deleted, whose base Python moved, or which was copied to a new
path. Only running the interpreter can tell, which is why the spec demands a
bounded probe rather than a stat.

The probe's two assertions are orthogonal, and each is the only thing that can
see its own failure:
  - sys.prefix == the declared path catches a venv that RUNS BUT IS NOT THIS
    ONE (copied or moved).
  - sys.base_prefix != sys.prefix catches something that is NOT A VENV AT ALL;
    a bare system interpreter passes the prefix check trivially, because for it
    the two values are the same.

FRUIT 11's `python -I` IS LOAD-BEARING. Without isolation an import can be
satisfied by the working directory or an inherited PYTHONPATH, so a passing
import would prove nothing about what the venv installed. There is a probe
below that demonstrates exactly that gap rather than asserting it.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

from gr2.python_cli.env_exec import (
    EnvExecutionError,
    execute_editable_install_operation,
    execute_venv_operation,
    import_origin,
    read_direct_url,
    venv_interpreter,
    verify_venv,
)
from gr2.python_cli.spec_apply import (
    validate_materialization_plan,
    workspace_spec_path,
    write_materialization_receipt,
)

UV = shutil.which("uv")
PYVER = f"{sys.version_info[0]}.{sys.version_info[1]}"


@unittest.skipIf(UV is None, "uv is a section 9.2 prerequisite and is not installed")
class EnvExecTestBase(unittest.TestCase):
    def setUp(self):
        import tempfile

        self.tmp = Path(tempfile.mkdtemp())
        self.workspace_root = self.tmp / "workspace"
        self.workspace_root.mkdir(parents=True)
        self.spec_sha256 = self._write_workspace_spec()

        self.venv_rel = "units/u_test/home/.venv"
        self.venv_path = self.workspace_root / self.venv_rel

        # A real installable package inside the unit's clone.
        self.source_rel = "units/u_test/repos/product"
        self.source = self.workspace_root / self.source_rel
        (self.source / "src" / "unitpkg").mkdir(parents=True)
        (self.source / "src" / "unitpkg" / "__init__.py").write_text(
            "VALUE = 'from the unit clone'\n"
        )
        (self.source / "pyproject.toml").write_text(
            "[build-system]\n"
            'requires = ["setuptools>=68"]\n'
            'build-backend = "setuptools.build_meta"\n\n'
            "[project]\n"
            'name = "unitpkg"\n'
            'version = "0.1.0"\n\n'
            "[project.optional-dependencies]\n"
            "extra = []\n\n"
            "[tool.setuptools.packages.find]\n"
            'where = ["src"]\n'
        )

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write_workspace_spec(self, content: str = 'workspace_name = "test"\n') -> str:
        spec_path = workspace_spec_path(self.workspace_root)
        spec_path.parent.mkdir(parents=True, exist_ok=True)
        spec_path.write_text(content)
        return hashlib.sha256(spec_path.read_bytes()).hexdigest()

    def _venv_op(self, **overrides: object) -> dict[str, object]:
        op: dict[str, object] = {
            "kind": "venv",
            "dest_path": self.venv_rel,
            "engine": "uv",
            "python": sys.executable,
        }
        op.update(overrides)
        return op

    def _editable_op(self, **overrides: object) -> dict[str, object]:
        op: dict[str, object] = {
            "kind": "editable_install",
            "venv_path": self.venv_rel,
            "source_path": self.source_rel,
            "extras": [],
        }
        op.update(overrides)
        return op

    def _validated(self, operations: list[dict[str, object]]):
        return validate_materialization_plan(
            self.workspace_root,
            {
                "schema_version": 1,
                "plan_id": "mp_test",
                "unit_key": "u_test",
                "workspace_spec_sha256": self.spec_sha256,
                "operations": operations,
            },
        )

    def _make_venv(self) -> dict[str, object]:
        return execute_venv_operation(
            self._validated([self._venv_op()]), 0, workspace_root=self.workspace_root
        )

    def _install(self, **overrides) -> dict[str, object]:
        validated = self._validated([self._venv_op(), self._editable_op(**overrides)])
        execute_venv_operation(validated, 0, workspace_root=self.workspace_root)
        return execute_editable_install_operation(
            validated, 1, workspace_root=self.workspace_root
        )


class TestVenvCreation(EnvExecTestBase):
    def test_creates_a_venv_with_the_declared_interpreter(self):
        """Acceptance fruit 10."""
        evidence = self._make_venv()

        self.assertTrue(venv_interpreter(self.venv_path).exists())
        self.assertEqual(evidence["kind"], "venv")
        self.assertEqual(evidence["interpreter_version"], PYVER)
        self.assertIs(evidence["reused"], False)

    def test_an_existing_healthy_venv_is_reused_and_still_validated(self):
        """Invariant 5's rule generalized: path ABSENCE must not be the
        condition that makes validation reachable. The venv is re-probed on
        every apply, not only when it is created."""
        self._make_venv()
        evidence = self._make_venv()
        self.assertIs(evidence["reused"], True)

    def test_evidence_is_receipt_shaped(self):
        validated = self._validated([self._venv_op()])
        evidence = execute_venv_operation(validated, 0, workspace_root=self.workspace_root)
        receipt_path = write_materialization_receipt(
            self.workspace_root, validated, [evidence]
        )
        receipt = json.loads(receipt_path.read_text())
        self.assertEqual(receipt["operations"][0]["kind"], "venv")


class TestInvariantSixProbe(EnvExecTestBase):
    """'File presence alone is not venv evidence' -- the spec naming its own mask."""

    def test_pyvenv_cfg_alone_does_not_satisfy_the_check(self):
        """The cheap check that LOOKS like validation. pyvenv.cfg is present and
        parseable; the interpreter is gone. A stat-based guard says healthy."""
        self._make_venv()
        interpreter = venv_interpreter(self.venv_path)
        interpreter.unlink()

        self.assertTrue(
            (self.venv_path / "pyvenv.cfg").is_file(),
            "premise: the cheap check still passes",
        )
        with self.assertRaises(EnvExecutionError) as ctx:
            verify_venv(self.venv_path)
        self.assertIn("no interpreter", str(ctx.exception))

    def test_the_prefix_assertions_cannot_fire_on_current_cpython(self):
        """PREMISE, and an honest correction to how invariant 6 reads.

        The spec asks the probe to assert `sys.prefix == the declared venv path`
        and `sys.base_prefix != sys.prefix`. Both are kept in verify_venv
        because the spec mandates them -- but on CPython 3.11+ NEITHER CAN FAIL
        once pyvenv.cfg exists, and that was established by running it rather
        than by reading the docs:

          - pyvenv.cfg next to bin/python is LITERALLY what makes a venv, so
            base_prefix always differs -- even when the file contains garbage.
          - sys.prefix is derived from the directory you INVOKED THROUGH, not
            from anything recorded inside, so it equals the declared path even
            when bin/python symlinks to a different venv's interpreter, and a
            COPIED venv is self-consistent at its new location.

        So the assertions are defence-in-depth against a Python that behaves
        differently, not live guards. They are documented as such rather than
        left looking like protection, and this test is what would notice if
        CPython ever changed: it FAILS, and the failure says the guards became
        reachable.

        What the probe genuinely catches is the reachable set -- interpreter
        missing, not executable, failing, or hanging -- covered above."""
        self._make_venv()

        decoy = self.workspace_root / "units" / "u_test" / "not-really-a-venv"
        (decoy / "bin").mkdir(parents=True)
        (decoy / "pyvenv.cfg").write_text("this is not a valid config\n")
        os.symlink(venv_interpreter(self.venv_path), venv_interpreter(decoy))

        probe = json.loads(
            subprocess.run(
                [str(venv_interpreter(decoy)), "-I", "-c",
                 "import sys,json;print(json.dumps({'p':sys.prefix,'b':sys.base_prefix}))"],
                capture_output=True, text=True, check=True,
            ).stdout
        )
        self.assertNotEqual(
            probe["b"], probe["p"],
            "CPython no longer treats a garbage pyvenv.cfg as a venv -- the "
            "base_prefix assertion in verify_venv is now REACHABLE and deserves "
            "a real probe",
        )
        self.assertEqual(
            Path(probe["p"]).resolve(), decoy.resolve(),
            "CPython no longer derives sys.prefix from the invocation path -- the "
            "prefix assertion in verify_venv is now REACHABLE and deserves a real "
            "probe",
        )
        # And the consequence: verify_venv accepts it, because every guard that
        # CAN fire passes. That is the honest state of invariant 6 today.
        verify_venv(decoy)


class TestEditableInstall(EnvExecTestBase):
    def test_installs_editable_and_records_pep610_metadata(self):
        """Acceptance fruit 12."""
        evidence = self._install()

        self.assertEqual(evidence["kind"], "editable_install")
        self.assertIs(evidence["editable"], True)
        self.assertEqual(evidence["distribution"], "unitpkg")

        data = read_direct_url(self.venv_path, self.source)
        self.assertTrue(data["dir_info"]["editable"])
        self.assertTrue(str(data["url"]).startswith("file://"))

    def test_import_resolves_inside_the_unit_clone(self):
        """Acceptance fruit 11."""
        self._install()
        origin = import_origin(self.venv_path, "unitpkg")
        self.assertTrue(
            Path(origin).resolve().is_relative_to(self.source.resolve()),
            f"unitpkg resolved to {origin}, outside the unit clone {self.source}",
        )

    def test_isolation_is_what_makes_that_claim_real(self):
        """`python -I` is load-bearing, demonstrated rather than asserted.

        Without isolation, an inherited PYTHONPATH satisfies an import that the
        venv never installed -- so a non-isolated probe cannot distinguish
        "this unit installed it" from "it happened to be on the path". That is
        why fruit 11 specifies -I.

        Demonstrated with a module the venv does NOT have. An earlier version of
        this probe tried to shadow the INSTALLED package and failed: modern
        editable installs register a MetaPathFinder, which runs ahead of sys.path
        entirely, so PYTHONPATH loses. Shadowing proves nothing; presence does."""
        self._install()
        decoy = self.tmp / "decoy"
        (decoy / "neverinstalled").mkdir(parents=True)
        (decoy / "neverinstalled" / "__init__.py").write_text("VALUE = 'decoy'\n")

        env = {**os.environ, "PYTHONPATH": str(decoy)}
        script = "import neverinstalled,os;print(os.path.realpath(neverinstalled.__file__))"
        interpreter = str(venv_interpreter(self.venv_path))

        leaky = subprocess.run(
            [interpreter, "-c", script], capture_output=True, text=True, env=env, check=False
        )
        isolated = subprocess.run(
            [interpreter, "-I", "-c", script], capture_output=True, text=True, env=env, check=False
        )

        self.assertEqual(
            leaky.returncode, 0,
            "premise: without -I an inherited PYTHONPATH satisfies the import",
        )
        self.assertNotEqual(
            isolated.returncode, 0,
            "-I must ignore PYTHONPATH -- otherwise 'the import resolves' says "
            "nothing about what this venv installed",
        )
        # And the real claim, on a module the unit genuinely installed.
        self.assertTrue(
            Path(import_origin(self.venv_path, "unitpkg")).resolve()
            .is_relative_to(self.source.resolve())
        )

    def test_extras_are_passed_through(self):
        evidence = self._install(extras=["extra"])
        self.assertEqual(evidence["extras"], ["extra"])

    def test_installing_into_a_directory_that_is_not_a_venv_is_refused(self):
        """Section 9.2: never mutate the operator's Python environment.
        Installing into something that merely looks like a venv is how that
        happens, so the venv is verified BEFORE the install runs."""
        validated = self._validated([self._venv_op(), self._editable_op()])
        self.venv_path.mkdir(parents=True)
        (self.venv_path / "pyvenv.cfg").write_text("home = /usr\n")

        with self.assertRaises(EnvExecutionError) as ctx:
            execute_editable_install_operation(
                validated, 1, workspace_root=self.workspace_root
            )
        self.assertIn("no interpreter", str(ctx.exception))

    def test_a_source_with_nothing_to_install_is_refused(self):
        validated = self._validated([self._venv_op(), self._editable_op()])
        execute_venv_operation(validated, 0, workspace_root=self.workspace_root)
        (self.source / "pyproject.toml").unlink()

        with self.assertRaises(EnvExecutionError) as ctx:
            execute_editable_install_operation(
                validated, 1, workspace_root=self.workspace_root
            )
        self.assertIn("nothing to install", str(ctx.exception))


class TestExecutorBinding(EnvExecTestBase):
    def test_a_tampered_capability_cannot_execute(self):
        validated = self._validated([self._venv_op()])
        object.__setattr__(validated, "plan_id", "mp_swapped")
        with self.assertRaises(Exception) as ctx:
            execute_venv_operation(validated, 0, workspace_root=self.workspace_root)
        self.assertIn("capability is invalid", str(ctx.exception))

    def test_a_wrong_kind_is_refused_by_index(self):
        validated = self._validated([self._venv_op(), self._editable_op()])
        with self.assertRaises(EnvExecutionError) as ctx:
            execute_editable_install_operation(
                validated, 0, workspace_root=self.workspace_root
            )
        self.assertIn("is kind 'venv'", str(ctx.exception))

    def test_executing_against_a_different_workspace_root_is_rejected(self):
        validated = self._validated([self._venv_op()])
        other = self.tmp / "other-workspace"
        spec = workspace_spec_path(other)
        spec.parent.mkdir(parents=True, exist_ok=True)
        spec.write_text('workspace_name = "other"\n')

        with self.assertRaises(EnvExecutionError) as ctx:
            execute_venv_operation(validated, 0, workspace_root=other)
        self.assertIn("WorkspaceSpec", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
