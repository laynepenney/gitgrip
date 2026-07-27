from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import shutil
import subprocess
import tomllib
from datetime import UTC, datetime
from pathlib import Path

from .events import EventType, emit
from .gitops import (
    checkout_branch,
    clone_repo,
    current_head_sha,
    ensure_repo_cache,
    is_git_dir,
    is_git_repo,
    remote_origin_url,
    repo_dirty,
)
from .hooks import HookContext, apply_file_projections, load_repo_hooks, run_lifecycle_stage


class MaterializationPlanError(Exception):
    pass


# ---------------------------------------------------------------------------
# Shared containment + identity primitives (config#491 §3, §6.2)
#
# Used by both the legacy workspace_spec.toml path below and the neutral
# MaterializationPlan path -- the same functions, not parallel copies.
# ---------------------------------------------------------------------------

# config#491 §6.2: "The production plan must not contain: agent display
# name, persistent agent ID, role, org or project, channel, entitlement
# result or reason, secret reference or value, memory body." Checked
# recursively (Sentinel r2 P5: nested identity fields must be caught too,
# not just top-level operation keys) as a structural safety net.
_FORBIDDEN_IDENTITY_KEYS = frozenset(
    {
        "agent_name",
        "agent_id",
        "persistent_identity_ref",
        "role",
        "org",
        "project",
        "channel",
        "channels",
        "entitlement",
        "entitlement_reason",
        "secret",
        "secret_ref",
        "memory",
        "memory_body",
    }
)


def _reject_identity_fields_recursive(value: object, *, path: str) -> None:
    if isinstance(value, dict):
        present = _FORBIDDEN_IDENTITY_KEYS & value.keys()
        if present:
            raise MaterializationPlanError(
                f"{path} carries identity-bearing field(s) {sorted(present)}; "
                "gr2 MaterializationPlan operations must be identity-free (config#491 §6.2)"
            )
        for key, nested in value.items():
            _reject_identity_fields_recursive(nested, path=f"{path}.{key}")
    elif isinstance(value, list):
        for i, item in enumerate(value):
            _reject_identity_fields_recursive(item, path=f"{path}[{i}]")


def _validate_path_safe_token(value: object, *, field_name: str) -> str:
    """An opaque, path-safe identifier: no separators, no traversal, no
    identity semantics interpreted -- used for plan_id and unit_key, both
    of which end up embedded in filesystem paths (receipt filenames)."""
    if not isinstance(value, str) or not value:
        raise MaterializationPlanError(f"{field_name} must be a non-empty string")
    if "/" in value or "\\" in value or value in (".", "..") or "\x00" in value:
        raise MaterializationPlanError(f"{field_name} must be a path-safe token, got {value!r}")
    return value


def _resolve_contained(workspace_root: Path, relative: str, *, field_name: str) -> Path:
    """config#491 §3: absolute paths, .., symlink escapes, and duplicate
    destinations are blockers. Path.resolve() normalizes .. lexically and
    follows any existing symlinks, so a single containment check after
    resolving catches all three escape shapes. Shared by dest_path,
    reference_base, and (via _resolve_staging_source) source_path."""
    if not relative or relative.startswith("/") or relative.startswith("~"):
        raise MaterializationPlanError(f"{field_name} must be relative to the workspace root: {relative!r}")
    workspace_resolved = workspace_root.resolve()
    candidate = (workspace_root / relative).resolve()
    if candidate != workspace_resolved and workspace_resolved not in candidate.parents:
        raise MaterializationPlanError(f"{field_name} escapes the workspace root: {relative!r}")
    return workspace_root / relative


def _resolve_safe_dest(workspace_root: Path, dest_path: str) -> Path:
    return _resolve_contained(workspace_root, dest_path, field_name="dest_path")


_STAGING_INPUTS_SUBPATH = Path(".grip") / "staging" / "inputs"


def _resolve_staging_source(workspace_root: Path, source_path: str) -> Path:
    """config#491 §6.2, Sentinel r2 P4 ruling: source_path MUST be
    workspace-relative AND resolve beneath .grip/staging/inputs/ specifically
    -- not just anywhere in the workspace. The normative example is
    `.grip/staging/inputs/f_01`; S7 emits `.grip/staging/inputs/<opaque-key>`."""
    resolved = _resolve_contained(workspace_root, source_path, field_name="source_path").resolve()
    staging_root = (workspace_root / _STAGING_INPUTS_SUBPATH).resolve()
    if resolved != staging_root and staging_root not in resolved.parents:
        raise MaterializationPlanError(
            f"source_path must resolve beneath .grip/staging/inputs/: {source_path!r}"
        )
    return workspace_root / source_path


# ---------------------------------------------------------------------------
# Shared clone executor (config#491 §7.3 "one executor", §8.1-8.3)
#
# The single canonical clone primitive. Used by both the legacy
# workspace_spec.toml path and the neutral MaterializationPlan path --
# Sentinel r2 P1: sharing only the gitops.clone_repo() leaf call does not
# satisfy "one executor, not a second materializer." Both callers now
# delegate the full clone-and-validate sequence here, not just the raw
# `git clone` invocation.
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class CloneResult:
    first_materialize: bool
    origin_url: str | None
    head_sha: str | None


