from __future__ import annotations

import json
import hashlib
import os
import shutil
import tempfile
import tomllib
from pathlib import Path, PurePosixPath, PureWindowsPath

import yaml

from . import grip
from .gitops import git


def gr1_manifest_path(workspace_root: Path) -> Path:
    return workspace_root / ".gitgrip" / "spaces" / "main" / "gripspace.yml"


def gr1_agents_path(workspace_root: Path) -> Path:
    return workspace_root / ".gitgrip" / "agents.toml"


def gr1_state_paths(workspace_root: Path) -> dict[str, Path]:
    gitgrip = workspace_root / ".gitgrip"
    return {
        "state_json": gitgrip / "state.json",
        "sync_state_json": gitgrip / "sync-state.json",
        "griptrees_json": gitgrip / "griptrees.json",
        "manifest_yaml": gr1_manifest_path(workspace_root),
    }


def detect_gr1_workspace(workspace_root: Path) -> dict[str, object]:
    manifest_path = gr1_manifest_path(workspace_root)
    if not manifest_path.exists():
        return {
            "detected": False,
            "workspace_root": str(workspace_root),
            "reason": f"missing {manifest_path}",
        }

    manifest = yaml.safe_load(manifest_path.read_text()) or {}
    repos = manifest.get("repos", {}) or {}
    agents_doc = _load_agents_doc(workspace_root)
    agent_names = sorted(((agents_doc.get("agents") or {}) or {}).keys())
    reference_repos = sorted(name for name, repo in repos.items() if bool((repo or {}).get("reference", False)))
    writable_repos = sorted(name for name in repos.keys() if name not in reference_repos)
    state_paths = gr1_state_paths(workspace_root)

    return {
        "detected": True,
        "workspace_root": str(workspace_root),
        "manifest_path": str(manifest_path),
        "repo_count": len(repos),
        "reference_repo_count": len(reference_repos),
        "agent_count": len(agent_names),
        "repos": sorted(repos.keys()),
        "reference_repos": reference_repos,
        "writable_repos": writable_repos,
        "agents": agent_names,
        "state_files": {key: str(path) for key, path in state_paths.items() if path.exists()},
    }


def migrate_gr1_workspace(workspace_root: Path, *, force: bool = False) -> dict[str, object]:
    detection = detect_gr1_workspace(workspace_root)
    if not detection["detected"]:
        raise SystemExit(detection["reason"])

    grip_dir = workspace_root / ".grip"
    spec_path = grip_dir / "workspace_spec.toml"
    if spec_path.exists() and not force:
        raise SystemExit(f"refusing to overwrite existing gr2 workspace spec: {spec_path}")

    manifest = yaml.safe_load(Path(str(detection["manifest_path"])).read_text()) or {}
    agents_doc = _load_agents_doc(workspace_root)
    compiled = compile_gr1_to_workspace_spec(workspace_root, manifest, agents_doc)

    grip_dir.mkdir(parents=True, exist_ok=True)
    spec_path.write_text(render_workspace_spec(compiled))

    migration_dir = grip_dir / "migrations" / "gr1"
    migration_dir.mkdir(parents=True, exist_ok=True)
    snapshots = preserve_gr1_state(workspace_root, migration_dir)
    summary_path = migration_dir / "migration-summary.json"
    summary = {
        "source": "gr1",
        "workspace_root": str(workspace_root),
        "workspace_spec_path": str(spec_path),
        "repo_count": len(compiled["repos"]),
        "unit_count": len(compiled["units"]),
        "snapshots": snapshots,
    }
    summary_path.write_text(json.dumps(summary, indent=2) + "\n")

    return {
        **summary,
        "units": [unit["name"] for unit in compiled["units"]],
        "repos": [repo["name"] for repo in compiled["repos"]],
    }


