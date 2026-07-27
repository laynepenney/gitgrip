"""Neutral launch primitive (S5).

Executes a LaunchPlan entry: run this argv, in this working directory, with
these environment KEY NAMES. gr2 cannot tell a synapt agent team from any other
multi-repo workspace -- it sees an opaque `unit_key`, an argv, and a set of env
key names whose VALUES the caller supplies in memory at launch.

Design: the spawn launch contract, §2 (LaunchPlan is the
opaque tier) and §5 (cold start, no `--resume`).

THE BOUNDARY CORRECTION THIS SLICE EXISTS TO MAKE
--------------------------------------------------
gr1's spawn builds an on-disk launch script containing `export KEY=value` lines.
That puts identity environment VALUES on disk -- SYNAPT_AGENT_ID, org, channel
bindings -- inside the OSS layer, in a file that outlives the launch.

The neutral plan carries key NAMES; the values are injected in memory and never
persisted. This primitive therefore has no script-writing path at all: values
are passed straight to the child process environment and are unreachable from
the filesystem afterwards. `test_no_environment_value_reaches_the_filesystem`
searches the workspace for a value rather than trusting that nothing wrote one.

Same rule that held through the whole materializer: no identity in any neutral
artifact. A launch script IS a neutral artifact.

WHAT "LAUNCHED" HAS TO MEAN
---------------------------
A spawn call returning successfully is not an agent running. A process that
exits immediately -- a missing binary, a bad flag, an instant crash -- produces
exactly the same "success" as one that came up healthy, and the failure surfaces
later as an empty pane nobody notices. So launch is not acknowledged until the
child has been observed ALIVE after a settle interval, which is the same
distinction invariant 6 draws between a venv's files existing and its
interpreter answering.
"""
from __future__ import annotations

import dataclasses
import os
import subprocess
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .spec_apply import MaterializationPlanError, canonicalize_workspace_path

# Long enough that an immediate crash (bad binary, bad flag, instant exit) has
# happened, short enough not to matter against §13's 180s budget.
_LIVENESS_SETTLE_SECONDS = 0.35


class LaunchExecutionError(MaterializationPlanError):
    """A launch entry could not be executed safely."""


@dataclasses.dataclass(frozen=True)
class LaunchEntry:
    """One unit's opaque launch declaration.

    Deliberately carries no model, tool, role or agent name -- gr2 runs an argv,
    it does not know what the argv IS."""

    unit_key: str
    workdir: str
    argv: tuple[str, ...]
    env_allowlist_keys: tuple[str, ...]

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> LaunchEntry:
        allowed = {"unit_key", "workdir", "argv", "env_allowlist_keys"}
        unknown = set(data) - allowed
        if unknown:
            # Closed by construction, same reason the plan schema is: a field
            # nobody thought to reject cannot smuggle anything if it cannot
            # exist. An unexpected key here is how identity would arrive.
            raise LaunchExecutionError(
                f"launch entry has unknown field(s) {sorted(unknown)} -- the opaque "
                "tier carries exactly unit_key, workdir, argv and env_allowlist_keys"
            )
        for field in ("unit_key", "workdir"):
            if not isinstance(data.get(field), str) or not data[field]:
                raise LaunchExecutionError(f"launch entry {field!r} must be a non-empty string")
        argv = data.get("argv")
        if not isinstance(argv, (list, tuple)) or not argv or not all(
            isinstance(a, str) for a in argv
        ):
            raise LaunchExecutionError(
                "launch entry argv must be a non-empty list of strings -- a single "
                "string would invite shell interpretation, and the launcher never "
                "hands a plan's contents to a shell"
            )
        keys = data.get("env_allowlist_keys", [])
        if not isinstance(keys, (list, tuple)) or not all(isinstance(k, str) for k in keys):
            raise LaunchExecutionError("env_allowlist_keys must be a list of strings")
        return cls(
            unit_key=data["unit_key"],
            workdir=data["workdir"],
            argv=tuple(argv),
            env_allowlist_keys=tuple(keys),
        )


def _require_exact_env(entry: LaunchEntry, values: Mapping[str, str]) -> dict[str, str]:
    """The allowlist is exact in BOTH directions.

    Extra: the caller supplied a value for a key the plan never declared. The plan
    is what a reviewer reads to know what a process receives, so a value outside
    it is invisible to review.

    Missing: the plan declared a key the launch has no value for. Starting the
    process anyway hands the agent a half-built environment and the failure
    appears later as behaviour nobody traces back to launch.

    Both are refusals, and they are checked separately because a single
    set-equality assertion would report the wrong one first and teach the
    operator the wrong thing to fix."""
    declared = set(entry.env_allowlist_keys)
    supplied = set(values)

    extra = sorted(supplied - declared)
    if extra:
        raise LaunchExecutionError(
            f"unit {entry.unit_key}: environment value(s) supplied for undeclared "
            f"key(s) {extra} -- the launch plan is what a reviewer reads to know what "
            "a process receives, so anything outside it is invisible to review"
        )
    missing = sorted(declared - supplied)
    if missing:
        raise LaunchExecutionError(
            f"unit {entry.unit_key}: no value supplied for declared key(s) {missing} -- "
            "starting with a half-built environment defers the failure to runtime"
        )
    return {k: str(values[k]) for k in entry.env_allowlist_keys}