def _validate_clone_isolation(
    repo_root: Path,
    *,
    workspace_root: Path,
    reference_repo_root: Path | None,
    expected_origin: str,
) -> None:
    """config#491 §8.1-8.2: reject worktree-linked clones, clones whose
    git-common-dir escapes their own .git, clones hosting nested linked
    worktrees, origin mismatches, and alternates pointing anywhere except
    the declared workspace cache. Sentinel r2 P3: "`.git` is a directory"
    plus an alternates check alone does not prove the §8.1 common-dir,
    origin, or no-worktrees invariants -- each is checked explicitly here."""
    git_path = repo_root / ".git"
    if git_path.is_file():
        raise MaterializationPlanError(
            f"clone at {repo_root} has a worktree-pointer .git file, not a real .git directory "
            "(config#491 §8.1 forbids worktree-linked agent workspaces)"
        )
    if not git_path.is_dir():
        raise MaterializationPlanError(f"clone at {repo_root} has no .git directory")

    if (git_path / "worktrees").exists():
        raise MaterializationPlanError(
            f"clone at {repo_root} has .git/worktrees -- it is hosting linked worktrees, "
            "not an isolated agent clone (config#491 §8.1)"
        )

    common_dir_proc = subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", "--git-common-dir"],
        capture_output=True,
        text=True,
        check=False,
    )
    if common_dir_proc.returncode == 0:
        common_dir_raw = common_dir_proc.stdout.strip()
        common_dir = Path(common_dir_raw)
        if not common_dir.is_absolute():
            common_dir = (repo_root / common_dir).resolve()
        else:
            common_dir = common_dir.resolve()
        if common_dir != git_path.resolve():
            raise MaterializationPlanError(
                f"clone at {repo_root} has git-common-dir {common_dir} that is not its own .git "
                "-- it shares mutable git metadata with another checkout (config#491 §8.1)"
            )

    actual_origin = remote_origin_url(repo_root)
    if actual_origin != expected_origin:
        raise MaterializationPlanError(
            f"clone at {repo_root} has origin {actual_origin!r}, expected {expected_origin!r} "
            "-- an existing clone must match the declared repo_url"
        )

    alternates_file = git_path / "objects" / "info" / "alternates"
    if not alternates_file.exists():
        return
    approved = (reference_repo_root.resolve() / "objects") if reference_repo_root else None
    for line in alternates_file.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        if approved is None or Path(line).resolve() != approved:
            raise MaterializationPlanError(
                f"clone at {repo_root} has an unapproved alternate: {line} "
                "(config#491 §8.2: alternates may only point at the declared workspace cache)"
            )


def _clone_isolated(
    workspace_root: Path,
    *,
    repo_url: str,
    dest: Path,
    branch: str | None = None,
    reference_repo_root: Path | None = None,
) -> CloneResult:
    """The one canonical clone primitive.

    - An existing dest is validated, never blindly reset or replaced
      (config#491 §8.3) -- checked before touching anything else.
    - A fresh clone happens in a SIBLING STAGING PATH: cloned, checked out,
      and fully validated there, then atomically renamed into dest
      (Sentinel r2 P2). A failure at any point after the raw `git clone`
      succeeds (bad branch, failed isolation check) must never leave a
      partially-published dest -- the staging directory is removed and
      dest never comes to exist.
    """
    if dest.exists():
        _validate_clone_isolation(
            dest,
            workspace_root=workspace_root,
            reference_repo_root=reference_repo_root,
            expected_origin=repo_url,
        )
        return CloneResult(
            first_materialize=False,
            origin_url=remote_origin_url(dest),
            head_sha=current_head_sha(dest),
        )

    staging = dest.parent / f".{dest.name}.staging-{os.getpid()}-{id(dest)}"
    if staging.exists():
        shutil.rmtree(staging, ignore_errors=True)
    try:
        clone_repo(repo_url, staging, reference_repo_root=reference_repo_root)
        if branch:
            checkout_branch(staging, branch)
        _validate_clone_isolation(
            staging,
            workspace_root=workspace_root,
            reference_repo_root=reference_repo_root,
            expected_origin=repo_url,
        )
    except (SystemExit, Exception) as exc:
        # gitops.py deliberately raises SystemExit (not Exception) on git
        # failures -- `except Exception:` alone silently misses it and skips
        # staging cleanup, since SystemExit is a BaseException sibling, not
        # an Exception subclass. Caught here explicitly, verified with a
        # test (clone + nonexistent branch) rather than assumed correct.
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        if isinstance(exc, MaterializationPlanError):
            raise
        raise MaterializationPlanError(f"clone staging failed for {repo_url} -> {dest}: {exc}") from exc

    dest.parent.mkdir(parents=True, exist_ok=True)
    staging.rename(dest)
    return CloneResult(
        first_materialize=True,
        origin_url=remote_origin_url(dest),
        head_sha=current_head_sha(dest),
    )


