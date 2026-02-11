# Issue #287: `gr release` — automated release workflow

## Context

The release process is 8+ manual steps that agents must orchestrate perfectly every time: version bump, changelog, build, branch, commit, push, PR, CI wait, merge, GitHub release, and Homebrew update. This is error-prone and the most time-consuming recurring workflow. Issue #287 adds `gr release` to automate this entire pipeline.

## CLI Interface

```
gr release v0.12.4 --notes "Description of changes"
gr release v0.12.4 --dry-run     # Show what would happen
gr release v0.12.4 --json        # Machine-readable step output
gr release v0.12.4 --skip-pr     # Skip PR workflow (bump, tag, release only)
gr release v0.12.4 --repo gitgrip  # Target specific repo for GitHub release
```

## Approach

Single command `gr release` that orchestrates the full pipeline as sequential steps. Reuses existing command functions (branch, commit, push, pr create/merge) rather than reimplementing. Adds `create_release()` to the `HostingPlatform` trait for the GitHub release step.

**Key design decisions:**
- Steps execute sequentially; each step must succeed before the next
- `--dry-run` validates inputs and shows what each step would do
- Version files auto-detected (Cargo.toml, package.json) or configured in manifest
- CHANGELOG.md updated by inserting a new section after the first heading
- The GitHub release is created on the target repo (auto-detected or `--repo`)
- Post-release hooks are optional (configured in manifest)
- Reuses existing `run_pr_merge` with `wait=true` for CI polling

## Changes

### 1. `src/core/manifest.rs` — New release config types

Add to `WorkspaceConfig`:
```rust
pub release: Option<ReleaseConfig>,
```

New types:
```rust
pub struct ReleaseConfig {
    pub version_files: Option<Vec<VersionFileConfig>>,
    pub changelog: Option<String>,  // path, default "CHANGELOG.md"
    pub post_release: Option<Vec<HookCommand>>,  // reuse existing type
}

pub struct VersionFileConfig {
    pub path: String,       // relative to workspace root, e.g. "gitgrip/Cargo.toml"
    pub pattern: String,    // e.g. 'version = "{version}"'
}
```

### 2. `src/platform/types.rs` — New `ReleaseResult` type

```rust
pub struct ReleaseResult {
    pub id: u64,
    pub tag: String,
    pub url: String,
}
```

### 3. `src/platform/traits.rs` — Add `create_release()` to trait

```rust
async fn create_release(
    &self,
    owner: &str,
    repo: &str,
    tag: &str,
    name: &str,
    body: Option<&str>,
    target_commitish: &str,
    draft: bool,
    prerelease: bool,
) -> Result<ReleaseResult, PlatformError> {
    // Default: not supported
}
```

### 4. `src/platform/github.rs` — Implement `create_release()`

Use Octocrab's releases API:
```rust
client.repos(owner, repo).releases()
    .create(tag)
    .name(name)
    .body(body.unwrap_or(""))
    .target_commitish(target)
    .draft(draft)
    .prerelease(prerelease)
    .send()
    .await
```

### 5. `src/cli/commands/release.rs` — Main release command (NEW)

**`pub async fn run_release(opts: ReleaseOptions<'_>) -> anyhow::Result<()>`**

```rust
pub struct ReleaseOptions<'a> {
    pub workspace_root: &'a PathBuf,
    pub manifest: &'a Manifest,
    pub version: &'a str,
    pub notes: Option<&'a str>,
    pub dry_run: bool,
    pub skip_pr: bool,
    pub target_repo: Option<&'a str>,
    pub json: bool,
    pub quiet: bool,
    pub timeout: u64,
}
```

**Step pipeline:**

1. **Validate** — Parse version (strip leading `v` if present, validate semver-like format), check not on main/default branch (unless creating new branch)
2. **Bump versions** — Auto-detect Cargo.toml/package.json in each repo dir, or use manifest `workspace.release.version_files`. Read files, find pattern, replace with new version. For Cargo.toml also run `cargo generate-lockfile` to update Cargo.lock.
3. **Update CHANGELOG** — Find CHANGELOG.md (workspace root or per-repo). Insert `## [vX.Y.Z] - YYYY-MM-DD` section with notes after first `# ` heading.
4. **Build** — For each repo with `agent.build`: run build command via `sh -c`. Skip if no build configured.
5. **Create branch** — Call `run_branch()` to create `release/vX.Y.Z` across repos.
6. **Commit + Push** — Call `run_commit()` with message `"chore: release vX.Y.Z"`, then `run_push()` with `set_upstream=true`.
7. **Create PR** — Call `run_pr_create()` with title `"chore: release vX.Y.Z"` and push=false (already pushed).
8. **Wait for CI + Merge** — Call `run_pr_merge()` with `wait=true`, `force=false`, `timeout=opts.timeout`.
9. **Sync** — After merge, checkout base branch and sync.
10. **Create GitHub release** — Detect target repo (first non-reference repo, or `--repo`). Get platform adapter. Call `create_release()` with tag `vX.Y.Z`, name `vX.Y.Z`, body from `--notes`.
11. **Post-release hooks** — If manifest has `workspace.release.post_release`, execute each hook via `sh -c`, substituting `{version}` in commands.

