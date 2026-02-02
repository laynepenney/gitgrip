# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.5.6] - 2026-02-01

### Added
- Griptree manifest worktree support - each griptree can have its own manifest worktree
- Branch tracking for griptrees - tracks original branch per repo for proper merge-back
- Reference repo sync - reference repos auto-sync with upstream before worktree creation
- `gr add` and `gr commit` now handle manifest worktree changes automatically
- `gr status` displays manifest worktree status as separate entry
- Griptree worktrees now prioritize repo's current branch instead of griptree branch
- Comprehensive test coverage for manifest worktree functionality (10 new tests)

### Changed
- Manifest loading prioritizes griptree's own manifest, falls back to main workspace

### Fixed
- `gr push` now shows which repos failed and why

### Implemented
- Full Bitbucket API integration with PR create/merge/status support

### Improved
- CI status visibility in PR checks output
- PR merge recognizes passing GitHub Actions check runs correctly
- Sync error messages show which repos failed during `gr sync`
- `gr pr create` supports `--dry-run` for preview without creating PRs

## [0.5.5] - 2026-02-01

### Added
- Telemetry, tracing, and benchmarks infrastructure for performance monitoring
  - Optional telemetry feature flag
  - Correlation IDs for request tracing
  - Git operation metrics (fetch, pull, push timing)
  - Platform API metrics
- CI now triggers for markdown file changes (enables doc-only PRs)

### Fixed
- `gr sync` now succeeds when on a branch without upstream configured
  - Fetches from origin to update refs instead of failing
  - Reports "fetched (no upstream)" status
- Windows CI: Fixed libgit2-sys linking by adding advapi32.lib via build.rs and RUSTFLAGS
- `gr repo add` YAML insertion now correctly places repos under `repos:` section
- Griptree creation now writes `.griptree` pointer file for workspace detection

### Changed
- CI summary job added for branch protection compatibility

## [0.5.4] - 2026-02-01

### Added
- Reference repos feature - mark repos as read-only with `reference: true` in manifest
  - Reference repos are excluded from `gr branch`, `gr checkout`, `gr push`, and PR operations
  - Reference repos still sync with `gr sync` and appear in `gr status` with `[ref]` indicator
  - Useful for upstream dependencies, reference implementations, or docs you only read
- `gr status` now shows `[ref]` suffix for reference repos

## [0.5.3] - 2026-01-31

### Added
- `gr status` now shows "vs main" column with commits ahead/behind default branch
  - `↑N` for commits ahead of main
  - `↓N` for commits behind main
  - `-` when on the default branch
  - `✓` when feature branch is in sync with main
- Summary line shows count of repos ahead of main

## [0.5.2] - 2026-01-31

### Fixed
- Git operations now work correctly in griptree worktrees
  - Changed all git CLI calls to use `repo.workdir()` instead of `repo.path().parent()`
  - Fixes "fatal: this operation must be run in a work tree" errors for `gr sync`, `gr add`, `gr commit`, etc.
- Release workflow now uses `--allow-dirty` for crates.io publish to handle Cargo.lock changes

### Added
- Shell completions via `gr completions <shell>` (bash, zsh, fish, elvish, powershell)
- GitLab E2E PR workflow tests with Bearer token authentication
- `get_workdir()` helper function for worktree-compatible path resolution

## [0.5.1] - 2026-01-31

### Fixed
- `gr` commands now work from griptree directories by detecting `.griptree` marker file
  - Reads `mainWorkspace` field from `.griptree` and delegates to parent workspace
  - Fixes "fatal: this operation must be run in a work tree" errors when running from griptrees

## [0.5.0] - 2026-01-31

### Added
- `gr init --from-dirs` command to create workspace from existing local directories
  - Auto-scans current directory for git repositories
  - `--dirs` flag to scan specific directories only
  - `--interactive` flag for YAML preview and editing before save
  - Discovers remote URLs and default branches automatically
  - Handles duplicate names with auto-suffixing
  - Initializes manifest directory as git repo with initial commit

## [0.4.2] - 2026-01-29

### Fixed
- Griptree worktrees now use manifest paths (e.g., `./codi`) instead of repo names
- `gr` commands now work correctly from within griptree directories

## [0.4.1] - 2026-01-29