# ---------------------------------------------------------------------------
# Legacy workspace_spec.toml path (repos/units declared as a TOML diff-target)
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class ValidationIssue:
    level: str
    code: str
    message: str
    path: str | None = None

    def as_dict(self) -> dict[str, object]:
        return dataclasses.asdict(self)


@dataclasses.dataclass(frozen=True)
class PlanOperation:
    kind: str
    subject: str
    target_path: str
    reason: str
    details: dict[str, object]

    def as_dict(self) -> dict[str, object]:
        return dataclasses.asdict(self)


def workspace_spec_path(workspace_root: Path) -> Path:
    return workspace_root / ".grip" / "workspace_spec.toml"


def workspace_cache_root(workspace_root: Path) -> Path:
    return workspace_root / ".grip" / "cache" / "repos"


def repo_cache_path(workspace_root: Path, repo_name: str) -> Path:
    return workspace_cache_root(workspace_root) / f"{repo_name}.git"


def load_workspace_spec_doc(workspace_root: Path) -> dict[str, object]:
    spec_path = workspace_spec_path(workspace_root)
    if not spec_path.exists():
        raise SystemExit(
            f"workspace spec not found: {spec_path}\n"
            "run `gr2 workspace init <path>` first or create .grip/workspace_spec.toml explicitly"
        )
    with spec_path.open("rb") as fh:
        return tomllib.load(fh)


def show_spec(workspace_root: Path, *, json_output: bool) -> str:
    spec_path = workspace_spec_path(workspace_root)
    if json_output:
        return json.dumps(load_workspace_spec_doc(workspace_root), indent=2)
    return spec_path.read_text()


def validate_spec(workspace_root: Path) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    spec = load_workspace_spec_doc(workspace_root)

    workspace_name = str(spec.get("workspace_name", "")).strip()
    if not workspace_name:
        issues.append(
            ValidationIssue(
                level="error",
                code="missing_workspace_name",
                message="workspace spec workspace_name must not be empty",
                path="workspace_name",
            )
        )

    repo_names: set[str] = set()
    for idx, repo in enumerate(spec.get("repos", [])):
        name = str(repo.get("name", "")).strip()
        path = str(repo.get("path", "")).strip()
        url = str(repo.get("url", "")).strip()
        if not name:
            issues.append(
                ValidationIssue("error", "missing_repo_name", "repo name must not be empty", f"repos[{idx}].name")
            )
            continue
        if name in repo_names:
            issues.append(
                ValidationIssue("error", "duplicate_repo_name", f"duplicate repo '{name}'", f"repos[{idx}].name")
            )
        repo_names.add(name)
        if not path:
            issues.append(
                ValidationIssue("error", "missing_repo_path", f"repo '{name}' path must not be empty", f"repos[{idx}].path")
            )
        if not url:
            issues.append(
                ValidationIssue("error", "missing_repo_url", f"repo '{name}' url must not be empty", f"repos[{idx}].url")
            )
        repo_root = workspace_root / path
        if repo_root.exists() and not is_git_repo(repo_root):
            issues.append(
                ValidationIssue(
                    level="error",
                    code="repo_path_conflict",
                    message=f"repo path exists but is not a git repo: {repo_root}",
                        path=f"repos[{idx}].path",
                    )
                )
        cache_root = repo_cache_path(workspace_root, name)
        if cache_root.exists() and not is_git_dir(cache_root):
            issues.append(
                ValidationIssue(
                    level="error",
                    code="repo_cache_conflict",
                    message=f"repo cache path exists but is not a bare git dir: {cache_root}",
                    path=f"repos[{idx}].name",
                )
            )
        if repo_root.exists() and is_git_repo(repo_root):
            try:
                load_repo_hooks(repo_root)
            except SystemExit as exc:
                issues.append(
                    ValidationIssue(
                        level="error",
                        code="invalid_repo_hooks",
                        message=f"repo '{name}' has invalid .gr2/hooks.toml: {exc}",
                        path=f"repos[{idx}]",
                    )
                )

    unit_names: set[str] = set()
    for idx, unit in enumerate(spec.get("units", [])):
        name = str(unit.get("name", "")).strip()
        path = str(unit.get("path", "")).strip()
        repos = [str(item) for item in unit.get("repos", [])]
        if not name:
            issues.append(
                ValidationIssue("error", "missing_unit_name", "unit name must not be empty", f"units[{idx}].name")
            )
            continue
        if name in unit_names:
            issues.append(
                ValidationIssue("error", "duplicate_unit_name", f"duplicate unit '{name}'", f"units[{idx}].name")
            )
        unit_names.add(name)
        if not path:
            issues.append(
                ValidationIssue("error", "missing_unit_path", f"unit '{name}' path must not be empty", f"units[{idx}].path")
            )
        unit_root = workspace_root / path
        if unit_root.exists() and unit_root.is_file():
            issues.append(
                ValidationIssue(
                    "error",
                    "unit_path_conflict",
                    f"unit path exists as a file: {unit_root}",
                    f"units[{idx}].path",
                )
            )
        missing = [repo for repo in repos if repo not in repo_names]
        for repo_name in missing:
            issues.append(
                ValidationIssue(
                    "error",
                    "missing_unit_repo",
                    f"unit '{name}' references missing repo '{repo_name}'",
                    f"units[{idx}].repos",
                )
            )

    return issues


