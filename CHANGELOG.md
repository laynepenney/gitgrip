# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.8.0] - 2026-02-04

### Added
- `gr prune` command - delete local branches merged into the default branch
  - Dry-run by default, `--execute` to actually delete
  - `--remote` flag to also prune remote tracking refs (`git fetch --prune`)
  - Reports summary of pruned branches across repos
- `gr grep` command - cross-repo search using `git grep`
  - Prefixes results with repo name for easy identification
  - `-i` flag for case-insensitive search
  - `--parallel` flag for concurrent search across repos
  - Supports pathspec filtering (`gr grep "pattern" -- "*.rs"`)
- Test harness with 40+ integration tests (Phases 0-3)
  - `WorkspaceBuilder` fixture for creating temporary workspaces with bare remotes
  - git_helpers module for test git operations
  - wiremock-based platform mocks for GitHub/GitLab/Azure
  - Tests for branch, checkout, sync, add, commit, push, status, forall, griptree, PR, and error scenarios

### Fixed
- `gr pr create` now includes repos without remote tracking branches
  - Previously `has_commits_ahead()` returned false when base ref was missing, silently skipping repos
  - Now assumes the branch has changes when neither remote nor local base ref exists
- Griptree worktree name parsing bug fix for names with path separators

### Improved
- Error messages across 5 key files with actionable recovery suggestions:
  - Push errors: interpreted messages for non-fast-forward, auth failure, network issues
  - PR create: clearer branch reference errors with guidance
  - Init: recovery suggestions for existing directory and missing manifest
  - Run: suggests `gr run --list` for missing scripts
  - Push: suggests `gr sync` for missing remote targets

## [0.7.1] - 2026-02-03

### Fixed
- `gr pr merge --force` now properly bypasses `all-or-nothing` merge strategy (#180)
  - Previously would stop on first failed merge even with `--force` flag
  - Now continues merging remaining PRs when one fails with `--force`
  - Shows warning for failed merges instead of hard stop
- `gr pr create` now detects uncommitted changes in manifest repo (#178)
  - Previously only checked for commits ahead of default branch
  - Now detects staged and unstaged changes as well
  - Properly handles manifest-only PR creation

### Documentation
- Updated skill documentation with complete manifest schema
- Added workflow patterns section (accidental main branch commits, single-repo operations)
- Documented `reference` repos and `platform` configuration options
- Added IMPROVEMENTS.md entries for discovered friction points

## [0.7.0] - 2026-02-02

### Changed (Breaking)
- `gr forall` now defaults to running commands only in repos with changes
  - Use `--all` flag for previous behavior (run in all repos)

### Added
- `gr branch --move` flag to move commits from current branch to a new branch
  - Creates new branch at HEAD, resets current branch to remote, checkouts new branch
- `gr branch --repo <names>` flag to operate on specific repos only

### Fixed
- Platform API timeouts now have explicit configuration (10s connect, 30s read/write)
  - Faster failure detection and clearer error messages
- Worktree branch conflicts now show helpful error messages with guidance
  - Explains the git limitation and suggests alternatives

## [0.6.0] - 2026-02-02

### Fixed
- Griptree branches now base off repo's default branch instead of HEAD
- Griptree worktrees now use griptree branch name, not current workspace branch
- Reference repo sync failures no longer block griptree creation (warning only)
- Automatic link application after griptree creation
- Manifest repo links (copyfile/linkfile) now properly processed
- Worktree cleanup on griptree removal using git2 prune
- Rollback on partial griptree creation failure
- Clone fallback when specified branch doesn't exist on remote

### Added
- Legacy griptree discovery in `gr tree list`
- Worktree tracking metadata (worktree_name, worktree_path, main_repo_path)
- state.json initialization in new griptrees

## [0.5.8] - 2026-02-02

### Added
- `gr pr create` now supports `-b/--body` flag for non-interactive PR description
- Griptree manifest worktree support - each griptree can have its own manifest worktree
- Branch tracking for griptrees - tracks original branch per repo for proper merge-back
- Reference repo sync - reference repos auto-sync with upstream before worktree creation
- `gr add` and `gr commit` now handle manifest worktree changes automatically
- `gr status` displays manifest worktree status as separate entry
- Griptree worktrees now prioritize repo's current branch instead of griptree branch
- Comprehensive test coverage for manifest worktree functionality (10 new tests)
- Documentation in IMPROVEMENTS.md for tracking completed and pending features
- Worktree conflict troubleshooting guide added to CONTRIBUTING.md
- Documentation for IMPROVEMENTS.md merge conflict behavior
- PLAN document for griptree repo branch implementation

### Changed
- Manifest loading prioritizes griptree's own manifest, falls back to main workspace
- IMPROVEMENTS.md reorganized to show completed vs pending features clearly

## [0.5.7] - 2026-02-01

## [0.5.6] - 2026-02-01

### Added
- Full Bitbucket API integration with PR create/merge/status/comment support
- `gr pr create` supports `--dry-run` for preview without creating actual PRs
- `gr pr create` supports `--push` flag to push branches before creating PRs
- Shell completions for bash, zsh, fish, elvish, powershell via `gr completions <shell>`

### Changed
- `gr sync` now succeeds when on a branch without upstream configured
- `gr push` now shows which repos failed and why
- Better CI status visibility in PR checks output
- Improved sync error messages showing which repos failed

### Fixed
- PR merge now recognizes passing GitHub Actions check runs correctly
- `gr repo add` YAML insertion correctly places repos under `repos:` section
- Griptree creation now writes `.griptree` pointer file for workspace detection
- Windows CI: Fixed libgit2-sys linking by adding advapi32.lib

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
