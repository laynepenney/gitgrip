# Implementation Plan: Architectural Assessment Action Items

*February 2026 — 4 PRs covering 16 action items from `docs/ARCHITECTURAL_ASSESSMENT.md`*

## PR 1: P0 — Safety Fixes (`fix/p0-safety`)

### 1.1 Thread panic handling
Replace `handle.join().unwrap()` with proper error handling:
- `src/cli/commands/grep.rs:150`
- `src/cli/commands/forall.rs:1011`

```rust
// Before:
handle.join().unwrap();
// After:
handle.join().map_err(|_| anyhow::anyhow!("Worker thread panicked"))?;
```

### 1.2 Mutex poison risk
Replace all `.lock().unwrap()` with `.expect("mutex poisoned")` in production code (16 sites):
- `src/cli/commands/forall.rs:1002, 1015`
- `src/cli/commands/grep.rs:141, 153`
- `src/git/cache.rs:46, 67, 79, 85`
- `src/telemetry/metrics.rs:32, 46, 53, 66-68, 79-81`
- `src/cli/commands/sync.rs:411-412`
- `src/cli/commands/pull.rs:125, 137-138`

### 1.3 Bitbucket mock race condition
Add `Once` guard to `setup_bitbucket_mock()` in `tests/common/mock_platform.rs:623-631`.

---

## PR 2: P1 — Quality Fixes (`fix/p1-quality`)

### 2.1 Fix broken branch JSON output
Add JSON output for create, delete, and move-commits operations in `src/cli/commands/branch.rs`.

### 2.2 Add git lock detection
Add `wait_for_git_lock(repo_path)` to `src/git/mod.rs` with retry logic and `GitError::RepositoryLocked` variant.

### 2.3 Fix GHE auto-merge
Pass `--hostname` to `gh` CLI in `src/platform/github.rs` `enable_auto_merge()` when on GHE.

### 2.4 Add tests for untested modules
- `src/git/cherry_pick.rs` — inline tests
- `src/git/gc.rs` — inline tests
- `src/core/griptree.rs` — extend existing tests

---

## PR 3: P2 — Maintainability Refactor (`refactor/p2-maintainability`)

### Phase 1: Foundation
- New `src/cli/context.rs`: `WorkspaceContext` struct (workspace_root, manifest, quiet, verbose, json)
- Extend `src/cli/output.rs`: Add `blank_line()`, `summary()`, `raw()`, `json()` methods

### Phase 2: load_gripspace decomposition
Split `load_gripspace()` in `src/main.rs` into `load_from_griptree()`, `load_from_gitgrip_dir()`, `load_from_repo_xml()`.

### Phase 3: Repo iteration helper
New `src/cli/repo_iter.rs`: `RepoSelection`, `RepoVisitResult`, `for_each_repo()`, `for_each_repo_path()`.

### Phase 4-6: Migrate all commands to WorkspaceContext + repo iteration helper
- Batch 1: add, diff, gc, prune, env
- Batch 2: status, commit, push, checkout, grep, forall, rebase, cherry_pick, link, run
- Batch 3: branch, verify, sync, pull, pr/*, release, tree, init, ci, repo, group, manifest, agent/*

### Phase 7: Dispatch refactor
Restructure main.rs: single `load_gripspace()` call, `WorkspaceContext` creation, compact `dispatch_workspace_command()` match block.

### Phase 8: Break up large functions
- sync.rs: Extract post-sync steps
- release.rs: Extract phase functions

---

## PR 4: P3 — Extensibility (`refactor/p3-extensibility`)

### 4.1 GitBackend trait
Abstract git operations behind `GitBackend` trait in `src/git/backend.rs`.

### 4.2 OutputSink trait
Extract trait from `Output` struct for testability and quiet mode support.

### 4.3 Platform capability matrix
Document in `docs/PLATFORM_CAPABILITIES.md`.

### 4.4 Trim tokio features
Replace `features = ["full"]` with specific features in `Cargo.toml`.

### 4.5 Multi-repo rollback semantics
Record pre-sync HEADs, add `gr sync --rollback` flag.

---

## Execution Order

1. PR 1 (P0) — Safety fixes
2. PR 2 (P1) — Quality fixes
3. PR 3 (P2) — Maintainability refactor (depends on P0/P1)
4. PR 4 (P3) — Extensibility (depends on P2)
