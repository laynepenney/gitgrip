# Issue #286: Post-sync hooks in manifest

## Context

After `gr sync` pulls new code, agents often need to rebuild. Currently there's no way to automate post-sync actions. The manifest already defines `WorkspaceHooks` with `post_sync` and `post_checkout` fields (`src/core/manifest.rs:263-282`), and gripspace resolution already merges hooks from composed gripspaces (`src/core/gripspace.rs:406-420`). However, **no execution code exists** — the hooks are parsed but never run.

Issue #286 extends the hook schema with `name`, `repos`, and `condition` fields, and implements actual execution after sync completes.

## Approach

Extend `HookCommand` with optional fields for richer control, add a `had_changes` field to `SyncResult` for change detection, then wire hook execution into the sync pipeline after links are applied. Hooks that fail produce warnings — they never fail the overall sync.

**Key design decisions:**
- Extend existing `HookCommand` (backward compatible — new fields are optional with defaults)
- Track changes via pre/post HEAD SHA comparison in `sync_single_repo`
- `condition: changed` means "any of the listed repos received new commits"
- `condition: always` (the default) means "always run"
- Hook failures are warnings, not errors
- `--no-hooks` flag on `gr sync` to skip execution

## Changes

### 1. `src/core/manifest.rs` — Extend HookCommand

Add `HookCondition` enum and extend `HookCommand`:

```rust
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum HookCondition {
    #[default]
    Always,
    Changed,
}

pub struct HookCommand {
    pub command: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub cwd: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub name: Option<String>,            // NEW
    #[serde(skip_serializing_if = "Option::is_none")]
    pub repos: Option<Vec<String>>,      // NEW
    #[serde(default, skip_serializing_if = "is_default_condition")]
    pub condition: HookCondition,        // NEW (defaults to Always)
}
```

### 2. `src/cli/commands/sync.rs` — Track changes + execute hooks

**SyncResult** — add `had_changes: bool`:
- Set `true` for clones (`was_cloned = true`)
- Set `true` when `safe_pull_latest` returns `pulled = true`
- Set `false` for "up to date" or errors

**Change detection** — In `sync_single_repo`, use `SafePullResult.pulled` which already indicates if new commits were fetched. For griptree upstream sync and reference reset paths, compare HEAD before/after.

**Hook execution** — New function `execute_post_sync_hooks()`:
1. Get hooks from `manifest.workspace.hooks.post_sync`
2. For each hook:
   - If `condition == Changed` and `repos` specified: check if any listed repo had changes
   - If `condition == Changed` and no `repos`: check if ANY repo had changes
   - If `condition == Always`: always run
3. Execute via `sh -c` (following pattern from `src/cli/commands/run.rs:95-107`)
4. `cwd` defaults to workspace root unless overridden
5. Capture success/failure, timing
6. Display results (success/warning)

**HookResult struct** for JSON output:
```rust
struct HookResult {
    name: String,
    success: bool,
    skipped: bool,
    duration_ms: u64,
    error: Option<String>,
}
```

**JSON output** — Add `hooks: Vec<HookResult>` to `JsonSyncResult`.

### 3. `src/main.rs` — Add `--no-hooks` flag

Add to `Sync` command:
```rust
/// Skip post-sync hooks
#[arg(long)]
no_hooks: bool,
```

Pass to `run_sync()` as new parameter.

### 4. `src/cli/commands/tree.rs` — Update run_sync call

Line 517: Add `false` for `no_hooks` parameter (hooks should run on tree return sync).

### 5. `tests/test_sync.rs` — Update 15 existing calls + add hook tests

All 15 existing `run_sync()` calls need `false` added for the new `no_hooks` parameter.

New integration tests:
- `test_sync_runs_post_sync_hooks_always` — hook with default condition runs
- `test_sync_hook_failure_is_warning` — failed hook doesn't fail sync
- `test_sync_no_hooks_flag_skips` — `no_hooks: true` skips all hooks

### 6. `tests/test_errors.rs` — Update 1 run_sync call

Line 228: Add `false` for `no_hooks`.

## Files to modify

| File | Change |
|------|--------|
| `src/core/manifest.rs` | Add `HookCondition` enum, extend `HookCommand` with `name`, `repos`, `condition` |
| `src/cli/commands/sync.rs` | Add `had_changes` to `SyncResult`, add hook execution after links, add `no_hooks` param, add JSON hook output |
| `src/main.rs` | Add `--no-hooks` flag to Sync command, pass to `run_sync` |
| `src/cli/commands/tree.rs` | Update `run_sync` call with `no_hooks: false` |
| `tests/test_sync.rs` | Update 15 `run_sync` calls, add 3 hook integration tests |
| `tests/test_errors.rs` | Update 1 `run_sync` call |

## Existing utilities to reuse

| Utility | File | Purpose |
|---------|------|---------|
| `HookCommand` / `WorkspaceHooks` | `src/core/manifest.rs:263-282` | Existing hook types |
| `run_command()` pattern | `src/cli/commands/run.rs:95-107` | Shell command execution via `sh -c` |
| `SafePullResult.pulled` | `src/git/remote.rs:591-598` | Change detection |
| `Output::success/warning` | `src/cli/output.rs` | Display formatting |
| Gripspace hook resolution | `src/core/gripspace.rs:406-420` | Already handles merging |

## Verification

1. `cargo build` succeeds
2. `cargo test` — all existing tests pass + new hook tests
3. `cargo clippy` clean
4. `cargo fmt` clean
5. Add post-sync hooks to test workspace manifest, run `gr sync`, verify hooks execute
6. Run `gr sync --no-hooks`, verify hooks are skipped
7. Add a hook with `condition: changed`, sync with no changes, verify hook is skipped
