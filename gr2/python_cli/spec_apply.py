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
from .gitops import checkout_branch, clone_repo, ensure_repo_cache, is_git_dir, is_git_repo, repo_dirty
from .hooks import HookContext, apply_file_projections, load_repo_hooks, run_lifecycle_stage


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
            first_materialize = clone_repo(str(repo_spec["url"]), repo_root, reference_repo_root=cache_path)
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
            missing = [str(r) for r in op.details.get("missing_repos", [])]
            converged: list[str] = []
            for repo_name in missing:
                repo_spec = _find_repo(spec, repo_name)
                clone_dest = unit_root / repo_name
                cache_path = repo_cache_path(workspace_root, str(repo_spec["name"]))
                first_materialize = clone_repo(
                    str(repo_spec["url"]), clone_dest, reference_repo_root=cache_path,
                )
                if first_materialize:
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
# Neutral MaterializationPlan executor (config#491 §6.2, S4)
#
# Consumes the plan JSON directly (clone/venv/editable_install/project_file
# operations), rather than workspace_spec.toml's repo/unit model above. Both
# entry points share the same clone/validation primitives -- one executor,
# not a second materializer, per config#491 §7.3.
# ---------------------------------------------------------------------------


class MaterializationPlanError(Exception):
    pass


# config#491 §6.2: "The production plan must not contain: agent display
# name, persistent agent ID, role, org or project, channel, entitlement
# result or reason, secret reference or value, memory body." Checked on
# every operation dict as a structural safety net -- gr2 must not become
# somewhere identity data could leak through even accidentally.
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


def _reject_identity_fields(op: dict[str, object]) -> None:
    present = _FORBIDDEN_IDENTITY_KEYS & op.keys()
    if present:
        raise MaterializationPlanError(
            f"operation carries identity-bearing field(s) {sorted(present)}; "
            "gr2 MaterializationPlan operations must be identity-free (config#491 §6.2)"
        )


def _resolve_safe_dest(workspace_root: Path, dest_path: str) -> Path:
    """Resolve dest_path relative to workspace_root, rejecting escapes.

    config#491 §3: absolute paths, .., symlink escapes, and duplicate
    destinations are blockers. Path.resolve() normalizes .. lexically and
    follows any existing symlinks, so a single containment check after
    resolving catches all three escape shapes.
    """
    if not dest_path or dest_path.startswith("/") or dest_path.startswith("~"):
        raise MaterializationPlanError(f"dest_path must be relative to the workspace root: {dest_path!r}")
    workspace_resolved = workspace_root.resolve()
    candidate = (workspace_root / dest_path).resolve()
    if candidate != workspace_resolved and workspace_resolved not in candidate.parents:
        raise MaterializationPlanError(f"dest_path escapes the workspace root: {dest_path!r}")
    return workspace_root / dest_path


def _validate_clone_isolation(repo_root: Path, *, workspace_root: Path, reference_base: str | None) -> None:
    """gap#6 / config#491 §8.1-8.2: reject worktree-linked clones and
    alternates pointing anywhere except the declared workspace cache."""
    git_path = repo_root / ".git"
    if git_path.is_file():
        raise MaterializationPlanError(
            f"clone at {repo_root} has a worktree-pointer .git file, not a real .git directory "
            "(config#491 §8.1 forbids worktree-linked agent workspaces)"
        )
    if not git_path.is_dir():
        raise MaterializationPlanError(f"clone at {repo_root} has no .git directory")

    alternates_file = git_path / "objects" / "info" / "alternates"
    if not alternates_file.exists():
        return
    approved = (workspace_root / reference_base).resolve() / "objects" if reference_base else None
    for line in alternates_file.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        if approved is None or Path(line).resolve() != approved:
            raise MaterializationPlanError(
                f"clone at {repo_root} has an unapproved alternate: {line} "
                "(config#491 §8.2: alternates may only point at the declared workspace cache)"
            )


def _apply_clone_operation(workspace_root: Path, op: dict[str, object]) -> dict[str, object]:
    dest_path = str(op["dest_path"])
    dest = _resolve_safe_dest(workspace_root, dest_path)
    repo_url = str(op["repo_url"])
    reference_base = op.get("reference_base")
    reference_base = str(reference_base) if reference_base else None
    reference_repo_root = (workspace_root / reference_base) if reference_base else None

    # config#491 §8.3: an existing clone is validated, never blindly reset
    # or replaced. Checked before attempting anything, not after -- a
    # worktree-linked or otherwise damaged existing path must block here,
    # not surface as a confusing "destination already exists" error from
    # `git clone` itself.
    if dest.exists():
        _validate_clone_isolation(dest, workspace_root=workspace_root, reference_base=reference_base)
        first_materialize = False
    else:
        first_materialize = clone_repo(repo_url, dest, reference_repo_root=reference_repo_root)
        branch = op.get("branch")
        if branch:
            checkout_branch(dest, str(branch))
        _validate_clone_isolation(dest, workspace_root=workspace_root, reference_base=reference_base)

    return {
        "kind": "clone",
        "repo_url": repo_url,
        "dest_path": dest_path,
        "first_materialize": first_materialize,
    }