def bootstrap_gr1_workspace(workspace_root: Path) -> dict[str, object]:
    """Compile the authoritative gr1 manifest and make its gr2 object store usable.

    This is intentionally narrower than migration: it does not snapshot mutable
    gr1 state or materialize repositories.  It first builds and parses the
    exact WorkspaceSpec bytes, so malformed source cannot create ``.grip``.
    The only persistent result is the git-native grip store plus that generated
    spec.  Repeating the operation accepts only the identical compiled bytes.
    """
    manifest_path = gr1_manifest_path(workspace_root)
    if not manifest_path.is_file():
        raise SystemExit(f"missing canonical gripspace manifest: {manifest_path}")

    manifest_bytes = manifest_path.read_bytes()
    try:
        manifest = yaml.safe_load(manifest_bytes) or {}
    except yaml.YAMLError as exc:
        raise SystemExit(f"invalid canonical gripspace manifest: {exc}") from exc
    if not isinstance(manifest, dict):
        raise SystemExit("canonical gripspace manifest must be a mapping")
    repos = manifest.get("repos", {})
    if not isinstance(repos, dict):
        raise SystemExit("canonical gripspace manifest repos must be a mapping")

    try:
        agents_doc = _load_agents_doc(workspace_root)
    except (OSError, ValueError) as exc:
        raise SystemExit(f"invalid gr1 agents manifest: {exc}") from exc
    if not isinstance(agents_doc, dict):
        raise SystemExit("gr1 agents manifest must be a mapping")

    # All source validation and TOML parsing is deliberately before mkdir, git,
    # or replacement. A failed compile must leave a gr1-only workspace alone.
    try:
        compiled = compile_gr1_to_workspace_spec(workspace_root, manifest, agents_doc)
        spec_bytes = render_workspace_spec(compiled).encode()
        tomllib.loads(spec_bytes.decode())
    except (TypeError, ValueError, KeyError, tomllib.TOMLDecodeError) as exc:
        raise SystemExit(f"cannot compile canonical gripspace manifest: {exc}") from exc

    grip_dir = workspace_root / ".grip"
    if grip_dir.exists() and not grip_dir.is_dir():
        raise SystemExit(f"refusing bootstrap: {grip_dir} is not a directory")
    spec_path = grip_dir / "workspace_spec.toml"
    git_dir = grip_dir / ".git"
    if git_dir.is_file():
        raise SystemExit(f"refusing bootstrap: {git_dir} is not a directory")
    if git_dir.is_dir():
        probe = git(grip_dir, "rev-parse", "--is-inside-work-tree")
        if probe.returncode != 0 or probe.stdout.strip() != "true":
            raise SystemExit(f"refusing bootstrap: {grip_dir} is not a valid git object store")

    if spec_path.exists() and spec_path.read_bytes() != spec_bytes:
        raise SystemExit(f"refusing bootstrap: existing generated spec differs: {spec_path}")

    already_initialized = git_dir.is_dir() and spec_path.exists()
    if not already_initialized:
        try:
            grip.grip_init(workspace_root)
        except grip.GripInitError as exc:
            raise SystemExit(str(exc)) from exc
        if not spec_path.exists():
            _atomic_write(spec_path, spec_bytes)

    return {
        "status": "already_initialized" if already_initialized else "initialized",
        "workspace_root": str(workspace_root),
        "manifest_path": str(manifest_path),
        "workspace_spec_path": str(spec_path),
        "grip_repo_path": str(grip_dir),
        "repo_count": len(compiled["repos"]),
        "unit_count": len(compiled["units"]),
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "workspace_spec_sha256": hashlib.sha256(spec_bytes).hexdigest(),
    }