def render_validation(issues: list[ValidationIssue]) -> str:
    if not issues:
        return "WorkspaceSpec\n- valid\n"
    lines = ["WorkspaceSpec", "LEVEL\tCODE\tPATH\tMESSAGE"]
    for issue in issues:
        lines.append(f"{issue.level}\t{issue.code}\t{issue.path or '-'}\t{issue.message}")
    return "\n".join(lines)


def build_plan(workspace_root: Path) -> tuple[dict[str, object], list[PlanOperation]]:
    issues = validate_spec(workspace_root)
    errors = [issue for issue in issues if issue.level == "error"]
    if errors:
        rendered = "\n".join(f"- {issue.message}" for issue in errors)
        raise SystemExit(f"workspace spec validation failed:\n{rendered}")

    spec = load_workspace_spec_doc(workspace_root)
    operations: list[PlanOperation] = []

    for repo in spec.get("repos", []):
        repo_name = str(repo["name"])
        repo_path = workspace_root / str(repo["path"])
        cache_path = repo_cache_path(workspace_root, repo_name)
        if not cache_path.exists():
            operations.append(
                PlanOperation(
                    kind="seed_repo_cache",
                    subject=repo_name,
                    target_path=str(cache_path),
                    reason="repo cache missing",
                    details={"url": str(repo["url"])},
                )
            )
        if not repo_path.exists():
            operations.append(
                PlanOperation(
                    kind="clone_repo",
                    subject=repo_name,
                    target_path=str(repo_path),
                    reason="repo path missing",
                    details={"url": str(repo["url"]), "cache_path": str(cache_path)},
                )
            )

    for unit in spec.get("units", []):
        unit_name = str(unit["name"])
        unit_root = workspace_root / str(unit["path"])
        unit_toml = unit_root / "unit.toml"
        if not unit_root.exists():
            operations.append(
                PlanOperation(
                    kind="create_unit_root",
                    subject=unit_name,
                    target_path=str(unit_root),
                    reason="unit path missing",
                    details={"repos": [str(repo) for repo in unit.get("repos", [])]},
                )
            )
        if not unit_toml.exists():
            operations.append(
                PlanOperation(
                    kind="write_unit_metadata",
                    subject=unit_name,
                    target_path=str(unit_toml),
                    reason="unit metadata missing",
                    details={"repos": [str(repo) for repo in unit.get("repos", [])]},
                )
            )

        # grip#539: computed unconditionally, not gated on unit_root/unit_toml
        # already existing. A brand-new unit's declared repos are trivially
        # "missing" too (unit_root doesn't exist yet, so (unit_root / r).exists()
        # is False for every r) -- the old guard meant a first apply published
        # the unit shell without scheduling its clones, requiring a second,
        # separate apply to notice. Ordered after create_unit_root/
        # write_unit_metadata in this loop, so apply_plan's execution (which
        # processes operations in list order) creates the directory before
        # trying to clone into it.
        declared_repos = [str(r) for r in unit.get("repos", [])]
        missing_repos = [r for r in declared_repos if not (unit_root / r).exists()]
        if missing_repos:
            operations.append(
                PlanOperation(
                    kind="converge_unit_repos",
                    subject=unit_name,
                    target_path=str(unit_root),
                    reason=f"missing repo checkouts: {', '.join(missing_repos)}",
                    details={"missing_repos": missing_repos, "all_repos": declared_repos},
                )
            )

    return spec, operations


def render_plan(operations: list[PlanOperation]) -> str:
    if not operations:
        return "ExecutionPlan\n- no changes required\n"
    lines = ["ExecutionPlan", "KIND\tSUBJECT\tTARGET\tREASON"]
    for op in operations:
        lines.append(f"{op.kind}\t{op.subject}\t{op.target_path}\t{op.reason}")
    return "\n".join(lines)


