"""Neutral launch primitive (S5) -- prove the team WAKES.

Design: `synapt-spawn-premium-compiler-2026-07-27.md` §2 (LaunchPlan is the
opaque tier) and §5 (cold start, no `--resume`).

Three probes here exist because the HAPPY PATH CANNOT SEE THEIR FAILURES, which
is the shape this sprint kept finding:

  1. "Never persist env values" -- nothing writes them on the happy path, so a
     test that merely launches passes while a launch-script implementation
     (gr1's current one) also passes. The probe SEARCHES THE FILESYSTEM for a
     value instead of trusting that nothing wrote it.
  2. "Started" is not "running" -- a process that exits instantly produces the
     same successful spawn as one that came up healthy. Same proxy invariant 6
     names when it says file presence is not venv evidence.
  3. The env allowlist has TWO directions -- a value for an undeclared key, and
     a declared key with no value. Probing one leaves the other unguarded.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from gr2.python_cli.launch_exec import (
    LaunchEntry,
    LaunchExecutionError,
    launch_team,
    launch_unit,
)

SECRET = "SYNAPT-AGENT-ID-VALUE-THAT-MUST-NEVER-TOUCH-DISK"


class LaunchTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.ws = self.tmp / "workspace"
        self.unit = self.ws / "units" / "u_abc123" / "home"
        self.unit.mkdir(parents=True)
        self.pids: list[int] = []

    def tearDown(self):
        for pid in self.pids:
            try:
                os.killpg(os.getpgid(pid), 15)
            except (ProcessLookupError, PermissionError):
                pass
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _entry(self, **overrides) -> LaunchEntry:
        data = {
            "unit_key": "u_abc123",
            "workdir": "units/u_abc123/home",
            # A process that stays alive, so liveness is a real observation.
            "argv": [sys.executable, "-c", "import time; time.sleep(30)"],
            "env_allowlist_keys": ["SYNAPT_AGENT_ID"],
        }
        data.update(overrides)
        return LaunchEntry.from_mapping(data)

    def _launch(self, entry=None, env=None):
        ev = launch_unit(
            entry or self._entry(),
            workspace_root=self.ws,
            env_values=env if env is not None else {"SYNAPT_AGENT_ID": SECRET},
        )
        self.pids.append(int(ev["pid"]))
        return ev


class TestLaunchMeansAlive(LaunchTestBase):
    def test_a_launched_unit_is_running(self):
        ev = self._launch()
        self.assertEqual(ev["kind"], "launch")
        self.assertIs(ev["alive"], True)
        os.kill(ev["pid"], 0)  # raises if not running

    def test_a_process_that_exits_immediately_is_not_a_launch(self):
        """The proxy this guard exists to reject. Popen returns successfully for
        a process that dies on the next instruction, and the failure would
        surface much later as an empty pane nobody notices."""
        entry = self._entry(argv=[sys.executable, "-c", "raise SystemExit(3)"])
        with self.assertRaises(LaunchExecutionError) as ctx:
            self._launch(entry)
        self.assertIn("exited with code 3", str(ctx.exception))

    def test_a_missing_binary_is_named(self):
        entry = self._entry(argv=["definitely-not-a-real-binary-xyz"])
        with self.assertRaises(LaunchExecutionError) as ctx:
            self._launch(entry)
        self.assertIn("not found on PATH", str(ctx.exception))


class TestTheBoundary(LaunchTestBase):
    def test_no_environment_value_reaches_the_filesystem(self):
        """The correction this slice exists to make.

        gr1's spawn writes a launch script containing `export KEY=value`, which
        puts identity values on disk inside the OSS layer, in a file that
        outlives the launch. This SEARCHES the workspace for the value rather
        than trusting that nothing wrote it -- a test that only launches passes
        for both implementations."""
        ev = self._launch()

        found = []
        for path in self.ws.rglob("*"):
            if not path.is_file():
                continue
            try:
                if SECRET in path.read_text(errors="ignore"):
                    found.append(str(path))
            except OSError:  # pragma: no cover
                pass
        self.assertEqual(found, [], f"environment value persisted to disk: {found}")

        # And the evidence carries NAMES only.
        self.assertEqual(ev["env_keys"], ["SYNAPT_AGENT_ID"])
        self.assertNotIn(SECRET, str(ev))

    def test_the_child_actually_received_the_value(self):
        """The complement, so 'nothing on disk' is not achieved by never
        injecting anything. The value must reach the process and only the
        process."""
        out = self.unit / "seen.txt"
        entry = self._entry(
            argv=[
                sys.executable,
                "-c",
                f"import os,time;open({str(out)!r},'w').write("
                "os.environ.get('SYNAPT_AGENT_ID','MISSING'));time.sleep(30)",
            ]
        )
        self._launch(entry)
        for _ in range(40):
            if out.is_file() and out.read_text():
                break
            time.sleep(0.05)
        self.assertEqual(out.read_text(), SECRET, "the child never received the value")

    def test_a_value_for_an_undeclared_key_is_refused(self):
        with self.assertRaises(LaunchExecutionError) as ctx:
            self._launch(env={"SYNAPT_AGENT_ID": SECRET, "SYNAPT_ORG": "smuggled"})
        self.assertIn("SYNAPT_ORG", str(ctx.exception))
        self.assertIn("undeclared", str(ctx.exception))

    def test_a_declared_key_with_no_value_is_refused(self):
        """The other direction. Launching anyway hands the agent a half-built
        environment and defers the failure to runtime."""
        entry = self._entry(env_allowlist_keys=["SYNAPT_AGENT_ID", "SYNAPT_CHANNELS"])
        with self.assertRaises(LaunchExecutionError) as ctx:
            self._launch(entry, env={"SYNAPT_AGENT_ID": SECRET})
        self.assertIn("SYNAPT_CHANNELS", str(ctx.exception))
        self.assertIn("no value supplied", str(ctx.exception))


class TestOpaqueEntryShape(LaunchTestBase):
    def test_an_unknown_field_is_rejected_not_ignored(self):
        """Closed by construction, same reason the plan schema is: a field
        nobody thought to reject cannot smuggle anything if it cannot exist.
        An unexpected key is exactly how identity would arrive here."""
        with self.assertRaises(LaunchExecutionError) as ctx:
            LaunchEntry.from_mapping(
                {
                    "unit_key": "u_abc123",
                    "workdir": "units/u_abc123/home",
                    "argv": ["true"],
                    "env_allowlist_keys": [],
                    "agent_name": "apollo",
                }
            )
        self.assertIn("agent_name", str(ctx.exception))

    def test_argv_must_be_a_list_not_a_shell_string(self):
        """A single string invites shell interpretation. The launcher never
        hands a plan's contents to a shell."""
        with self.assertRaises(LaunchExecutionError) as ctx:
            LaunchEntry.from_mapping(
                {
                    "unit_key": "u_abc123",
                    "workdir": "units/u_abc123/home",
                    "argv": "claude --model x",
                    "env_allowlist_keys": [],
                }
            )
        self.assertIn("list of strings", str(ctx.exception))

    def test_a_missing_workdir_is_refused_rather_than_created(self):
        """Materialization runs before launch, so a missing workspace means the
        unit was never materialized -- not that launch should create it."""
        entry = self._entry(workdir="units/u_never_materialized/home")
        with self.assertRaises(LaunchExecutionError) as ctx:
            self._launch(entry)
        self.assertIn("does not exist", str(ctx.exception))


