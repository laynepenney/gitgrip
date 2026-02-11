# Issue #284: `gr verify` — boolean pass/fail assertions

## Context

Agents need boolean yes/no answers, not text to interpret. Currently checking "are all repos clean?" requires parsing `gr status` output. A new `gr verify` command provides exit-code-based assertions: exit 0 = pass, exit 1 = fail. With `--json`, returns `{"pass": bool, "details": [...]}`.

## Approach

New `gr verify` command with multiple assertion flags. Each flag checks one condition. Multiple flags can be combined (all must pass). This follows existing gitgrip patterns for command registration, repo filtering, and JSON output.

**Key design decisions:**
- Exit codes: `std::process::exit(1)` on failure (new pattern for gitgrip, but essential for agent use)
- JSON mode: always exits 0, puts pass/fail in the JSON body (consistent with how agents consume JSON)
- Multiple flags: all checks run, all must pass

## Changes

### 1. `src/cli/commands/verify.rs` — New command implementation

Create new file with `run_verify()` function. Uses existing utilities:
- `crate::git::status::get_repo_status()` for `--clean` (from `src/git/status.rs`)
- `crate::cli::commands::link::show_link_status()` pattern for `--links` (from `src/cli/commands/link.rs`)
- `crate::git::branch::get_current_branch()` for `--on-branch` (from `src/git/branch.rs`)
- `crate::core::repo::filter_repos()` for repo filtering (from `src/core/repo.rs`)
- Platform adapters for `--checks` and `--pr-merged` (from `src/platform/`)

**Flags:**
```
--clean              # No uncommitted changes in any repo
--links              # All copyfile/linkfile entries are valid
--on-branch <name>   # All non-reference repos on this branch
--synced             # All repos up-to-date with remote
--checks <number>    # All CI checks pass for PR
--pr-merged <number> # PR is merged
```

**JSON output shape:**
```json
{
  "pass": false,
  "checks": [
    {"name": "clean", "pass": true, "details": []},
    {"name": "on-branch", "pass": false, "details": [
      {"repo": "frontend", "expected": "feat/x", "actual": "main"}
    ]}
  ]
}
```

### 2. `src/cli/commands/mod.rs` — Register module

Add `pub mod verify;`

### 3. `src/main.rs` — Add Verify command variant

Add `Verify` variant to `Commands` enum with clap args. Add dispatch in the match arm. The verify command needs async (for `--checks` and `--pr-merged` which call platform APIs).

### 4. Unit tests in `src/cli/commands/verify.rs`

Test the individual check functions:
- `test_check_clean_with_clean_repos`
- `test_check_clean_with_dirty_repos`
- `test_check_on_branch_matching`
- `test_check_on_branch_mismatch`

### 5. Integration tests in `tests/test_verify.rs`

Using `WorkspaceBuilder`:
- `test_verify_clean_passes_on_clean_workspace`
- `test_verify_clean_fails_with_changes`
- `test_verify_on_branch_passes`
- `test_verify_on_branch_fails`
- `test_verify_no_flags_shows_help`

## Files to modify

| File | Change |
|------|--------|
| `src/cli/commands/verify.rs` | **NEW** — Main verify command implementation |
| `src/cli/commands/mod.rs` | Add `pub mod verify;` |
| `src/main.rs` | Add `Verify` variant to `Commands` enum + dispatch |
| `tests/test_verify.rs` | **NEW** — Integration tests |

## Existing utilities to reuse

| Utility | File | Purpose |
|---------|------|---------|
| `get_repo_status()` | `src/git/status.rs:204` | Clean/dirty detection |
| `filter_repos()` | `src/core/repo.rs:185` | Repo filtering by group |
| `get_current_branch()` | `src/git/branch.rs` | Current branch name |
| `show_link_status()` pattern | `src/cli/commands/link.rs:33` | Link validity checking |
| `Output::header/success/error` | `src/cli/output.rs` | Consistent output formatting |
| Platform adapters | `src/platform/` | PR/checks queries |

## Verification

1. `cargo build` succeeds
2. `cargo test` passes (all existing + new verify tests)
3. `cargo clippy` clean
4. Manual: `gr verify --clean` on clean workspace → exit 0
5. Manual: modify a file, `gr verify --clean` → exit 1
6. Manual: `gr verify --on-branch main` → exit 0
7. Manual: `gr verify --clean --json` → JSON with `pass: true`