def apply_plan(workspace_root: Path, *, yes: bool, manual_hooks: bool = False) -> dict[str, object]:
    spec, operations = build_plan(workspace_root)
    if len(operations) > 3 and not yes:
        raise SystemExit("plan contains more than 3 operations; rerun with --yes to apply it")

    applied: list[str] = []
    materialized_repos: list[dict[str, object]] = []
    for op in operations:
        if op.kind == "clone_repo":
            repo_spec = _find_repo(spec, op.subject)
            repo_root = workspace_root / str(repo_spec["path"])
            cache_path = repo_cache_path(workspace_root, str(repo_spec["name"]))
            result = _clone_isolated(
                workspace_root,
                repo_url=str(repo_spec["url"]),
                dest=repo_root,
                reference_repo_root=cache_path,
            )
            first_materialize = result.first_materialize
            hook_payload = _run_materialize_hooks(
                workspace_root,
                repo_root,
                str(repo_spec["name"]),
                first_materialize,
                manual_hooks=manual_hooks,
            )
            for projection in hook_payload["projected_files"]:
                emit(
                    event_type=EventType.WORKSPACE_FILE_PROJECTED,
                    workspace_root=workspace_root,
                    actor="system",
                    owner_unit="workspace",
                    payload={
                        "repo": str(repo_spec["name"]),
                        "kind": projection["kind"],
                        "src": projection["src"],
                        "dest": projection["dest"],
                    },
                )
            materialized_repos.append({"repo": str(repo_spec["name"]), "first_materialize": first_materialize})
            applied.append(f"cloned repo '{op.subject}' into {repo_root}")
        elif op.kind == "seed_repo_cache":
            repo_spec = _find_repo(spec, op.subject)
            cache_path = repo_cache_path(workspace_root, str(repo_spec["name"]))
            created = ensure_repo_cache(str(repo_spec["url"]), cache_path)
            if created:
                applied.append(f"seeded repo cache for '{op.subject}' at {cache_path}")
            else:
                applied.append(f"refreshed repo cache for '{op.subject}' at {cache_path}")
        elif op.kind == "create_unit_root":
            unit_root = Path(op.target_path)
            unit_root.mkdir(parents=True, exist_ok=True)
            applied.append(f"created unit root for '{op.subject}' at {unit_root}")
        elif op.kind == "write_unit_metadata":
            unit_spec = _find_unit(spec, op.subject)
            unit_root = workspace_root / str(unit_spec["path"])
            unit_root.mkdir(parents=True, exist_ok=True)
            unit_toml = unit_root / "unit.toml"
            unit_toml.write_text(render_unit_toml(unit_spec))
            applied.append(f"wrote unit metadata for '{op.subject}'")
        elif op.kind == "converge_unit_repos":
            unit_spec = _find_unit(spec, op.subject)
            unit_root = workspace_root / str(unit_spec["path"])
            # All declared repos, not just the ones build_plan flagged
            # "missing" -- _clone_isolated handles existing-vs-missing
            # internally (validate vs. stage-clone-rename), so this is what
            # makes an already-present-but-corrupted or origin-mismatched
            # unit-repo checkout actually get caught on every converge pass,
            # not just genuinely-absent ones. Part of §7.3 "one executor":
            # shared code with matching guarantees, not just a shared leaf
            # git-clone call.
            all_repos = [str(r) for r in op.details.get("all_repos", [])]
            converged: list[str] = []
            for repo_name in all_repos:
                repo_spec = _find_repo(spec, repo_name)
                clone_dest = unit_root / repo_name
                cache_path = repo_cache_path(workspace_root, str(repo_spec["name"]))
                result = _clone_isolated(
                    workspace_root,
                    repo_url=str(repo_spec["url"]),
                    dest=clone_dest,
                    reference_repo_root=cache_path,
                )
                if result.first_materialize:
                    converged.append(repo_name)
                    materialized_repos.append({"repo": repo_name, "first_materialize": True})
            unit_toml = unit_root / "unit.toml"
            unit_toml.write_text(render_unit_toml(unit_spec))
            applied.append(f"converged unit '{op.subject}': cloned {', '.join(converged)}")
        else:
            raise SystemExit(f"unknown plan operation kind: {op.kind}")

    if applied:
        _record_apply_state(workspace_root, applied)
    if materialized_repos:
        emit(
            event_type=EventType.WORKSPACE_MATERIALIZED,
            workspace_root=workspace_root,
            actor="system",
            owner_unit="workspace",
            payload={"repos": materialized_repos},
        )

    return {
        "workspace_root": str(workspace_root),
        "applied": applied,
        "operation_count": len(operations),
    }


def render_apply_result(payload: dict[str, object]) -> str:
    applied = [str(item) for item in payload.get("applied", [])]
    lines = ["ApplyResult", f"workspace_root = {payload['workspace_root']}", f"operation_count = {payload['operation_count']}"]
    if not applied:
        lines.append("- no changes applied")
        return "\n".join(lines)
    lines.append("ACTIONS")
    lines.extend(f"- {item}" for item in applied)
    return "\n".join(lines)


def _find_repo(spec: dict[str, object], repo_name: str) -> dict[str, object]:
    for repo in spec.get("repos", []):
        if str(repo.get("name")) == repo_name:
            return repo
    raise SystemExit(f"repo not found in workspace spec: {repo_name}")


def _find_unit(spec: dict[str, object], unit_name: str) -> dict[str, object]:
    for unit in spec.get("units", []):
        if str(unit.get("name")) == unit_name:
            return unit
    raise SystemExit(f"unit not found in workspace spec: {unit_name}")