**Dry-run mode:** Each step prints what it would do but doesn't execute. For file changes, show the diff. For commands, show the command that would run.

**JSON output:**
```json
{
  "version": "0.12.4",
  "steps": [
    {"name": "bump-version", "status": "ok", "files": ["gitgrip/Cargo.toml"]},
    {"name": "changelog", "status": "ok"},
    {"name": "build", "status": "ok"},
    {"name": "branch", "status": "ok", "name": "release/v0.12.4"},
    {"name": "pr", "status": "ok", "number": 282, "url": "..."},
    {"name": "ci", "status": "ok"},
    {"name": "merge", "status": "ok"},
    {"name": "release", "status": "ok", "url": "..."}
  ]
}
```

**`--skip-pr` mode:** Skip steps 5-9 (branch, commit, push, PR, CI, merge, sync). Only bump version, update changelog, build, and create release. Useful when the PR is already merged and you just need the GitHub release.

### 6. `src/cli/commands/mod.rs` — Register module

Add `pub mod release;`

### 7. `src/main.rs` — Register command

Add `Release` variant to `Commands` enum:
```rust
Release {
    /// Version to release (e.g. v0.12.4)
    version: String,
    /// Release notes
    #[arg(short, long)]
    notes: Option<String>,
    /// Show what would happen without doing it
    #[arg(long)]
    dry_run: bool,
    /// Skip PR workflow (bump, tag, release only)
    #[arg(long)]
    skip_pr: bool,
    /// Target repo for GitHub release (default: auto-detect)
    #[arg(long)]
    repo: Option<String>,
    /// Timeout in seconds for CI wait (default: 600)
    #[arg(long, default_value = "600")]
    timeout: u64,
},
```

Add dispatch in `main()`:
```rust
Some(Commands::Release { version, notes, dry_run, skip_pr, repo, timeout }) => {
    let (workspace_root, manifest) = load_gripspace()?;
    gitgrip::cli::commands::release::run_release(
        gitgrip::cli::commands::release::ReleaseOptions {
            workspace_root: &workspace_root,
            manifest: &manifest,
            version: &version,
            notes: notes.as_deref(),
            dry_run,
            skip_pr,
            target_repo: repo.as_deref(),
            json: cli.json,
            quiet: cli.quiet,
            timeout,
        },
    ).await?;
}
```

### 8. `tests/test_release.rs` — Integration tests

- `test_release_dry_run` — verify dry-run shows steps without executing
- `test_release_bumps_cargo_toml` — verify Cargo.toml version replacement
- `test_release_bumps_package_json` — verify package.json version replacement
- `test_release_updates_changelog` — verify CHANGELOG.md gets new section
- `test_release_invalid_version` — verify error on malformed version
- `test_release_version_file_config` — verify manifest-configured version files
- `test_release_post_release_hooks` — verify hooks execute with version substitution

Note: Full PR/merge/release integration requires real git remotes and platforms. Tests focus on the local file manipulation (version bump, changelog) and dry-run output.

## Files to create/modify

| File | Action | Change |
|------|--------|--------|
| `src/core/manifest.rs` | MODIFY | Add `ReleaseConfig`, `VersionFileConfig`, add to `WorkspaceConfig` |
| `src/platform/types.rs` | MODIFY | Add `ReleaseResult` |
| `src/platform/traits.rs` | MODIFY | Add `create_release()` with default impl |
| `src/platform/github.rs` | MODIFY | Implement `create_release()` via Octocrab |
| `src/cli/commands/release.rs` | CREATE | `run_release()` with step pipeline |
| `src/cli/commands/mod.rs` | MODIFY | Add `pub mod release;` |
| `src/main.rs` | MODIFY | Add `Release` variant + dispatch |
| `tests/test_release.rs` | CREATE | Integration tests |

## Existing utilities to reuse

| Utility | File | Purpose |
|---------|------|---------|
| `run_branch()` | `src/cli/commands/branch.rs` | Create release branch |
| `run_commit()` | `src/cli/commands/commit.rs` | Commit version changes |
| `run_push()` | `src/cli/commands/push.rs` | Push release branch |
| `run_pr_create()` | `src/cli/commands/pr/create.rs` | Create release PR |
| `run_pr_merge()` | `src/cli/commands/pr/merge.rs` | Merge with CI wait |
| `run_sync()` | `src/cli/commands/sync.rs` | Post-merge sync |
| `run_checkout()` | `src/cli/commands/checkout.rs` | Checkout base after merge |
| `get_platform_adapter()` | `src/platform/mod.rs` | Get platform for release |
| `HookCommand` | `src/core/manifest.rs` | Reuse for post-release hooks |
| `filter_repos()` | `src/core/repo.rs` | Get repos list |
| `Output::*` | `src/cli/output.rs` | Step progress display |
| `BranchOptions` | `src/cli/commands/branch.rs` | Branch creation options |

## Verification

1. `cargo build` succeeds
2. `cargo test` — all existing tests pass + new release tests
3. `cargo clippy` clean
4. `cargo fmt` clean
5. `gr release v0.0.0-test --dry-run` — shows all steps without executing
6. `gr release v0.0.0-test --dry-run --json` — valid JSON output
7. Manual verification: version bump correctly updates Cargo.toml version field
8. Manual verification: CHANGELOG.md gets properly formatted new section
