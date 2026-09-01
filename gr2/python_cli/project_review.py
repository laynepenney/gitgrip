"""Minimal M1 project-tier composition over the existing review clone seam."""
from __future__ import annotations

import argparse
import dataclasses
import re
from pathlib import Path
from pathlib import PurePosixPath, PureWindowsPath
from typing import Literal

from gr2.prototypes import lane_workspace_prototype as lanes
from . import grip, review, spec_apply
from .gitops import git

_SHA40 = re.compile(r"\A[0-9a-f]{40}\Z")


@dataclasses.dataclass(frozen=True)
class ProjectReviewPin:
    key: str
    repo: str
    path: str
    base: str
    head: str


@dataclasses.dataclass(frozen=True)
class ProjectReviewSpec:
    schema: str
    grip_commit: str
    pins: tuple[ProjectReviewPin, ...]


@dataclasses.dataclass(frozen=True)
class ProjectReviewFailure:
    key: str
    reason: str


@dataclasses.dataclass(frozen=True)
class ProjectReviewOutcome:
    status: Literal["opened", "refused", "partial"]
    grip_commit: str
    observed: tuple[review.ReviewRecord, ...]
    failures: tuple[ProjectReviewFailure, ...]
    review_root: Path | None
    current_lane_changed: bool


def make_spec(workspace: Path, pins: list[ProjectReviewPin]) -> ProjectReviewSpec:
    ordered = tuple(sorted((_canonical_pin(pin) for pin in pins), key=lambda pin: pin.key))
    if not ordered or len({pin.key for pin in ordered}) != len(ordered):
        raise ValueError("project review pins must be non-empty with unique keys")
    commit = grip.create_project_review_commit(workspace, [dataclasses.asdict(pin) for pin in ordered])
    return ProjectReviewSpec("gr2-project-review/v1", commit, ordered)


def _normalized_path(value: str) -> str:
    path = PurePosixPath(value)
    if not value or path.is_absolute() or ".." in path.parts or str(path) in {".", ""}:
        raise ValueError(f"invalid project review path: {value!r}")
    return path.as_posix()


def _canonical_pin(pin: ProjectReviewPin) -> ProjectReviewPin:
    if not pin.key or any(ch in pin.key for ch in "/\\") or not pin.repo or not _SHA40.match(pin.base) or not _SHA40.match(pin.head):
        raise ValueError(f"invalid project review pin: {pin.key}")
    return dataclasses.replace(pin, path=_normalized_path(pin.path))


def _review_path_component(value: str, field: str) -> str:
    """Validate names before they become a clone destination or lane path."""
    if not value or value in {".", ".."}:
        raise ValueError(f"invalid {field}: {value!r}")
    windows = PureWindowsPath(value)
    if (
        "/" in value
        or "\\" in value
        or ":" in value
        or windows.drive
        or windows.root
        or any(ord(char) < 0x20 or ord(char) == 0x7F for char in value)
    ):
        raise ValueError(f"invalid {field}: {value!r}")
    return value


def _canonical_repo_identity(value: str, *, allow_local: bool) -> str:
    """Canonicalize a pin/spec identity without treating a clone path as truth.

    Local paths are test-only transport. When one names a checkout, its origin
    supplies the repository identity just as production HTTPS/SSH transport
    does. A bare local path remains marked local for isolated fixtures.
    """
    if value.startswith("local:"):
        local = Path(value.removeprefix("local:"))
        origin = review.gitops.remote_origin_url(local) if local.is_dir() else None
        if origin:
            return review.canonical_source_identity(origin, allow_local=True)
        return f"local:{local.resolve()}"
    return review.canonical_source_identity(value, allow_local=allow_local)


def _validate_workspace_repository_boundary(
    *, workspace: Path, pins: tuple[ProjectReviewPin, ...], sources: dict[str, tuple[Path, str]], allow_local: bool
) -> ProjectReviewFailure | None:
    """Bind every review pin and ephemeral source to the compiled workspace.

    This is deliberately before pin-object checks, clone destinations, or lane
    transition. A project review may only materialize repositories the compiled
    workspace itself authorizes.
    """
    try:
        workspace_doc = spec_apply.load_workspace_spec_doc(workspace)
    except SystemExit as exc:
        return ProjectReviewFailure("workspace_spec", str(exc))
    entries: dict[str, str] = {}
    for row in workspace_doc.get("repos", []):
        if not isinstance(row, dict):
            return ProjectReviewFailure("workspace_spec", "compiled workspace repo entry is not a mapping")
        key = str(row.get("name", ""))
        url = str(row.get("url", ""))
        try:
            entries[key] = _canonical_repo_identity(url, allow_local=allow_local)
        except Exception as exc:
            return ProjectReviewFailure("workspace_spec", f"invalid compiled repository {key!r}: {exc}")
    for pin in pins:
        expected = entries.get(pin.key)
        if expected is None:
            return ProjectReviewFailure(pin.key, f"unknown workspace repository key {pin.key!r}")
        try:
            pin_identity = _canonical_repo_identity(pin.repo, allow_local=allow_local)
        except Exception as exc:
            return ProjectReviewFailure(pin.key, f"invalid pin repository identity: {exc}")
        if pin_identity != expected:
            return ProjectReviewFailure(
                pin.key,
                f"workspace repository identity mismatch: pin {pin_identity!r}, compiled {expected!r}",
            )
        source_branch = sources.get(pin.key)
        if source_branch is None:
            continue
        source, _branch = source_branch
        origin = review.gitops.remote_origin_url(source)
        if not origin:
            return ProjectReviewFailure(pin.key, f"selected source {source} has no origin for identity validation")
        try:
            source_identity = _canonical_repo_identity(origin, allow_local=allow_local)
        except Exception as exc:
            return ProjectReviewFailure(pin.key, f"invalid selected source origin: {exc}")
        if source_identity != pin_identity:
            return ProjectReviewFailure(
                pin.key,
                f"selected source identity mismatch: source {source_identity!r}, pin {pin_identity!r}",
            )
    return None