def _run_materialize_hooks(
    workspace_root: Path,
    repo_root: Path,
    repo_name: str,
    first_materialize: bool,
    *,
    manual_hooks: bool = False,
) -> dict[str, list[dict[str, object]]]:
    hooks = load_repo_hooks(repo_root)
    if not hooks:
        return {"projected_files": []}
    ctx = HookContext(
        workspace_root=workspace_root,
        unit_root=workspace_root,
        lane_root=repo_root,
        repo_root=repo_root,
        repo_name=repo_name,
        lane_owner="workspace",
        lane_subject=repo_name,
        lane_name="workspace",
    )
    projections = apply_file_projections(hooks, ctx)
    run_lifecycle_stage(
        hooks,
        "on_materialize",
        ctx,
        repo_dirty=repo_dirty(repo_root),
        first_materialize=first_materialize,
        allow_manual=manual_hooks,
    )
    projected_files: list[dict[str, object]] = []
    for result in projections:
        if result.status != "applied" or not result.src or not result.dest:
            continue
        projected_files.append(
            {
                "kind": result.name.split(":", 1)[0],
                "src": _relative_workspace_path(workspace_root, Path(result.src)),
                "dest": _relative_workspace_path(workspace_root, Path(result.dest)),
            }
        )
    return {"projected_files": projected_files}


def _relative_workspace_path(workspace_root: Path, path: Path) -> str:
    return os.path.relpath(path, workspace_root)


def render_unit_toml(unit_spec: dict[str, object]) -> str:
    repos = [str(repo) for repo in unit_spec.get("repos", [])]
    repos_str = "[" + ", ".join(f'"{repo}"' for repo in repos) + "]"
    lines = [
        f'name = "{unit_spec["name"]}"',
        'kind = "unit"',
        f"repos = {repos_str}",
    ]
    return "\n".join(lines) + "\n"


def _record_apply_state(workspace_root: Path, actions: list[str]) -> None:
    state_dir = workspace_root / ".grip" / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    state_path = state_dir / "applied.toml"
    timestamp = datetime.now(UTC).isoformat()
    content = [
        "[[applied]]",
        f'timestamp = "{timestamp}"',
        "actions = [" + ", ".join(json.dumps(action) for action in actions) + "]",
        "",
    ]
    if state_path.exists():
        existing = state_path.read_text().rstrip()
        state_path.write_text(existing + "\n\n" + "\n".join(content))
    else:
        state_path.write_text("\n".join(content))


# ---------------------------------------------------------------------------
# Neutral MaterializationPlan executor (config#491 §6.2, §12.1, S4)
#
# Consumes the plan JSON directly (clone/venv/editable_install/project_file
# operations), rather than workspace_spec.toml's repo/unit model above.
# Shares _clone_isolated with the legacy path (§7.3), not a parallel copy.
# ---------------------------------------------------------------------------


def _apply_clone_operation(workspace_root: Path, op: dict[str, object]) -> dict[str, object]:
    dest_path = str(op["dest_path"])
    dest = _resolve_safe_dest(workspace_root, dest_path)
    repo_url = str(op["repo_url"])
    reference_base = op.get("reference_base")
    reference_repo_root: Path | None = None
    if reference_base:
        reference_repo_root = _resolve_contained(
            workspace_root, str(reference_base), field_name="reference_base"
        )

    branch = op.get("branch")
    result = _clone_isolated(
        workspace_root,
        repo_url=repo_url,
        dest=dest,
        branch=str(branch) if branch else None,
        reference_repo_root=reference_repo_root,
    )

    return {
        "kind": "clone",
        "repo_url": repo_url,
        "dest_path": dest_path,
        "first_materialize": result.first_materialize,
        "head_sha": result.head_sha,
    }


def _is_real_venv(dest: Path) -> bool:
    return (dest / "pyvenv.cfg").is_file()


def _apply_venv_operation(workspace_root: Path, op: dict[str, object]) -> dict[str, object]:
    dest_path = str(op["dest_path"])
    dest = _resolve_safe_dest(workspace_root, dest_path)
    if dest.exists():
        # Sentinel r2 P5: an arbitrary existing directory must not be
        # accepted as a valid venv just because a path exists there.
        if not _is_real_venv(dest):
            raise MaterializationPlanError(
                f"venv dest {dest} exists but is not a real venv (no pyvenv.cfg)"
            )
        return {"kind": "venv", "dest_path": dest_path, "created": False}

    python_constraint = str(op.get("python", ">=3.11"))
    staging = dest.parent / f".{dest.name}.staging-{os.getpid()}-{id(dest)}"
    if staging.exists():
        shutil.rmtree(staging, ignore_errors=True)
    dest.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        ["uv", "venv", "--python", python_constraint, str(staging)],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0 or not _is_real_venv(staging):
        shutil.rmtree(staging, ignore_errors=True)
        raise MaterializationPlanError(f"uv venv failed for {dest}:\n{proc.stderr or proc.stdout}")
    staging.rename(dest)
    return {"kind": "venv", "dest_path": dest_path, "created": True}