### Changed
- Renamed command from `gr griptree` to `gr tree` to avoid "gitgrip griptree" duplication
- Standalone references use "griptree" branding (e.g., "Create a griptree")
- Commands use `gr tree` (e.g., `gr tree add`, `gr tree list`)
- Config file remains `.griptree`

## [0.4.0] - 2026-01-29

### Added
- `gr tree` commands for worktree-based multi-branch workspaces (griptrees)
  - `gr tree add <branch>` - create parallel workspace on a branch
  - `gr tree list` - show all griptrees
  - `gr tree remove <branch>` - remove a griptree
  - `gr tree lock/unlock <branch>` - protect griptrees from removal
- `GitStatusCache` class for caching git status calls within command execution
- CI workflow with build/test/benchmarks on Node 18, 20, 22
- Griptree documentation graphics (`assets/griptree-concept.svg`, `assets/griptree-workflow.svg`)

### Changed
- **Performance:** Parallelized `push`, `sync`, and `commit` commands using `Promise.all()`
  - 3.4x speedup on `status` operation
  - 1.8x speedup on `branch-check` operation

## [0.3.1] - 2026-01-29

### Added
- `gr repo add <url>` command - add new repositories to workspace
  - Parses GitHub, GitLab, Azure DevOps URLs automatically
  - Updates manifest.yaml preserving comments
  - Clones repo and syncs to current workspace branch
  - Options: `--path`, `--name`, `--branch`, `--no-clone`

### Fixed
- `gr sync` no longer discards local commits on unpushed feature branches
  - Now checks if branch was ever pushed before auto-switching
  - Warns if local-only commits would be lost

## [0.2.4] - 2026-01-28

### Removed
- Removed backward compatibility for `.codi-repo/` directories
- Removed `gr migrate` command (no longer needed)

### Fixed
- Fixed PR linking - manifest PRs now include linked PR table with cross-references

## [0.2.3] - 2026-01-28

### Fixed
- Fixed PR linking - manifest PRs now include linked PR table with cross-references

## [0.2.2] - 2026-01-28

### Changed
- Updated branding with new emerald/green color scheme
- New icon design showing grip concept with central hub and three branches
- Updated README with centered banner and npm badges

## [0.2.1] - 2026-01-28

### Changed
- Renamed from `codi-repo` to `gitgrip`
- CLI command changed from `cr` to `gr`
- Directory changed from `.codi-repo/` to `.gitgrip/`
- Skill renamed from `codi-repo` to `gitgrip`
- All documentation updated to use new naming

### Added
- Backward compatibility for legacy `.codi-repo/` directories

## [0.2.0] - 2026-01-28

### Changed
- Initial release as `gitgrip` (renamed from codi-repo)

## [0.1.2] - 2026-01-27

### Added
- `gr forall` command - run commands in each repository (like AOSP repo forall)
- `gr add` command - stage changes across all repositories
- `gr diff` command - show diff across all repositories
- `gr commit` command - commit staged changes across all repositories
- `gr push` command - push current branch across all repositories
- `gr branch --repo` flag - create branches in specific repos only
- `--timing` flag for performance debugging
- `gr bench` command for benchmarking

### Fixed
- `gr pr create` now only checks branch consistency for repos with changes
- `gr pr status/merge` find PRs by checking each repo's own branch
- `gr sync` automatically recovers when manifest's upstream branch was deleted

## [0.1.1] - 2026-01-27

### Added
- Manifest repo (`.gitgrip/manifests/`) automatically included in commands
- `gr status` shows manifest in separate section
- `gr branch --include-manifest` flag

### Fixed
- Various stability improvements

## [0.1.0] - 2026-01-27

### Added
- Initial release
- `gr init` - initialize workspace from manifest
- `gr sync` - pull latest from all repos
- `gr status` - show status of all repos
- `gr branch` - create/list branches across repos
- `gr checkout` - checkout branch across repos
- `gr pr create` - create linked PRs
- `gr pr status` - show PR status
- `gr pr merge` - merge all linked PRs
- `gr link` - manage copyfile/linkfile entries
- `gr run` - execute workspace scripts
- `gr env` - show workspace environment variables
- Manifest-based configuration (AOSP-style)
- Linked PR workflow with all-or-nothing merge strategy