def _apply_venv_operation(workspace_root: Path, op: dict[str, object]) -> dict[str, object]:
    dest_path = str(op["dest_path"])
    dest = _resolve_safe_dest(workspace_root, dest_path)
    if dest.exists():
        return {"kind": "venv", "dest_path": dest_path, "created": False}

    python_constraint = str(op.get("python", ">=3.11"))
    proc = subprocess.run(
        ["uv", "venv", "--python", python_constraint, str(dest)],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise MaterializationPlanError(f"uv venv failed for {dest}:\n{proc.stderr or proc.stdout}")
    return {"kind": "venv", "dest_path": dest_path, "created": True}


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
    return {
        "kind": "editable_install",
        "venv_path": str(op["venv_path"]),
        "source_path": str(op["source_path"]),
    }


def _apply_project_file_operation(workspace_root: Path, op: dict[str, object]) -> dict[str, object]:
    # source_path is workspace-relative, same as dest_path (config#491 §6.2's
    # own example: ".grip/staging/inputs/f_01") -- resolved through the same
    # containment guard as dest, not read+deleted as an arbitrary caller-
    # supplied filesystem path. Stromus's r1 catch on #797: reading and then
    # unlink()-ing an unvalidated path is a real arbitrary-file-delete gap,
    # not just a style nit.
    source_path = _resolve_safe_dest(workspace_root, str(op["source_path"]))
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


def _materialization_receipt_path(workspace_root: Path, plan_id: str) -> Path:
    return workspace_root / ".grip" / "state" / "materialization" / f"{plan_id}.json"


def _write_materialization_receipt(
    workspace_root: Path,
    plan: dict[str, object],
    op_results: list[dict[str, object]],
) -> Path:
    """gap#5: a structured, resumable per-plan receipt -- not an append-only
    action log. config#491 §12.1: neutral receipts carry plan hash, spec
    hash, and per-operation structural evidence; no identity, org, channel,
    secret, or memory content."""
    receipt = {
        "plan_id": plan["plan_id"],
        "schema_version": plan.get("schema_version", 1),
        "workspace_spec_sha256": plan.get("workspace_spec_sha256"),
        "applied_at": datetime.now(UTC).isoformat(),
        "operations": op_results,
    }
    receipt_path = _materialization_receipt_path(workspace_root, str(plan["plan_id"]))
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n")
    return receipt_path


def apply_materialization_plan(
    workspace_root: Path,
    plan: dict[str, object],
    *,
    yes: bool = True,
) -> dict[str, object]:
    """Execute a neutral MaterializationPlan (config#491 §6.2).

    Identity-free by construction: every operation is validated against
    _FORBIDDEN_IDENTITY_KEYS before execution. dest_path is used explicitly
    for every operation kind (gap#4) rather than inferred from a repo name.
    Resumable: a rerun re-validates already-materialized state and reports
    first_materialize/created=False rather than duplicating work or receipt
    entries (idempotent per operation, matching clone_repo's own contract).
    """
    if not yes:
        raise MaterializationPlanError("apply_materialization_plan requires yes=True (no interactive gate)")

    operations = plan.get("operations", [])
    if not isinstance(operations, list) or not operations:
        raise MaterializationPlanError("plan.operations must be a non-empty list")

    op_results: list[dict[str, object]] = []
    for op in operations:
        if not isinstance(op, dict):
            raise MaterializationPlanError(f"operation must be an object, got {type(op).__name__}")
        _reject_identity_fields(op)
        kind = str(op.get("kind", ""))
        handler = _MATERIALIZATION_HANDLERS.get(kind)
        if handler is None:
            raise MaterializationPlanError(f"unknown materialization operation kind: {kind!r}")
        op_results.append(handler(workspace_root, op))

    receipt_path = _write_materialization_receipt(workspace_root, plan, op_results)

    return {
        "workspace_root": str(workspace_root),
        "plan_id": plan["plan_id"],
        "operation_count": len(op_results),
        "operations": op_results,
        "receipt_path": str(receipt_path),
    }