def _find_direct_url_evidence(venv_path: Path) -> str | None:
    for candidate in sorted(venv_path.glob("lib/*/site-packages/*.dist-info/direct_url.json")):
        return str(candidate.relative_to(venv_path))
    return None


def _apply_editable_install_operation(workspace_root: Path, op: dict[str, object]) -> dict[str, object]:
    venv_path = _resolve_safe_dest(workspace_root, str(op["venv_path"]))
    source_path = _resolve_safe_dest(workspace_root, str(op["source_path"]))
    extras = [str(e) for e in op.get("extras", [])]
    venv_python = venv_path / "bin" / "python"

    target = f"{source_path}[{','.join(extras)}]" if extras else str(source_path)
    proc = subprocess.run(
        ["uv", "pip", "install", "--python", str(venv_python), "--editable", target],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise MaterializationPlanError(
            f"uv pip install --editable failed for {source_path}:\n{proc.stderr or proc.stdout}"
        )
    evidence = _find_direct_url_evidence(venv_path)
    if evidence is None:
        raise MaterializationPlanError(
            f"uv pip install --editable reported success for {source_path}, but no PEP 610 "
            f"direct_url.json evidence was found under {venv_path}"
        )
    return {
        "kind": "editable_install",
        "venv_path": str(op["venv_path"]),
        "source_path": str(op["source_path"]),
        "pep610_evidence": evidence,
    }


def _apply_project_file_operation(workspace_root: Path, op: dict[str, object]) -> dict[str, object]:
    # source_path must resolve under .grip/staging/inputs/ specifically
    # (Sentinel r2 P4 ruling) -- not just anywhere in the workspace. Stromus's
    # r1 catch on #797: reading and then unlink()-ing an unvalidated path is
    # a real arbitrary-file-delete gap, not just a style nit; the follow-up
    # r2 tightened "anywhere in the workspace" to the actual staging contract.
    source_path = _resolve_staging_source(workspace_root, str(op["source_path"]))
    dest_path = str(op["dest_path"])
    dest = _resolve_safe_dest(workspace_root, dest_path)
    expected_sha256 = str(op["source_sha256"])

    if not source_path.exists():
        raise MaterializationPlanError(f"project_file source does not exist: {source_path}")
    content = source_path.read_bytes()
    actual_sha256 = hashlib.sha256(content).hexdigest()
    if actual_sha256 != expected_sha256:
        raise MaterializationPlanError(
            f"project_file hash mismatch for {source_path}: "
            f"expected {expected_sha256}, got {actual_sha256}"
        )

    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(content)
    dest.chmod(0o600)

    # config#491 §6.2: the staged input is a run-scoped opaque artifact,
    # deleted after acknowledgement -- it must not linger once copied.
    source_path.unlink()

    return {"kind": "project_file", "dest_path": dest_path, "source_sha256": expected_sha256}


_MATERIALIZATION_HANDLERS = {
    "clone": _apply_clone_operation,
    "venv": _apply_venv_operation,
    "editable_install": _apply_editable_install_operation,
    "project_file": _apply_project_file_operation,
}


def _require_str(op: dict[str, object], key: str, prefix: str) -> str:
    value = op.get(key)
    if not isinstance(value, str) or not value:
        raise MaterializationPlanError(f"{prefix}: {key} must be a non-empty string")
    return value


def _validate_operation_schema(op: dict[str, object], *, idx: int, workspace_root: Path) -> None:
    """Sentinel r2 P5: schema AND containment are validated for every
    operation up front -- not just type-checked, and not deferred to
    execution time. A plan whose op[2] has an unsafe dest_path must never
    let op[0]/op[1] mutate anything first."""
    kind = op.get("kind")
    prefix = f"operations[{idx}] (kind={kind!r})"
    if kind not in _MATERIALIZATION_HANDLERS:
        raise MaterializationPlanError(f"{prefix}: unknown operation kind")

    if kind == "clone":
        _require_str(op, "repo_url", prefix)
        dest_path = _require_str(op, "dest_path", prefix)
        _resolve_safe_dest(workspace_root, dest_path)
        reference_base = op.get("reference_base")
        if reference_base:
            _resolve_contained(workspace_root, str(reference_base), field_name=f"{prefix}.reference_base")
    elif kind == "venv":
        dest_path = _require_str(op, "dest_path", prefix)
        _resolve_safe_dest(workspace_root, dest_path)
        engine = op.get("engine", "uv")
        if engine != "uv":
            raise MaterializationPlanError(f"{prefix}: engine must be 'uv', got {engine!r}")
    elif kind == "editable_install":
        venv_path = _require_str(op, "venv_path", prefix)
        source_path = _require_str(op, "source_path", prefix)
        _resolve_safe_dest(workspace_root, venv_path)
        _resolve_safe_dest(workspace_root, source_path)
    elif kind == "project_file":
        source_path = _require_str(op, "source_path", prefix)
        dest_path = _require_str(op, "dest_path", prefix)
        _require_str(op, "source_sha256", prefix)
        _resolve_staging_source(workspace_root, source_path)
        _resolve_safe_dest(workspace_root, dest_path)
        mode = op.get("mode", "copy")
        if mode != "copy":
            raise MaterializationPlanError(f"{prefix}: mode must be 'copy' for v1, got {mode!r}")


def _validate_plan_shape(plan: dict[str, object], *, workspace_root: Path) -> None:
    """Sentinel r2 P5: validate the COMPLETE plan before the first
    filesystem mutation -- not one operation validated immediately before
    its own execution, which lets earlier operations mutate state before a
    later operation's invalid shape is ever discovered."""
    _validate_path_safe_token(plan.get("plan_id"), field_name="plan_id")
    # Sentinel/Atlas r2 ruling: one MaterializationPlan is scoped to one
    # opaque unit and carries a required top-level unit_key. gr2 validates
    # it as a path-safe opaque token without interpreting identity.
    _validate_path_safe_token(plan.get("unit_key"), field_name="unit_key")

    operations = plan.get("operations")
    if not isinstance(operations, list) or not operations:
        raise MaterializationPlanError("plan.operations must be a non-empty list")

    seen_dest_paths: set[str] = set()
    for idx, op in enumerate(operations):
        if not isinstance(op, dict):
            raise MaterializationPlanError(f"operations[{idx}] must be an object, got {type(op).__name__}")
        _reject_identity_fields_recursive(op, path=f"operations[{idx}]")
        _validate_operation_schema(op, idx=idx, workspace_root=workspace_root)

        dest_path = op.get("dest_path")
        if isinstance(dest_path, str):
            if dest_path in seen_dest_paths:
                raise MaterializationPlanError(f"duplicate dest_path across operations: {dest_path!r}")
            seen_dest_paths.add(dest_path)


def _materialization_receipt_path(workspace_root: Path, plan_id: str) -> Path:
    return workspace_root / ".grip" / "state" / "materialization" / f"{plan_id}.json"


def _write_materialization_receipt(
    workspace_root: Path,
    plan: dict[str, object],
    op_results: list[dict[str, object]],
) -> Path:
    """config#491 §12.1: neutral receipts carry the plan hash, opaque unit
    key, and per-operation structural evidence -- no identity, org, channel,
    secret, or memory content. Written atomically (temp file + rename), not
    directly, matching the same publish-don't-partially-write discipline as
    _clone_isolated's staging rename."""
    plan_hash = hashlib.sha256(json.dumps(plan, sort_keys=True).encode()).hexdigest()
    receipt = {
        "plan_id": plan["plan_id"],
        "unit_key": plan["unit_key"],
        "plan_hash": plan_hash,
        "schema_version": plan.get("schema_version", 1),
        "workspace_spec_sha256": plan.get("workspace_spec_sha256"),
        "applied_at": datetime.now(UTC).isoformat(),
        "operations": op_results,
    }
    receipt_path = _materialization_receipt_path(workspace_root, str(plan["plan_id"]))
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = receipt_path.with_name(receipt_path.name + f".tmp-{os.getpid()}")
    tmp_path.write_text(json.dumps(receipt, indent=2) + "\n")
    tmp_path.rename(receipt_path)
    return receipt_path


def apply_materialization_plan(
    workspace_root: Path,
    plan: dict[str, object],
    *,
    yes: bool = True,
) -> dict[str, object]:
    """Execute a neutral MaterializationPlan (config#491 §6.2).

    Validate-before-touch (Sentinel r2 P5): the entire plan is schema- and
    containment-validated before any operation executes, so an invalid
    operation anywhere in the plan blocks the whole apply -- not just the
    operations that happen to come after it in list order.

    Identity-free by construction: every operation (recursively, not just
    top-level keys) is checked against _FORBIDDEN_IDENTITY_KEYS.

    Resumable: a rerun re-validates already-materialized state (real clone
    isolation, real venv) and reports first_materialize/created=False rather
    than duplicating work or receipt entries.
    """
    if not yes:
        raise MaterializationPlanError("apply_materialization_plan requires yes=True (no interactive gate)")

    _validate_plan_shape(plan, workspace_root=workspace_root)

    op_results: list[dict[str, object]] = []
    for op in plan["operations"]:
        kind = str(op["kind"])
        handler = _MATERIALIZATION_HANDLERS[kind]
        op_results.append(handler(workspace_root, op))

    receipt_path = _write_materialization_receipt(workspace_root, plan, op_results)

    return {
        "workspace_root": str(workspace_root),
        "plan_id": plan["plan_id"],
        "unit_key": plan["unit_key"],
        "operation_count": len(op_results),
        "operations": op_results,
        "receipt_path": str(receipt_path),
    }
