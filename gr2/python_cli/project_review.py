"""Minimal M1 project-tier composition over the existing review clone seam."""
from __future__ import annotations

import argparse
import dataclasses
import re
from pathlib import Path
from typing import Literal

from gr2.prototypes import lane_workspace_prototype as lanes
from . import grip, review
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
    ordered = tuple(sorted(pins, key=lambda pin: pin.key))
    if not ordered or len({pin.key for pin in ordered}) != len(ordered):
        raise ValueError("project review pins must be non-empty with unique keys")
    for pin in ordered:
        if not _SHA40.match(pin.base) or not _SHA40.match(pin.head) or not pin.path or Path(pin.path).is_absolute() or ".." in Path(pin.path).parts:
            raise ValueError(f"invalid project review pin: {pin.key}")
    commit = grip.create_project_review_commit(workspace, [dataclasses.asdict(pin) for pin in ordered])
    return ProjectReviewSpec("gr2-project-review/v1", commit, ordered)


def open_project_review(*, workspace: Path, owner_unit: str, lane_name: str, spec: ProjectReviewSpec, sources: dict[str, tuple[Path, str]], allow_local: bool = False) -> ProjectReviewOutcome:
    """Preflight every immutable pin, then materialize all members before enter."""
    if spec.schema != "gr2-project-review/v1":
        return ProjectReviewOutcome("refused", spec.grip_commit, (), (ProjectReviewFailure("spec", "unsupported schema"),), None, False)
    decoded = grip.read_project_review_commit(workspace, spec.grip_commit)
    if [row["key"] for row in decoded] != [pin.key for pin in spec.pins]:
        return ProjectReviewOutcome("refused", spec.grip_commit, (), (ProjectReviewFailure("spec", "commit/spec pin disagreement"),), None, False)
    for pin in spec.pins:
        source_branch = sources.get(pin.key)
        if source_branch is None:
            return ProjectReviewOutcome("refused", spec.grip_commit, (), (ProjectReviewFailure(pin.key, "missing source transport"),), None, False)
        source, _branch = source_branch
        for label, sha in (("base", pin.base), ("head", pin.head)):
            if git(source, "cat-file", "-e", f"{sha}^{{commit}}").returncode != 0:
                return ProjectReviewOutcome("refused", spec.grip_commit, (), (ProjectReviewFailure(pin.key, f"missing {label} pin {sha}"),), None, False)
    review_root = workspace / "reviews" / owner_unit / lane_name
    observed: list[review.ReviewRecord] = []
    for pin in spec.pins:
        source, branch = sources[pin.key]
        try:
            record = review.open_review_lane(source_repo_root=source, review_branch=branch, expected_head_sha=pin.head, base_sha=pin.base, lane_repo_root=review_root / "repos" / pin.key, workspace_root=workspace, allow_local=allow_local, echo=lambda _line: None)
        except Exception as exc:
            return ProjectReviewOutcome("partial", spec.grip_commit, tuple(observed), (ProjectReviewFailure(pin.key, str(exc)),), review_root, False)
        observed.append(record)
    try:
        lanes.create_lane(argparse.Namespace(workspace_root=workspace, owner_unit=owner_unit, lane_name=lane_name, type="review", repos=",".join(pin.key for pin in spec.pins), branch="main", source="project-review", default_commands=[]))
        lanes.enter_lane(argparse.Namespace(workspace_root=workspace, owner_unit=owner_unit, lane_name=lane_name, actor="project-review", notify_channel=False, recall=False))
    except Exception as exc:
        return ProjectReviewOutcome("partial", spec.grip_commit, tuple(observed), (ProjectReviewFailure("transition", str(exc)),), review_root, False)
    return ProjectReviewOutcome("opened", spec.grip_commit, tuple(observed), (), review_root, True)