def open_project_review(*, workspace: Path, owner_unit: str, lane_name: str, spec: ProjectReviewSpec, sources: dict[str, tuple[Path, str]], allow_local: bool = False) -> ProjectReviewOutcome:
    """Preflight every immutable pin, then materialize all members before enter."""
    if spec.schema != "gr2-project-review/v1":
        return ProjectReviewOutcome("refused", spec.grip_commit, (), (ProjectReviewFailure("spec", "unsupported schema"),), None, False)
    try:
        owner_unit = _review_path_component(owner_unit, "owner unit")
        lane_name = _review_path_component(lane_name, "lane name")
    except ValueError as exc:
        return ProjectReviewOutcome("refused", spec.grip_commit, (), (ProjectReviewFailure("review_root", str(exc)),), None, False)
    try:
        canonical_pins = tuple(_canonical_pin(pin) for pin in spec.pins)
    except ValueError as exc:
        return ProjectReviewOutcome("refused", spec.grip_commit, (), (ProjectReviewFailure("spec", str(exc)),), None, False)
    decoded = grip.read_project_review_commit(workspace, spec.grip_commit)
    if len(decoded) != len(canonical_pins):
        return ProjectReviewOutcome("refused", spec.grip_commit, (), (ProjectReviewFailure("spec", "gr commit member count mismatch"),), None, False)
    for row, pin in zip(decoded, canonical_pins):
        for field, expected, observed in (("key", pin.key, row["key"]), ("repo", pin.repo, row["repo"]), ("path", pin.path, _normalized_path(row["path"])), ("base", pin.base, row["base"]), ("head", pin.head, row["head"])):
            if expected != observed:
                return ProjectReviewOutcome("refused", spec.grip_commit, (), (ProjectReviewFailure(pin.key, f"gr commit mismatch for {field}: expected {expected!r}, observed {observed!r}"),), None, False)
    boundary_failure = _validate_workspace_repository_boundary(
        workspace=workspace, pins=canonical_pins, sources=sources, allow_local=allow_local
    )
    if boundary_failure is not None:
        return ProjectReviewOutcome("refused", spec.grip_commit, (), (boundary_failure,), None, False)
    for pin in canonical_pins:
        source_branch = sources.get(pin.key)
        if source_branch is None:
            return ProjectReviewOutcome("refused", spec.grip_commit, (), (ProjectReviewFailure(pin.key, "missing source transport"),), None, False)
        source, _branch = source_branch
        for label, sha in (("base", pin.base), ("head", pin.head)):
            if git(source, "cat-file", "-e", f"{sha}^{{commit}}").returncode != 0:
                return ProjectReviewOutcome("refused", spec.grip_commit, (), (ProjectReviewFailure(pin.key, f"missing {label} pin {sha}"),), None, False)
    review_root = workspace / "reviews" / owner_unit / lane_name
    observed: list[review.ReviewRecord] = []
    for pin in canonical_pins:
        source, branch = sources[pin.key]
        try:
            record = review.open_review_lane(source_repo_root=source, review_branch=branch, expected_head_sha=pin.head, base_sha=pin.base, lane_repo_root=review_root / "repos" / pin.key, workspace_root=workspace, allow_local=allow_local, echo=lambda _line: None)
        except Exception as exc:
            return ProjectReviewOutcome("partial", spec.grip_commit, tuple(observed), (ProjectReviewFailure(pin.key, str(exc)),), review_root, False)
        observed.append(record)
    try:
        lanes.create_lane(argparse.Namespace(workspace_root=workspace, owner_unit=owner_unit, lane_name=lane_name, type="review", repos=",".join(pin.key for pin in canonical_pins), branch="main", source="project-review", default_commands=[]))
        lanes.enter_lane(argparse.Namespace(workspace_root=workspace, owner_unit=owner_unit, lane_name=lane_name, actor="project-review", notify_channel=False, recall=False))
    except Exception as exc:
        return ProjectReviewOutcome("partial", spec.grip_commit, tuple(observed), (ProjectReviewFailure("transition", str(exc)),), review_root, False)
    return ProjectReviewOutcome("opened", spec.grip_commit, tuple(observed), (), review_root, True)


def outcome_payload(outcome: ProjectReviewOutcome) -> dict[str, object]:
    return {"status": outcome.status, "grip_commit": outcome.grip_commit,
            "observed": [record.to_dict() for record in outcome.observed],
            "failures": [dataclasses.asdict(failure) for failure in outcome.failures],
            "review_root": str(outcome.review_root) if outcome.review_root else None,
            "current_lane_changed": outcome.current_lane_changed}