class TestTeamLaunch(LaunchTestBase):
    def _team_entries(self, n=3, bad_index=None):
        entries = []
        for i in range(n):
            key = f"u_unit{i}"
            (self.ws / "units" / key / "home").mkdir(parents=True, exist_ok=True)
            argv = (
                [sys.executable, "-c", "raise SystemExit(1)"]
                if i == bad_index
                else [sys.executable, "-c", "import time; time.sleep(30)"]
            )
            entries.append(
                LaunchEntry.from_mapping(
                    {
                        "unit_key": key,
                        "workdir": f"units/{key}/home",
                        "argv": argv,
                        "env_allowlist_keys": ["SYNAPT_AGENT_ID"],
                    }
                )
            )
        return entries

    def test_the_whole_team_wakes(self):
        entries = self._team_entries()
        evidence = launch_team(
            entries,
            workspace_root=self.ws,
            env_values_by_unit={e.unit_key: {"SYNAPT_AGENT_ID": SECRET} for e in entries},
        )
        self.assertEqual(len(evidence), 3)
        for ev in evidence:
            self.pids.append(int(ev["pid"]))
            os.kill(ev["pid"], 0)
        self.assertEqual(len({ev["pid"] for ev in evidence}), 3, "units share a process")

    def test_one_failed_unit_leaves_no_half_live_team(self):
        """Same failure shape as a partially materialized team: some agents
        alive, some absent, presenting as a confused team rather than an error.
        Anything already started is terminated before the failure propagates, so
        a retry does not race a half-live team."""
        entries = self._team_entries(bad_index=2)
        before = _child_python_count()

        with self.assertRaises(LaunchExecutionError):
            launch_team(
                entries,
                workspace_root=self.ws,
                env_values_by_unit={
                    e.unit_key: {"SYNAPT_AGENT_ID": SECRET} for e in entries
                },
            )

        # The two that started must have been reaped.
        for _ in range(40):
            if _child_python_count() <= before:
                break
            time.sleep(0.05)
        self.assertLessEqual(
            _child_python_count(), before, "survivors left behind after a failed team launch"
        )


def _child_python_count() -> int:
    """Sleeping python children of this process -- the fixture's own launches."""
    try:
        out = subprocess.run(
            ["pgrep", "-P", str(os.getpid())], capture_output=True, text=True, check=False
        ).stdout
    except OSError:  # pragma: no cover
        return 0
    return len([line for line in out.splitlines() if line.strip()])


if __name__ == "__main__":
    unittest.main()
