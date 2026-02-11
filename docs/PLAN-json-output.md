# Issue #282: Add `--json` global flag for machine-readable output

## Context

AI agents parse human-readable colored terminal output to determine command outcomes. This is fragile and error-prone. Some commands already have per-command `--json` flags (status, branch, diff, pr status, pr checks, ci), but most commands lack structured output. Adding a global `--json` flag to the CLI makes every command's output parseable by agents — the single highest-impact agent improvement.

## Approach

1. Add `--json` as a **global flag** on the `Cli` struct
2. Remove all existing per-command `--json` flags (6 commands) to avoid conflicts
3. Pass `cli.json` through to each command handler
4. Add JSON output to the 8 priority commands from the issue
5. Leave non-priority commands unchanged (they'll just ignore the flag for now)

## Changes

### 1. `src/main.rs` — Add global flag, remove per-command flags

**Add to `Cli` struct** (after `verbose`):
```rust
/// Output in JSON format (machine-readable)
#[arg(long, global = true)]
json: bool,
```

**Remove `json: bool` field from these enum variants:**
- `Commands::Status` (line 79)
- `Commands::Branch` (line 102)
- `Commands::Diff` (line 128)
- `PrCommands::Status` (line 337)
- `PrCommands::Checks` (line 358)
- `CiCommands::Run` (line 459)
- `CiCommands::List` (line 465)
- `CiCommands::Status` (line 471)

**Update dispatch** to pass `cli.json` instead of per-command `json`:
- Status: pass `cli.json` instead of destructured `json`
- Branch: set `opts.json = cli.json` instead of `json`
- Diff: pass `cli.json`
- Sync: add `cli.json` parameter
- Push: add `cli.json` parameter
- Commit: add `cli.json` parameter
- Pr Create: add `cli.json` parameter
- Pr Status: pass `cli.json`
- Pr Merge: add `cli.json` parameter
- Pr Checks: pass `cli.json`
- Ci Run/List/Status: pass `cli.json`
- Link: add `cli.json` parameter

### 2. `src/cli/commands/sync.rs` — Add JSON output

**Signature:** Add `json: bool` parameter to `run_sync()`

**JSON struct:**
```rust
#[derive(serde::Serialize)]
struct JsonSyncResult {
    success: bool,
    repos: Vec<JsonSyncRepo>,
    links: JsonLinkResult,
    composefiles: usize,
}
#[derive(serde::Serialize)]
struct JsonSyncRepo {
    name: String,
    action: String,  // "pulled", "cloned", "skipped", "failed"
    error: Option<String>,
}
#[derive(serde::Serialize)]
struct JsonLinkResult {
    applied: usize,
    errors: usize,
}
```

**Pattern:** Collect results into Vec (already done via `SyncResult`). At the end, if `json`, serialize and print instead of the human-readable summary. Suppress all `Output::*` calls when `json` is true.

### 3. `src/cli/commands/push.rs` — Add JSON output

**Signature:** Add `json: bool` parameter to `run_push()`

**JSON struct:**
```rust
#[derive(serde::Serialize)]
struct JsonPushResult {
    success: bool,
    pushed: Vec<String>,
    skipped: Vec<String>,
    failed: Vec<JsonPushError>,
}
#[derive(serde::Serialize)]
struct JsonPushError {
    repo: String,
    reason: String,
}
```

**Pattern:** Collect pushed/skipped/failed vectors during the loop. At end, serialize if `json`.

### 4. `src/cli/commands/commit.rs` — Add JSON output

**Signature:** Add `json: bool` parameter to `run_commit()`

**JSON struct:**
```rust
#[derive(serde::Serialize)]
struct JsonCommitResult {
    success: bool,
    committed: Vec<JsonCommit>,
    skipped: Vec<String>,
}
#[derive(serde::Serialize)]
struct JsonCommit {
    repo: String,
    sha: String,
}
```

**Pattern:** Collect committed/skipped during loop. Serialize at end.

### 5. `src/cli/commands/pr/create.rs` — Add JSON output

**Signature:** Add `json: bool` parameter to `run_pr_create()`

**JSON struct:**
```rust
#[derive(serde::Serialize)]
struct JsonPrCreateResult {
    success: bool,
    prs: Vec<JsonCreatedPr>,
}
#[derive(serde::Serialize)]
struct JsonCreatedPr {
    repo: String,
    number: u64,
    url: String,
}
```

**Pattern:** The `created_prs: Vec<(String, u64, String)>` already collects this data. Convert at end.

### 6. `src/cli/commands/pr/merge.rs` — Add JSON output

**Signature:** Add `json: bool` parameter to `run_pr_merge()`

**JSON struct:**
```rust
#[derive(serde::Serialize)]
struct JsonPrMergeResult {
    success: bool,
    merged: Vec<JsonMergedPr>,
    failed: Vec<JsonFailedPr>,
    skipped: Vec<String>,
}
#[derive(serde::Serialize)]
struct JsonMergedPr {
    repo: String,
    pr_number: u64,
}
#[derive(serde::Serialize)]
struct JsonFailedPr {
    repo: String,
    pr_number: u64,
    reason: String,
}
```

**Pattern:** Collect merged/failed/skipped during the merge loop. Serialize at end.

### 7. `src/cli/commands/branch.rs` — Already has `json` in `BranchOptions`

Just pass `cli.json` through. No structural changes needed — JSON output already implemented.

### 8. `src/cli/commands/link.rs` — Add JSON output

**Signature:** Add `json: bool` parameter to `run_link()` and `show_link_status()`

**JSON struct:**
```rust
#[derive(serde::Serialize)]
struct JsonLinkStatus {
    links: Vec<JsonLink>,
    valid: usize,
    broken: usize,
}
#[derive(serde::Serialize)]
struct JsonLink {
    link_type: String,  // "copyfile" or "linkfile"
    src: String,
    dest: String,
    status: String,  // "valid" or "broken"
}
```

### 9. Existing JSON commands (status, diff, pr status, pr checks, ci)

These already have JSON implementations. Just change from per-command `json` to global `cli.json` in the dispatch. No changes to the command files themselves.

## Implementation pattern for each command

The pattern for adding JSON to a command is consistent:

1. Add `json: bool` param to function signature
2. Define `#[derive(serde::Serialize)]` struct(s) inside the function
3. If `json`, suppress `Output::header()` call at the top
4. Collect results into serializable structs alongside existing logic
5. At the end, if `json`, print `serde_json::to_string_pretty(&result)?` instead of the human-readable summary
6. Skip spinner output when `json` (spinners write to stderr by default via indicatif, so they're already separate from stdout — but for cleanliness, suppress them too)

## Files to modify

| File | Change |
|------|--------|
| `src/main.rs` | Add global `--json`, remove 8 per-command `--json` flags, update dispatch |
| `src/cli/commands/sync.rs` | Add `json` param, JSON output structs and serialization |
| `src/cli/commands/push.rs` | Add `json` param, JSON output structs and serialization |
| `src/cli/commands/commit.rs` | Add `json` param, JSON output structs and serialization |
| `src/cli/commands/pr/create.rs` | Add `json` param, JSON output structs and serialization |
| `src/cli/commands/pr/merge.rs` | Add `json` param, JSON output structs and serialization |
| `src/cli/commands/link.rs` | Add `json` param to `run_link()`, JSON output for status |
| `tests/test_pr_merge.rs` | Add `false` for new `json` param to all call sites |

## Key decisions

- **No envelope wrapper**: Each command returns its own shape directly (not wrapped in `{success, action, details}`). The `success` field on each struct serves the same purpose without redundant nesting.
- **Suppress Output/spinners in JSON mode**: Check `if !json` before `Output::header()`, spinner creation, and summary printing.
- **Errors still go to stderr**: `Output::error()` writes to stderr, so it won't corrupt JSON on stdout. But we still suppress it in JSON mode since errors are captured in the JSON structs.
- **serde_json already in Cargo.toml**: No new dependencies needed.

## Verification

1. `cargo build` succeeds
2. `cargo test` passes
3. `cargo clippy` clean
4. Manual testing:
   - `gr status --json` — still works (same behavior, just global flag now)
   - `gr --json status` — works (global flag position)
   - `gr push --json` — returns JSON
   - `gr link --json` — returns JSON with link status
   - `gr pr merge --json` — returns JSON (on feature branch with PR)