# Launcher-owned process mechanics, supplied EXPLICITLY rather than inherited.
# §6 classes these as launcher-owned precisely so a plan cannot declare them --
# but the child still needs them to run at all (a binary resolved by name needs
# PATH). Naming them here is the difference between "the launcher provides these,
# for these reasons" and "whatever the parent happened to have".
_LAUNCHER_OWNED_PASSTHROUGH = ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "SystemRoot")


def _child_environment(entry: LaunchEntry, values: Mapping[str, str]) -> dict[str, str]:
    """The child's COMPLETE environment, built rather than inherited.

    Sentinel, #825: passing `{**os.environ, **declared}` inherits the parent's
    entire environment, so a child sees ambient caller variables that were
    never declared anywhere -- reproduced on a live host, where the coordinator's
    ambient coordinator variables reached a spawned agent.

    My allowlist check was exact in two directions and both were about the
    SUPPLIED dict: a value for an undeclared key, and a declared key with no
    value. Neither asks what the child ACTUALLY ENDS UP WITH. Receiving the
    right thing and receiving ONLY that are different claims, and the test that
    asserted the child got the declared value could not see the difference.

    So the environment is CONSTRUCTED: exactly the declared keys, plus a named
    set of launcher-owned mechanics the child cannot run without. Nothing is
    inherited implicitly. Everything present is there because something declared
    it or because this list names it.

    That matters beyond tidiness: the demo claims identity is injected in memory
    with nothing leaked, and inheriting os.environ leaks the COORDINATOR'S
    caller environment into every spawned agent."""
    child = _require_exact_env(entry, values)
    for key in _LAUNCHER_OWNED_PASSTHROUGH:
        ambient = os.environ.get(key)
        if ambient is not None and key not in child:
            child[key] = ambient
    return child


def launch_unit(
    entry: LaunchEntry,
    *,
    workspace_root: Path,
    env_values: Mapping[str, str],
    settle_seconds: float = _LIVENESS_SETTLE_SECONDS,
) -> dict[str, object]:
    """Start one unit's process and prove it is alive.

    `env_values` is consumed in memory and never written anywhere. Returns
    neutral evidence -- no argv values, no env, nothing identity-bearing."""
    workspace_root = Path(os.fspath(workspace_root))
    workdir = canonicalize_workspace_path(
        workspace_root, entry.workdir, field_name=f"launch[{entry.unit_key}].workdir"
    )
    if not workdir.is_dir():
        raise LaunchExecutionError(
            f"unit {entry.unit_key}: workdir {entry.workdir} does not exist -- "
            "materialization runs before launch, so a missing workspace means the "
            "unit was never materialized rather than that launch should create it"
        )

    env = _child_environment(entry, env_values)

    try:
        # No shell. argv is a list, and a plan's contents are never handed to a
        # shell for interpretation.
        proc = subprocess.Popen(  # noqa: S603
            list(entry.argv),
            cwd=str(workdir),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except FileNotFoundError as exc:
        raise LaunchExecutionError(
            f"unit {entry.unit_key}: {entry.argv[0]!r} not found on PATH"
        ) from exc
    except OSError as exc:
        raise LaunchExecutionError(f"unit {entry.unit_key}: launch failed: {exc}") from exc

    # LIVENESS, not spawn-return. A process that exits immediately produces the
    # same successful Popen as one that came up healthy.
    time.sleep(settle_seconds)
    code = proc.poll()
    if code is not None:
        raise LaunchExecutionError(
            f"unit {entry.unit_key}: process exited with code {code} within "
            f"{settle_seconds}s of launch -- a spawn that returns is not an agent "
            "that runs, and an immediately-dead process is indistinguishable from a "
            "healthy one until someone looks"
        )

    return {
        "kind": "launch",
        "unit_key": entry.unit_key,
        "workdir": entry.workdir,
        "pid": proc.pid,
        "env_keys": list(entry.env_allowlist_keys),  # NAMES only, never values
        "alive": True,
    }


def launch_team(
    entries: Sequence[LaunchEntry],
    *,
    workspace_root: Path,
    env_values_by_unit: Mapping[str, Mapping[str, str]],
    settle_seconds: float = _LIVENESS_SETTLE_SECONDS,
) -> list[dict[str, object]]:
    """Launch every unit, or none of them.

    A partially launched team is the same failure shape as a partially
    materialized one: some agents alive, some absent, presenting as a confused
    team rather than an error. Anything already started is terminated before the
    failure propagates, so a retry does not race a half-live team."""
    started: list[tuple[dict[str, object], int]] = []
    try:
        for entry in entries:
            values = env_values_by_unit.get(entry.unit_key)
            if values is None:
                raise LaunchExecutionError(
                    f"no environment supplied for unit {entry.unit_key}"
                )
            evidence = launch_unit(
                entry,
                workspace_root=workspace_root,
                env_values=values,
                settle_seconds=settle_seconds,
            )
            started.append((evidence, int(evidence["pid"])))
    except BaseException:
        for _, pid in started:
            try:
                os.killpg(os.getpgid(pid), 15)
            except (ProcessLookupError, PermissionError):  # pragma: no cover
                pass
        raise
    return [ev for ev, _ in started]
