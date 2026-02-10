# Fix #279: gr sync should apply linkfiles/copyfiles after syncing

## Context

After `gr sync`, linkfiles and copyfiles are broken because sync doesn't call `apply_links()`. Users must manually run `gr link --apply` after every sync. This is the #1 source of workspace drift.

## Changes

### 1. Make `apply_links` public and add `quiet` parameter

**File:** `src/cli/commands/link.rs:237`

Change:
```rust
fn apply_links(workspace_root: &PathBuf, manifest: &Manifest) -> anyhow::Result<()> {
```
To:
```rust
pub fn apply_links(workspace_root: &PathBuf, manifest: &Manifest, quiet: bool) -> anyhow::Result<()> {
```

When `quiet` is true:
- Skip the header (`Output::header("Applying File Links")`)
- Skip per-link `Output::success(...)` lines
- Still print warnings/errors (source missing, symlink failures)
- Still print the summary line at the end

Update the existing call site in `link.rs` (the CLI `--apply` handler around line 23) to pass `quiet: false`.

### 2. Call `apply_links` from sync after composefiles

**File:** `src/cli/commands/sync.rs`

**Import:** Add `use crate::cli::commands::link::apply_links;`

**Injection point:** After composefile processing (line 138), before `Ok(())` (line 140):

```rust
// Apply linkfiles and copyfiles after repos and composefiles
match apply_links(workspace_root, &manifest, quiet) {
    Ok(()) => {}
    Err(e) => {
        Output::warning(&format!("Link application failed: {}", e));
    }
}
```

Note: `manifest` in sync is the re-resolved manifest from `sync_gripspaces()` (line 43-54), so it includes gripspace-inherited links.

### 3. Update existing `apply_links` call in link.rs CLI handler

**File:** `src/cli/commands/link.rs` ~line 23

Change `apply_links(workspace_root, manifest)?;` → `apply_links(workspace_root, manifest, false)?;`

## Files to modify

| File | Change |
|------|--------|
| `src/cli/commands/link.rs:237` | Make `apply_links` pub, add `quiet: bool` param |
| `src/cli/commands/link.rs:~23` | Pass `quiet: false` to existing call |
| `src/cli/commands/sync.rs` | Import `apply_links`, call after composefiles |

## Verification

1. `cargo build` succeeds
2. `cargo test` passes
3. `cargo clippy` clean
4. Test in codi-workspace:
   - Break a link manually (`rm .claude/skills/codi-rs`)
   - Run `gr sync` — link should be restored automatically
   - Run `gr link` — all links should show ✓
   - Run `gr sync --quiet` — no per-link output, just summary