def _atomic_write(path: Path, content: bytes) -> None:
    """Replace one generated control-plane file without exposing partial TOML."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, raw_temp_path = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temp_path = Path(raw_temp_path)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(content)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(temp_path, path)
    except BaseException:
        temp_path.unlink(missing_ok=True)
        raise


def compile_gr1_to_workspace_spec(
    workspace_root: Path,
    manifest: dict[str, object],
    agents_doc: dict[str, object],
) -> dict[str, object]:
    repos_doc = manifest.get("repos", {}) or {}
    if not isinstance(repos_doc, dict):
        raise ValueError("canonical gripspace manifest repos must be a mapping")
    repos: list[dict[str, object]] = []
    writable_repo_names: list[str] = []

    for repo_name, repo_doc in repos_doc.items():
        safe_repo_name = _safe_workspace_component(repo_name, "repo name")
        if not isinstance(repo_doc, dict):
            raise ValueError(f"repository {safe_repo_name!r} must be a mapping")
        path = repo_doc.get("path", "")
        normalized_path = _safe_workspace_relative_path(path, f"repository {safe_repo_name!r} path")
        repo_item = {
            "name": safe_repo_name,
            "path": normalized_path,
            "url": str(repo_doc.get("url", "")).strip(),
        }
        if "revision" in repo_doc:
            repo_item["default_branch"] = str(repo_doc.get("revision") or "").strip()
        elif "default_branch" in repo_doc:
            repo_item["default_branch"] = str(repo_doc.get("default_branch") or "").strip()
        if repo_doc.get("reference", False):
            repo_item["reference"] = True
        repos.append(repo_item)
        if not repo_doc.get("reference", False):
            writable_repo_names.append(safe_repo_name)

    agents = (agents_doc.get("agents") or {}) or {}
    if not isinstance(agents, dict):
        raise ValueError("gr1 agents manifest agents must be a mapping")
    unit_items = (
        sorted((_safe_workspace_component(unit_name, "agent unit name"), unit_doc) for unit_name, unit_doc in agents.items())
        if agents
        else [("default", {})]
    )
    units: list[dict[str, object]] = []
    for safe_unit_name, unit_doc in unit_items:
        unit_doc = unit_doc or {}
        if not isinstance(unit_doc, dict):
            raise ValueError(f"agent unit {safe_unit_name!r} must be a mapping")
        units.append(
            {
                "name": safe_unit_name,
                "path": f"agents/{safe_unit_name}/home",
                "repos": writable_repo_names,
                "migration_source": {
                    "worktree": unit_doc.get("worktree"),
                    "channel": unit_doc.get("channel"),
                },
            }
        )

    return {
        "workspace_name": workspace_root.name,
        "repos": repos,
        "units": units,
        "workspace_constraints": {
            "migration_source": "gr1",
        },
    }


def _safe_workspace_component(value: object, field: str) -> str:
    """Accept one logical name, never a path fragment or invisible control data."""
    if not isinstance(value, str) or not value or value in {".", ".."}:
        raise ValueError(f"{field} must be a non-empty logical name")
    if "/" in value or "\\" in value or any(ord(char) < 0x20 or ord(char) == 0x7F for char in value):
        raise ValueError(f"{field} must not contain separators or control characters: {value!r}")
    return value


def _safe_workspace_relative_path(value: object, field: str) -> str:
    """Normalize only a safe, portable workspace-relative manifest path."""
    if not isinstance(value, str) or not value or any(ord(char) < 0x20 or ord(char) == 0x7F for char in value):
        raise ValueError(f"{field} must be a non-empty relative path")
    if "\\" in value:
        raise ValueError(f"{field} must use portable '/' separators: {value!r}")
    posix_path = PurePosixPath(value)
    windows_path = PureWindowsPath(value)
    if (
        posix_path.is_absolute()
        or windows_path.is_absolute()
        or windows_path.drive
        or windows_path.root
        or ".." in posix_path.parts
        or str(posix_path) in {".", ""}
    ):
        raise ValueError(f"{field} escapes the workspace: {value!r}")
    return posix_path.as_posix()


def preserve_gr1_state(workspace_root: Path, migration_dir: Path) -> dict[str, str]:
    snapshots: dict[str, str] = {}
    for name, src in gr1_state_paths(workspace_root).items():
        if not src.exists():
            continue
        dest = migration_dir / src.name
        shutil.copy2(src, dest)
        snapshots[name] = str(dest)
    return snapshots


def render_workspace_spec(compiled: dict[str, object]) -> str:
    lines = [
        f'workspace_name = "{compiled["workspace_name"]}"',
        "",
    ]
    constraints = compiled.get("workspace_constraints") or {}
    if constraints:
        lines.append("[workspace_constraints]")
        for key, value in constraints.items():
            lines.append(f'{key} = "{value}"')
        lines.append("")

    for repo in compiled["repos"]:
        lines.extend(
            [
                "[[repos]]",
                f'name = "{repo["name"]}"',
                f'path = "{repo["path"]}"',
                f'url = "{repo["url"]}"',
            ]
        )
        default_branch = str(repo.get("default_branch", "")).strip()
        if default_branch:
            lines.append(f'default_branch = "{default_branch}"')
        if repo.get("reference", False):
            lines.append("reference = true")
        lines.append("")

    for unit in compiled["units"]:
        lines.extend(
            [
                "[[units]]",
                f'name = "{unit["name"]}"',
                f'path = "{unit["path"]}"',
                "repos = [" + ", ".join(f'"{repo}"' for repo in unit["repos"]) + "]",
            ]
        )
        lines.append("")

    return "\n".join(lines)


def render_detection(payload: dict[str, object]) -> str:
    if not payload["detected"]:
        return "\n".join(["Gr1Detection", "detected = false", f"reason = {payload['reason']}"])
    lines = [
        "Gr1Detection",
        "detected = true",
        f"workspace_root = {payload['workspace_root']}",
        f"manifest_path = {payload['manifest_path']}",
        f"repo_count = {payload['repo_count']}",
        f"reference_repo_count = {payload['reference_repo_count']}",
        f"agent_count = {payload['agent_count']}",
        "REPOS",
    ]
    lines.extend(f"- {repo}" for repo in payload["repos"])
    lines.append("AGENTS")
    lines.extend(f"- {agent}" for agent in payload["agents"])
    return "\n".join(lines)


def render_migration(payload: dict[str, object]) -> str:
    lines = [
        "Gr1Migration",
        f"workspace_root = {payload['workspace_root']}",
        f"workspace_spec_path = {payload['workspace_spec_path']}",
        f"repo_count = {payload['repo_count']}",
        f"unit_count = {payload['unit_count']}",
        "UNITS",
    ]
    lines.extend(f"- {unit}" for unit in payload["units"])
    lines.append("SNAPSHOTS")
    lines.extend(f"- {name}\t{path}" for name, path in payload["snapshots"].items())
    return "\n".join(lines)


def workspace_status(workspace_root: Path) -> dict[str, object]:
    """Report workspace state: gr1-only, gr2-only, coexistence, or none."""
    has_gr1 = gr1_manifest_path(workspace_root).exists()
    gr2_spec_path = workspace_root / ".grip" / "workspace_spec.toml"
    has_gr2 = gr2_spec_path.exists()
    migration_dir = workspace_root / ".grip" / "migrations" / "gr1"
    has_migration = migration_dir.exists() and (migration_dir / "migration-summary.json").exists()

    if has_gr1 and has_gr2:
        phase = "coexistence"
    elif has_gr1:
        phase = "gr1-only"
    elif has_gr2:
        phase = "gr2-only"
    else:
        phase = "none"

    result: dict[str, object] = {
        "workspace_root": str(workspace_root),
        "gr1": has_gr1,
        "gr2": has_gr2,
        "coexistence": has_gr1 and has_gr2,
        "migration_snapshot": has_migration,
        "phase": phase,
    }

    if has_gr1:
        detection = detect_gr1_workspace(workspace_root)
        result["gr1_repo_count"] = detection.get("repo_count", 0)
        result["gr1_agents"] = detection.get("agents", [])

    if has_gr2:
        import tomllib
        with gr2_spec_path.open("rb") as fh:
            spec = tomllib.load(fh)
        repos = spec.get("repos", [])
        units = spec.get("units", [])
        result["gr2_repo_count"] = len(repos)
        result["gr2_unit_count"] = len(units)
        result["gr2_spec_path"] = str(gr2_spec_path)

    return result


def render_status(payload: dict[str, object]) -> str:
    lines = [
        "WorkspaceStatus",
        f"phase = {payload['phase']}",
        f"workspace_root = {payload['workspace_root']}",
    ]
    if payload["gr1"]:
        lines.append(f"gr1 = true (repos: {payload.get('gr1_repo_count', '?')})")
    if payload["gr2"]:
        lines.append(f"gr2 = true (repos: {payload.get('gr2_repo_count', '?')}, units: {payload.get('gr2_unit_count', '?')})")
    if payload["coexistence"]:
        lines.append("coexistence = true (both .gitgrip and .grip present)")
    if payload.get("migration_snapshot"):
        lines.append("migration_snapshot = true (.grip/migrations/gr1/ present)")
    if not payload["gr1"] and not payload["gr2"]:
        lines.append("No workspace detected. Run `gr2 workspace init` or `gr2 workspace migrate-gr1`.")
    return "\n".join(lines)


def _load_agents_doc(workspace_root: Path) -> dict[str, object]:
    path = gr1_agents_path(workspace_root)
    if not path.exists():
        return {}
    import tomllib

    with path.open("rb") as fh:
        return tomllib.load(fh)
