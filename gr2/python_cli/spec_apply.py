from __future__ import annotations

import dataclasses
import hashlib
import importlib.resources
import json
import os
import shutil
import stat
import subprocess
import tomllib
from datetime import UTC, datetime
from pathlib import Path

from jsonschema import Draft202012Validator

from .events import EventType, emit
from .gitops import (
    checkout_branch,
    clone_repo,
    current_branch,
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
# Pinned MaterializationPlan v1 schema (config#492, merged 4b36896)
#
# The normative wire contract. Round 3 (Atlas): a hand-rolled validator is a
# separate, looser contract by construction -- nine plans the pinned schema
# rejects were being accepted. The packaged schema's bytes are verified
# against the pinned SHA-256 at load; a mismatch fails closed rather than
# validating against an unpinned document.
# ---------------------------------------------------------------------------

_PLAN_SCHEMA_SHA256 = "a5061501ba6651d7432d87d57f1c85902e5dec076f860a47faa299f5f590231c"
_PLAN_SCHEMA_RESOURCE = "schemas/gr2-materialization-plan-v1.schema.json"
_plan_validator: Draft202012Validator | None = None


def _read_plan_schema_bytes() -> bytes:
    """Load the packaged schema. importlib.resources is the real
    (installed) path; the sibling-directory fallback covers the in-repo
    pytest context, where conftest.py injects a bare `gr2` module without
    a __spec__ and resources lookup cannot traverse it. Either way the
    bytes are verified against the pinned SHA-256 before use, so WHERE
    they load from cannot weaken WHAT gets enforced."""
    try:
        return (importlib.resources.files("gr2") / _PLAN_SCHEMA_RESOURCE).read_bytes()
    except Exception:
        return (Path(__file__).resolve().parent.parent / "gr2" / _PLAN_SCHEMA_RESOURCE).read_bytes()


def _load_plan_validator() -> Draft202012Validator:
    global _plan_validator
    if _plan_validator is None:
        raw = _read_plan_schema_bytes()
        actual = hashlib.sha256(raw).hexdigest()
        if actual != _PLAN_SCHEMA_SHA256:
            raise MaterializationPlanError(
                f"packaged MaterializationPlan v1 schema hash mismatch: expected "
                f"{_PLAN_SCHEMA_SHA256}, got {actual} -- refusing to validate against "
                "an unpinned schema (config#492 §6.2.1)"
            )
        _plan_validator = Draft202012Validator(json.loads(raw))
    return _plan_validator


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
    """Defense in depth alongside the per-kind field allowlist below: even
    an allowed field's VALUE should never carry an identity-shaped key.
    The allowlist is what actually PROVES identity-freedom (round 2,
    Atlas/Sentinel: "a blacklist cannot prove identity-free construction"
    -- display_name, or any field name nobody enumerated, sails through a
    blacklist undetected); this stays as a second layer, not the primary one."""
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


def _canonicalize_workspace_path(workspace_root: Path, relative: str, *, field_name: str) -> Path:
    """config#492 §6.2.1 invariant #2: reject absolute paths, `~`,
    backslashes, empty segments, `.` or `..` segments, NUL, any existing
    symlink in the path prefix, and any resolved escape.

    Segment checks run on the RAW string split on "/" -- Path() silently
    normalizes single-dot segments away (Path("a/./b").parts == ("a","b")),
    so parts-based scanning cannot see them (round 3: "." segment was one
    of the nine schema-invalid plans being accepted).

    The symlink-free-prefix walk (lstat per existing component, including
    the final one) is what a resolve()-based containment check structurally
    cannot provide: with `.grip/staging/inputs` itself a symlink to
    `<workspace>/rogue`, BOTH the candidate and the staging root resolve
    through the same link, so "resolved candidate is under resolved root"
    holds while the real bytes come from outside staging (Atlas's round-3
    mutant, reproduced before fixing).

    Returns the fully resolved canonical path -- for filesystem operations
    and ALL comparison (duplicate detection, cache-namespace checks)."""
    if not relative or relative.startswith("/") or relative.startswith("~"):
        raise MaterializationPlanError(f"{field_name} must be relative to the workspace root: {relative!r}")
    if "\\" in relative or "\x00" in relative:
        raise MaterializationPlanError(f"{field_name} must not contain backslashes or NUL: {relative!r}")
    segments = relative.split("/")
    if any(seg in ("", ".", "..") for seg in segments):
        raise MaterializationPlanError(
            f"{field_name} must not contain empty, '.', or '..' segments: {relative!r}"
        )
    walker = workspace_root
    for seg in segments:
        walker = walker / seg
        if walker.is_symlink():
            raise MaterializationPlanError(
                f"{field_name} passes through a symlink at {walker} -- path prefixes must be "
                "symlink-free (config#492 §6.2.1 #2)"
            )
    workspace_resolved = workspace_root.resolve()
    candidate = (workspace_root / relative).resolve()
    if candidate != workspace_resolved and workspace_resolved not in candidate.parents:
        raise MaterializationPlanError(f"{field_name} escapes the workspace root: {relative!r}")
    return candidate


def _resolve_safe_dest(workspace_root: Path, dest_path: str) -> Path:
    return _canonicalize_workspace_path(workspace_root, dest_path, field_name="dest_path")


_STAGING_INPUTS_SUBPATH = Path(".grip") / "staging" / "inputs"


def _resolve_staging_source(workspace_root: Path, source_path: str) -> Path:
    """config#492 §6.2.1 #7: source_path must be a single opaque artifact
    DIRECTLY inside .grip/staging/inputs/ (the schema's stagedInputPath
    pattern has no path separator in the artifact token -- nested
    `.grip/staging/inputs/a/b` is schema-invalid and rejected here too),
    reached through a symlink-free prefix. The per-component symlink walk
    in _canonicalize_workspace_path covers both the prefix AND the final
    component, so an in-staging alias symlink (inputs/alias -> inputs/real)
    rejects as well -- Sentinel's round-3 fixture: the alias was accepted,
    the RESOLVED target got unlinked, and the dangling alias stayed."""
    resolved = _canonicalize_workspace_path(workspace_root, source_path, field_name="source_path")
    staging_root = (workspace_root / _STAGING_INPUTS_SUBPATH).resolve()
    if resolved.parent != staging_root:
        raise MaterializationPlanError(
            f"source_path must be directly inside .grip/staging/inputs/ (no nesting): {source_path!r}"
        )
    return resolved


_CACHE_NAMESPACE_SUBPATH = Path(".grip") / "cache" / "repos"


def _validate_reference_base(workspace_root: Path, reference_base: str, *, repo_url: str) -> Path:
    """config#492 §6.2.1 invariant #5: a declared reference_base must BE
    the workspace-managed bare cache with canonical remote equal to
    repo_url. Fail CLOSED on every unverifiable state (round 3, Atlas):

    - the round-2 version accepted an existing cache whose
      remote_origin_url returned None ("if origin is not None and differs"
      is fail-open on absent provenance);
    - a non-Git directory at the canonical cache path was accepted, then
      `git clone --reference-if-able` silently skipped the unusable
      reference and the receipt still claimed the alternate was approved;
    - a missing cache cannot have its provenance verified at all.

    All three now reject before any git command runs."""
    resolved = _canonicalize_workspace_path(workspace_root, reference_base, field_name="reference_base")
    cache_namespace = (workspace_root / _CACHE_NAMESPACE_SUBPATH).resolve()
    if resolved.parent != cache_namespace or resolved.suffix != ".git":
        raise MaterializationPlanError(
            f"reference_base must be a *.git cache directly inside .grip/cache/repos/: {reference_base!r}"
        )
    if not resolved.exists():
        raise MaterializationPlanError(
            f"reference_base {reference_base!r} does not exist -- a declared cache whose "
            "provenance cannot be verified is rejected, not silently skipped (config#492 §6.2.1 #5)"
        )
    if not is_git_dir(resolved):
        raise MaterializationPlanError(
            f"reference_base {reference_base!r} is not a bare git repository (config#492 §6.2.1 #5)"
        )
    cache_origin = remote_origin_url(resolved)
    if cache_origin is None:
        raise MaterializationPlanError(
            f"reference_base {reference_base!r} has no canonical remote -- absent provenance "
            "is rejected, not treated as acceptable (config#492 §6.2.1 #5)"
        )
    if cache_origin != repo_url:
        raise MaterializationPlanError(
            f"reference_base {reference_base!r} has canonical origin {cache_origin!r}, "
            f"expected {repo_url!r} -- a cache seeded from a different remote cannot be reused"
        )
    return resolved


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
    # The alternate line actually OBSERVED in .git/objects/info/alternates,
    # or None. Round 3 (Atlas): receipt evidence must be observation, not
    # an echo of what the plan requested -- a clone that completed without
    # any alternates file was being receipted alternate_approved=true.
    observed_alternate: str | None


def _read_observed_alternate(repo_root: Path) -> str | None:
    alternates_file = repo_root / ".git" / "objects" / "info" / "alternates"
    if not alternates_file.exists():
        return None
    lines = [line.strip() for line in alternates_file.read_text().splitlines() if line.strip()]
    return lines[0] if lines else None


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
    if common_dir_proc.returncode != 0:
        # Round 2 (Sentinel): fail CLOSED, not open. The prior version
        # silently skipped this whole check when the subprocess itself
        # failed -- "cannot verify isolation" must reject, not be treated
        # as "assume it's fine."
        raise MaterializationPlanError(
            f"clone at {repo_root}: git rev-parse --git-common-dir failed, cannot verify isolation "
            f"(config#491 §8.1): {common_dir_proc.stderr or common_dir_proc.stdout}"
        )
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

    # config#492 §6.2.1 #5, round 4 (Atlas): "an existing destination is
    # validated on every apply and, when reference_base is present, the
    # resulting clone's only alternate is that cache." The round-3 form
    # returned early here whenever the alternates file was absent, so the
    # REQUIRED-alternate half ran only on the fresh-clone path -- an
    # existing ordinary clone with no alternates was accepted under a plan
    # declaring a reference_base. Checked here, in the one function BOTH
    # the fresh-staging and existing-destination paths call, rather than
    # at a fresh-only call site: that is what makes the two paths share a
    # single validation contract instead of drifting apart again.
    alternates_file = git_path / "objects" / "info" / "alternates"
    if not alternates_file.exists():
        if reference_repo_root is not None:
            raise MaterializationPlanError(
                f"clone at {repo_root} carries no alternate but the plan declares "
                f"reference {reference_repo_root} -- declared object sharing was not achieved "
                "(config#492 §6.2.1 #5)"
            )
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
        # config#492 §6.2.1 (round 3, Atlas): declared plan fields are
        # DESIRED STATE, validated on every apply -- not inputs consumed
        # only during first creation. An existing healthy clone on `main`
        # was accepting a plan declaring `branch: feature` and silently
        # staying on `main`. Never force-switch (prior source ruling);
        # a mismatch blocks with a repair-is-manual message instead.
        if branch:
            actual_branch = current_branch(dest)
            if actual_branch != branch:
                raise MaterializationPlanError(
                    f"existing clone at {dest} is on branch {actual_branch!r} but the plan "
                    f"declares {branch!r} -- refusing to force-switch a healthy existing "
                    "clone; reconcile manually (config#492 §6.2.1 #5, §8.3)"
                )
        return CloneResult(
            first_materialize=False,
            origin_url=remote_origin_url(dest),
            head_sha=current_head_sha(dest),
            observed_alternate=_read_observed_alternate(dest),
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

    # Note: the declared-reference/no-alternate rejection now lives inside
    # _validate_clone_isolation above, which ran against `staging` before
    # this rename -- so a fresh clone that failed to realize its declared
    # object sharing never reaches publication at all, and the existing-
    # destination path gets the identical check. One contract, both paths.
    dest.parent.mkdir(parents=True, exist_ok=True)
    staging.rename(dest)
    return CloneResult(
        first_materialize=True,
        origin_url=remote_origin_url(dest),
        head_sha=current_head_sha(dest),
        observed_alternate=_read_observed_alternate(dest),
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
        #
        # Round 2 (Atlas/Sentinel P1): scheduled whenever a unit has ANY
        # declared repos, not only when build_plan's cheap existence check
        # finds something missing. A unit whose repos are all PRESENT but
        # one has the wrong origin was never getting converge_unit_repos
        # scheduled at all -- build_plan can't detect an origin mismatch
        # without running real git commands, which it deliberately avoids
        # (planning stays cheap); the fix is to always schedule the check
        # and let apply-time's real _clone_isolated validation (cheap
        # existence check bypassed) catch it, not to make planning itself
        # do git work.
        declared_repos = [str(r) for r in unit.get("repos", [])]
        missing_repos = [r for r in declared_repos if not (unit_root / r).exists()]
        if declared_repos:
            reason = (
                f"missing repo checkouts: {', '.join(missing_repos)}"
                if missing_repos
                else "validate declared repo checkouts (origin/isolation) on every pass"
            )
            operations.append(
                PlanOperation(
                    kind="converge_unit_repos",
                    subject=unit_name,
                    target_path=str(unit_root),
                    reason=reason,
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
            # Round 2 (Atlas P1): routed through the SAME operation-dict
            # dispatch the MaterializationPlan path uses, not a manually
            # invoked _clone_isolated -- "one executor" means one dispatch
            # path, not just a shared leaf clone primitive underneath two
            # separate call sites. reference_base is declared only when the
            # cache actually exists: a declared-but-unverifiable cache is a
            # hard rejection (config#492 §6.2.1 #5), while cloning
            # self-contained without one is legitimate.
            legacy_clone_op: dict[str, object] = {
                "kind": "clone",
                "repo_url": str(repo_spec["url"]),
                "dest_path": _relative_workspace_path(workspace_root, repo_root),
            }
            if cache_path.exists():
                legacy_clone_op["reference_base"] = _relative_workspace_path(workspace_root, cache_path)
            clone_result = _apply_clone_operation(workspace_root, legacy_clone_op)
            first_materialize = bool(clone_result["first_materialize"])
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
                converge_clone_op: dict[str, object] = {
                    "kind": "clone",
                    "repo_url": str(repo_spec["url"]),
                    "dest_path": _relative_workspace_path(workspace_root, clone_dest),
                }
                if cache_path.exists():
                    converge_clone_op["reference_base"] = _relative_workspace_path(
                        workspace_root, cache_path
                    )
                clone_result = _apply_clone_operation(workspace_root, converge_clone_op)
                if clone_result["first_materialize"]:
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
        # Bound to the declared cache namespace + canonical-origin verified
        # (round 2 §8.2), not just "somewhere in the workspace."
        reference_repo_root = _validate_reference_base(workspace_root, str(reference_base), repo_url=repo_url)

    branch = op.get("branch")
    result = _clone_isolated(
        workspace_root,
        repo_url=repo_url,
        dest=dest,
        branch=str(branch) if branch else None,
        reference_repo_root=reference_repo_root,
    )

    # config#491 §12.1 evidence: repo URL, destination, HEAD, clone-state,
    # cache path, and alternate evidence. Every field here is an
    # OBSERVATION of resulting state, not an echo of the request -- round 3
    # (Atlas): alternate_approved was being derived from "a reference was
    # passed," reporting true for a clone with no alternates file at all.
    return {
        "kind": "clone",
        "repo_url": repo_url,
        "dest_path": dest_path,
        "first_materialize": result.first_materialize,
        "head_sha": result.head_sha,
        "observed_origin": result.origin_url,
        "cache_path": str(reference_base) if reference_base else None,
        "observed_alternate": result.observed_alternate,
        "alternate_approved": result.observed_alternate is not None,
    }


def _probe_venv_interpreter(dest: Path, *, python_constraint: str | None = None) -> Path | None:
    """config#492 §6.2.1 invariant #6: an existing venv is valid only when
    pyvenv.cfg is a regular file AND the interpreter is present, executable,
    and succeeds under an isolated bounded probe reporting a resolved
    sys.prefix equal to the declared venv path, a distinct sys.base_prefix,
    and (when a constraint is declared) an interpreter version satisfying
    the plan's `python` specifier.

    Round 3 (Atlas + Sentinel): the round-2 check (pyvenv.cfg present +
    executable file at bin/python*) accepted a directory holding a forged
    pyvenv.cfg plus an executable SHELL SCRIPT named bin/python3, and a
    real-shaped venv was accepted under python=">=99" -- an unsatisfiable
    constraint no genuine interpreter could meet. File presence and the
    executable bit prove nothing; only running the pinned probe does."""
    pyvenv_cfg = dest / "pyvenv.cfg"
    if pyvenv_cfg.is_symlink() or not pyvenv_cfg.is_file():
        return None
    interpreter: Path | None = None
    for candidate_name in ("python3", "python"):
        candidate = dest / "bin" / candidate_name
        if candidate.is_file() and os.access(candidate, os.X_OK):
            interpreter = candidate
            break
    if interpreter is None:
        return None
    probe_code = (
        "import sys; print(sys.prefix); print(sys.base_prefix); "
        "print('.'.join(map(str, sys.version_info[:3])))"
    )
    try:
        proc = subprocess.run(
            [str(interpreter), "-I", "-c", probe_code],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    if proc.returncode != 0:
        return None
    lines = proc.stdout.strip().splitlines()
    if len(lines) != 3:
        return None
    try:
        reported_prefix = Path(lines[0]).resolve()
        reported_base = Path(lines[1]).resolve()
    except OSError:
        return None
    if reported_prefix != dest.resolve():
        return None
    if reported_prefix == reported_base:
        return None
    if python_constraint is not None:
        # Deferred import: packaging is a runtime dependency, but only this
        # probe needs it -- keep module import time flat.
        from packaging.specifiers import InvalidSpecifier, SpecifierSet
        from packaging.version import InvalidVersion, Version

        try:
            specifier = SpecifierSet(python_constraint)
            version = Version(lines[2])
        except (InvalidSpecifier, InvalidVersion):
            return None
        if version not in specifier:
            return None
    return interpreter


def _apply_venv_operation(workspace_root: Path, op: dict[str, object]) -> dict[str, object]:
    dest_path = str(op["dest_path"])
    dest = _resolve_safe_dest(workspace_root, dest_path)
    # No default: the pinned v1 schema requires `python` explicitly
    # (round 3 -- do not preserve defaulting/coercion behavior).
    python_constraint = str(op["python"])
    if dest.exists():
        interpreter = _probe_venv_interpreter(dest, python_constraint=python_constraint)
        if interpreter is None:
            raise MaterializationPlanError(
                f"venv dest {dest} exists but fails the isolated venv probe "
                "(pyvenv.cfg not a regular file, no executable interpreter, probe's "
                "sys.prefix/sys.base_prefix report does not match the declared venv, or the "
                f"interpreter does not satisfy the declared constraint {python_constraint!r} -- "
                "config#492 §6.2.1 #6; file presence alone is not venv evidence)"
            )
        return {
            "kind": "venv",
            "dest_path": dest_path,
            "created": False,
            "interpreter_path": str(interpreter.relative_to(dest)),
        }

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
    if proc.returncode != 0:
        shutil.rmtree(staging, ignore_errors=True)
        raise MaterializationPlanError(f"uv venv failed for {dest}:\n{proc.stderr or proc.stdout}")
    # Rename BEFORE probing: sys.prefix is derived at runtime from where
    # the interpreter binary currently resides, so the probe must run at
    # the final path -- probing at the staging path would report the
    # staging prefix and never match the declared dest. Probe failure
    # after rename rolls the fresh creation back entirely.
    staging.rename(dest)
    interpreter = _probe_venv_interpreter(dest, python_constraint=python_constraint)
    if interpreter is None:
        shutil.rmtree(dest, ignore_errors=True)
        raise MaterializationPlanError(
            f"freshly created venv at {dest} fails the isolated venv probe (config#492 §6.2.1 #6)"
        )
    # config#491 §12.1 evidence: venv interpreter.
    return {
        "kind": "venv",
        "dest_path": dest_path,
        "created": True,
        "interpreter_path": str(interpreter.relative_to(dest)),
    }


def _find_direct_url_evidence(venv_path: Path, source_path: Path) -> tuple[str, str] | None:
    """Returns (relative direct_url.json path, distribution name) for the
    editable install of THIS source, or None.

    Round 4 (Atlas): the round-3 form returned the first sorted
    direct_url.json in the venv, so a plan installing editable `alpha`
    then editable `beta` receipted beta's operation with ALPHA's PEP 610
    path and distribution -- a structurally complete receipt that is
    false. Evidence must be bound to the artifact it claims to describe:
    match the decoded PEP 610 `url` against this operation's resolved
    source and require dir_info.editable, then derive the distribution
    from the MATCHED row rather than from whichever row sorted first."""
    from urllib.parse import unquote, urlparse

    target = source_path.resolve()
    for candidate in sorted(venv_path.glob("lib/*/site-packages/*.dist-info/direct_url.json")):
        try:
            record = json.loads(candidate.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        url = record.get("url")
        if not isinstance(url, str):
            continue
        parsed = urlparse(url)
        if parsed.scheme != "file":
            continue
        try:
            recorded = Path(unquote(parsed.path)).resolve()
        except OSError:
            continue
        if recorded != target:
            continue
        dir_info = record.get("dir_info")
        if not isinstance(dir_info, dict) or dir_info.get("editable") is not True:
            continue
        dist_info_name = candidate.parent.name
        distribution = dist_info_name.removesuffix(".dist-info").split("-")[0]
        return str(candidate.relative_to(venv_path)), distribution
    return None


def _apply_editable_install_operation(workspace_root: Path, op: dict[str, object]) -> dict[str, object]:
    venv_path = _resolve_safe_dest(workspace_root, str(op["venv_path"]))
    source_path = _resolve_safe_dest(workspace_root, str(op["source_path"]))
    # No default: the pinned v1 schema requires `extras` explicitly.
    extras = [str(e) for e in op["extras"]]
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
    evidence = _find_direct_url_evidence(venv_path, source_path)
    if evidence is None:
        raise MaterializationPlanError(
            f"uv pip install --editable reported success for {source_path}, but no PEP 610 "
            f"direct_url.json evidence matching that source (editable, url == source) was "
            f"found under {venv_path}"
        )
    pep610_path, distribution = evidence
    # config#491 §12.1 evidence: editable source path, extras, distribution.
    return {
        "kind": "editable_install",
        "venv_path": str(op["venv_path"]),
        "source_path": str(op["source_path"]),
        "extras": extras,
        "distribution": distribution,
        "pep610_evidence": pep610_path,
    }


def _verify_staged_source(source_path: Path, expected_sha256: str) -> None:
    """config#492 §6.2.1 #7: a staged input must exist, be a regular
    non-symlink file, and its REOPENED bytes must hash to source_sha256.

    Extracted in round 4 so the first-run and rerun-cleanup paths call one
    function rather than each implementing their own subset -- the rerun
    path previously skipped all three checks and deleted whatever it
    found. Any future verification added here reaches both paths by
    construction, which is the point: the recurring finding-generator has
    been "the second path skips what the first path does"."""
    if not source_path.exists():
        raise MaterializationPlanError(f"project_file source does not exist: {source_path}")
    # The symlink-free prefix (including the final component) is already
    # enforced by _canonicalize_workspace_path's per-component walk; this
    # rejects the remaining non-regular shapes (fifo, directory, device).
    if not stat.S_ISREG(os.lstat(source_path).st_mode):
        raise MaterializationPlanError(
            f"project_file source is not a regular file: {source_path} (config#492 §6.2.1 #7)"
        )
    actual_sha256 = hashlib.sha256(source_path.read_bytes()).hexdigest()
    if actual_sha256 != expected_sha256:
        raise MaterializationPlanError(
            f"project_file hash mismatch for {source_path}: "
            f"expected {expected_sha256}, got {actual_sha256}"
        )


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

    # config#492 §6.2.1 #8: idempotent rerun. After a successful prior
    # apply, the staged source is legitimately gone (cleaned up post-
    # receipt) while dest carries the verified bytes -- that operation is
    # complete, not an error. And if cleanup was interrupted AFTER receipt
    # publication (dest correct, source still present), the rerun performs
    # the idempotent cleanup rather than re-copying.
    if dest.exists():
        dest_sha256 = hashlib.sha256(dest.read_bytes()).hexdigest()
        if dest_sha256 == expected_sha256:
            result: dict[str, object] = {
                "kind": "project_file",
                "source_path": str(op["source_path"]),
                "dest_path": dest_path,
                "source_sha256": expected_sha256,
                "already_projected": True,
            }
            if source_path.exists():
                # Round 4 (Atlas): the rerun path scheduled ANY existing
                # staged source for deletion without verifying it -- so a
                # source recreated with tampered bytes after the receipt
                # was silently destroyed. Destructive cleanup must verify
                # the artifact it is destroying, using the SAME function
                # the first run uses, so the two paths cannot drift.
                _verify_staged_source(source_path, expected_sha256)
                result["_pending_unlink"] = str(source_path)
            return result

    _verify_staged_source(source_path, expected_sha256)
    content = source_path.read_bytes()

    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(content)
    dest.chmod(0o600)

    # config#492 §6.2.1 #8: "the staging artifact is removed only after
    # the final materialization receipt containing that operation's
    # evidence has been atomically published and made durable." A
    # successful destination write is NOT acknowledgement. _pending_unlink
    # is an internal-only key (stripped before the result becomes receipt
    # content): apply_materialization_plan performs the actual unlink only
    # after the durable (fsync'd, atomically replaced) receipt exists.
    return {
        "kind": "project_file",
        "source_path": str(op["source_path"]),
        "dest_path": dest_path,
        "source_sha256": expected_sha256,
        "already_projected": False,
        "_pending_unlink": str(source_path),
    }


_MATERIALIZATION_HANDLERS = {
    "clone": _apply_clone_operation,
    "venv": _apply_venv_operation,
    "editable_install": _apply_editable_install_operation,
    "project_file": _apply_project_file_operation,
}


# Round 2 (Atlas/Sentinel P5): exact per-kind ALLOWLISTS, not a blacklist
# scan. "kind" is included in each set since every operation carries it.
# Any field not on its kind's list is rejected -- this is what actually
# proves identity-freedom: a field name nobody thought to blacklist
# (display_name, or anything else) cannot exist on an operation at all,
# rather than merely not being on a list of names someone enumerated.
_CLONE_FIELDS = frozenset({"kind", "repo_url", "dest_path", "branch", "reference_base"})
_VENV_FIELDS = frozenset({"kind", "dest_path", "engine", "python"})
_EDITABLE_INSTALL_FIELDS = frozenset({"kind", "venv_path", "source_path", "extras"})
_PROJECT_FILE_FIELDS = frozenset({"kind", "source_path", "dest_path", "source_sha256", "mode"})

_OPERATION_ALLOWED_FIELDS: dict[str, frozenset[str]] = {
    "clone": _CLONE_FIELDS,
    "venv": _VENV_FIELDS,
    "editable_install": _EDITABLE_INSTALL_FIELDS,
    "project_file": _PROJECT_FILE_FIELDS,
}

_PLAN_ALLOWED_TOP_LEVEL_FIELDS = frozenset(
    {"schema_version", "plan_id", "unit_key", "workspace_spec_sha256", "operations"}
)


def _require_str(op: dict[str, object], key: str, prefix: str) -> str:
    value = op.get(key)
    if not isinstance(value, str) or not value:
        raise MaterializationPlanError(f"{prefix}: {key} must be a non-empty string")
    return value


def _validate_operation_schema(
    op: dict[str, object], *, idx: int, workspace_root: Path
) -> Path | None:
    """Round 2 (Atlas/Sentinel P5): schema AND containment are validated
    for every operation up front, via an exact allowlist -- not just
    type-checked, not deferred to execution time, and not a blacklist that
    only catches enumerated field names. Returns the canonical (resolved)
    dest_path for duplicate/collision detection by the caller, or None for
    operation kinds without one."""
    kind = op.get("kind")
    prefix = f"operations[{idx}] (kind={kind!r})"
    if kind not in _MATERIALIZATION_HANDLERS:
        raise MaterializationPlanError(f"{prefix}: unknown operation kind")

    allowed = _OPERATION_ALLOWED_FIELDS[kind]
    unknown = op.keys() - allowed
    if unknown:
        raise MaterializationPlanError(f"{prefix}: unknown field(s) {sorted(unknown)}")

    if kind == "clone":
        _require_str(op, "repo_url", prefix)
        _require_str(op, "branch", prefix)
        dest_path = _require_str(op, "dest_path", prefix)
        canonical_dest = _resolve_safe_dest(workspace_root, dest_path)
        reference_base = op.get("reference_base")
        if reference_base is not None:
            if not isinstance(reference_base, str) or not reference_base:
                raise MaterializationPlanError(f"{prefix}: reference_base must be a non-empty string")
            _validate_reference_base(workspace_root, reference_base, repo_url=str(op["repo_url"]))
        return canonical_dest
    elif kind == "venv":
        dest_path = _require_str(op, "dest_path", prefix)
        canonical_dest = _resolve_safe_dest(workspace_root, dest_path)
        # No defaults anywhere (round 3): the pinned v1 schema requires
        # engine and python explicitly; this hand layer mirrors it.
        if op.get("engine") != "uv":
            raise MaterializationPlanError(f"{prefix}: engine must be 'uv', got {op.get('engine')!r}")
        _require_str(op, "python", prefix)
        return canonical_dest
    elif kind == "editable_install":
        venv_path = _require_str(op, "venv_path", prefix)
        source_path = _require_str(op, "source_path", prefix)
        _resolve_safe_dest(workspace_root, venv_path)
        _resolve_safe_dest(workspace_root, source_path)
        extras = op.get("extras")
        if not isinstance(extras, list) or not all(isinstance(e, str) for e in extras):
            raise MaterializationPlanError(f"{prefix}: extras must be a list of strings (required)")
        return None
    elif kind == "project_file":
        source_path = _require_str(op, "source_path", prefix)
        dest_path = _require_str(op, "dest_path", prefix)
        _require_str(op, "source_sha256", prefix)
        _resolve_staging_source(workspace_root, source_path)
        canonical_dest = _resolve_safe_dest(workspace_root, dest_path)
        if op.get("mode") != "copy":
            raise MaterializationPlanError(f"{prefix}: mode must be 'copy' for v1, got {op.get('mode')!r}")
        return canonical_dest
    return None


def _validate_plan_shape(plan: dict[str, object], *, workspace_root: Path) -> None:
    """Round 2 (Atlas/Sentinel P5): validate the COMPLETE plan before the
    first filesystem mutation. Round 3: validation against the PINNED v1
    JSON Schema comes first -- the hand-rolled layer below it is defense
    in depth, not the contract. A hand validator is a separate, looser
    contract by construction: nine schema-invalid plans passed it, and
    schema_version=True passed its `!= 1` check because bool is an int
    subclass in Python (True == 1) while JSON Schema's `const: 1`
    correctly distinguishes the types."""
    validator = _load_plan_validator()
    schema_errors = sorted(validator.iter_errors(plan), key=lambda e: list(e.absolute_path))
    if schema_errors:
        first = schema_errors[0]
        location = "/".join(str(p) for p in first.absolute_path) or "<root>"
        raise MaterializationPlanError(
            f"plan rejected by pinned MaterializationPlan v1 schema at {location}: {first.message}"
        )

    unknown_top_level = plan.keys() - _PLAN_ALLOWED_TOP_LEVEL_FIELDS
    if unknown_top_level:
        raise MaterializationPlanError(f"plan: unknown top-level field(s) {sorted(unknown_top_level)}")

    if isinstance(plan.get("schema_version"), bool) or plan.get("schema_version") != 1:
        raise MaterializationPlanError(f"plan.schema_version must be exactly 1, got {plan.get('schema_version')!r}")

    _validate_path_safe_token(plan.get("plan_id"), field_name="plan_id")
    # Sentinel/Atlas r2 ruling: one MaterializationPlan is scoped to one
    # opaque unit and carries a required top-level unit_key. gr2 validates
    # it as a path-safe opaque token without interpreting identity.
    _validate_path_safe_token(plan.get("unit_key"), field_name="unit_key")

    # config#492 §6.2.1 invariant #1: reopen the canonical WorkspaceSpec
    # bytes and verify their SHA-256 equals workspace_spec_sha256. Round 3
    # (Atlas/Sentinel): the field was carried but never verified, and the
    # executor applied with no canonical WorkspaceSpec file at all.
    workspace_spec_sha256 = str(plan["workspace_spec_sha256"])
    spec_file = workspace_spec_path(workspace_root)
    if not spec_file.exists():
        raise MaterializationPlanError(
            "canonical WorkspaceSpec (.grip/workspace_spec.toml) not found -- "
            "workspace_spec_sha256 cannot be verified (config#492 §6.2.1 #1)"
        )
    actual_spec_sha256 = hashlib.sha256(spec_file.read_bytes()).hexdigest()
    if actual_spec_sha256 != workspace_spec_sha256:
        raise MaterializationPlanError(
            f"workspace_spec_sha256 mismatch: plan declares {workspace_spec_sha256}, "
            f"canonical WorkspaceSpec bytes hash to {actual_spec_sha256} -- the plan was "
            "compiled against a different workspace state (config#492 §6.2.1 #1)"
        )

    operations = plan.get("operations")
    if not isinstance(operations, list) or not operations:
        raise MaterializationPlanError("plan.operations must be a non-empty list")

    # Round 2 (Atlas/Sentinel): canonical (resolved, case-folded)
    # comparison, not raw strings -- "units/u1/.venv" and
    # "units/u1/./.venv" are the same real path and must collide, as must
    # case-folded collisions on case-insensitive filesystems (config#491 §3).
    seen_canonical_dests: dict[str, int] = {}
    for idx, op in enumerate(operations):
        if not isinstance(op, dict):
            raise MaterializationPlanError(f"operations[{idx}] must be an object, got {type(op).__name__}")
        _reject_identity_fields_recursive(op, path=f"operations[{idx}]")
        canonical_dest = _validate_operation_schema(op, idx=idx, workspace_root=workspace_root)

        if canonical_dest is not None:
            key = str(canonical_dest).casefold()
            if key in seen_canonical_dests:
                raise MaterializationPlanError(
                    f"operations[{idx}] dest_path collides (case-folded/normalized) with "
                    f"operations[{seen_canonical_dests[key]}]: {canonical_dest}"
                )
            seen_canonical_dests[key] = idx


def _materialization_receipt_path(workspace_root: Path, plan_id: str) -> Path:
    return workspace_root / ".grip" / "state" / "materialization" / f"{plan_id}.json"


def compute_plan_hash(plan: dict[str, object]) -> str:
    """config#492 §6.2.1 #9, the exact pinned canonical serialization:
    UTF-8 JSON, keys sorted, no insignificant whitespace, non-ASCII
    unescaped. Round 3 (Atlas/Sentinel): default json.dumps separators
    (", ", ": ") and ensure_ascii=True produce different bytes and
    therefore a different, non-conformant hash. Public so tests recompute
    it independently rather than trusting the receipt's own value."""
    return hashlib.sha256(
        json.dumps(plan, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def _write_materialization_receipt(
    workspace_root: Path,
    plan: dict[str, object],
    op_results: list[dict[str, object]],
) -> Path:
    """config#492 §6.2.1 #10: publish through a same-directory temporary
    file, file flush and fsync, atomic replace, then parent-directory
    fsync. Round 3 (Sentinel): write_text + rename with ZERO fsync calls
    is not durable acknowledgement -- on power loss the rename can survive
    while the data doesn't, yielding a receipt that "exists" with empty or
    partial content, after the staged inputs it acknowledges were already
    deleted. Every step here is load-bearing, in this order."""
    receipt = {
        "plan_id": plan["plan_id"],
        "unit_key": plan["unit_key"],
        "plan_hash": compute_plan_hash(plan),
        "schema_version": plan["schema_version"],
        "workspace_spec_sha256": plan["workspace_spec_sha256"],
        # config#491 §10 / §12.1 structural stage: MATERIALIZED is the
        # terminal state OSS gr2 can honestly claim on its own.
        "stage": "MATERIALIZED",
        "applied_at": datetime.now(UTC).isoformat(),
        "operations": op_results,
    }
    receipt_path = _materialization_receipt_path(workspace_root, str(plan["plan_id"]))
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = receipt_path.with_name(receipt_path.name + f".tmp-{os.getpid()}")
    with open(tmp_path, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(receipt, indent=2) + "\n")
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp_path, receipt_path)
    dir_fd = os.open(receipt_path.parent, os.O_RDONLY)
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)
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
    pending_unlinks: list[Path] = []
    for op in plan["operations"]:
        kind = str(op["kind"])
        handler = _MATERIALIZATION_HANDLERS[kind]
        result = handler(workspace_root, op)
        # _pending_unlink is orchestration-only, never receipt content --
        # popped before this result is handed to the receipt writer.
        pending_unlink = result.pop("_pending_unlink", None)
        if pending_unlink is not None:
            pending_unlinks.append(Path(pending_unlink))
        op_results.append(result)

    receipt_path = _write_materialization_receipt(workspace_root, plan, op_results)

    # config#491 §6.2: staged inputs are deleted only after durable
    # acknowledgement -- i.e. only after the receipt above has been
    # written successfully. A receipt-write failure now leaves the staged
    # source intact rather than silently deleting evidence of a projection
    # nothing durably confirms happened.
    for source in pending_unlinks:
        source.unlink(missing_ok=True)

    return {
        "workspace_root": str(workspace_root),
        "plan_id": plan["plan_id"],
        "unit_key": plan["unit_key"],
        "operation_count": len(op_results),
        "operations": op_results,
        "receipt_path": str(receipt_path),
    }
