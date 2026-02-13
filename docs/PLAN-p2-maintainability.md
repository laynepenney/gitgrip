# P2 Maintainability Refactor — Completion Plan

## Context

The `refactor/p2-maintainability` branch has uncommitted work from a Feb 12 session that was interrupted. It introduces `WorkspaceContext` and decomposes `load_gripspace()` in `main.rs`. Meanwhile, PRs #315 (P0 safety) and #316 (P1 quality) were just merged to main, so the branch needs rebasing before we can commit and ship.

The original plan (`docs/IMPLEMENTATION_PLAN.md`) had 8 phases. Analysis shows Phases 1-3 are largely done, Phase 4-6 dispatch conversion is 93% done, and Phases 7-8 provide marginal value. This plan ships what's built and scopes out the rest with rationale.

## Steps

### 0. Write plan to docs
Save this plan to `gitgrip/docs/PLAN-p2-maintainability.md` (consistent with other plan docs).

### 1. Rebase on main
Stash uncommitted work, rebase onto updated main (picks up P0/P1), pop stash.
```
git stash push -u -m "p2-maintainability WIP"
git fetch origin main && git rebase origin/main
git stash pop
```
No conflicts expected — P0/P1 didn't touch `main.rs` or `cli/mod.rs`.

### 2. Build & test
```
cargo build && cargo test && cargo clippy && cargo fmt --check
```
Watch for clippy warnings on unused `repo_iter` imports. If flagged, the `pub` visibility from `cli/mod.rs` → `lib.rs` should suppress it.

### 3. Commit the refactor
Stage all 4 files and commit:
- `src/cli/context.rs` (NEW) — `WorkspaceContext` struct
- `src/cli/repo_iter.rs` (NEW) — `for_each_repo()` / `for_each_repo_path()` helpers
- `src/cli/mod.rs` — module declarations + re-exports
- `src/main.rs` — `load_workspace_context()`, decomposed `load_gripspace()`, 28 commands using `ctx`

### 4. Update docs/IMPLEMENTATION_PLAN.md
Mark completed phases, note what was scoped out and why.

### 5. Push & create PR
```
gr push -u
gr pr create -t "refactor: P2 maintainability — WorkspaceContext and load_gripspace decomposition"
```

## What ships

| Item | Value |
|------|-------|
| `WorkspaceContext` struct (31 lines) | Eliminates repetitive flag passing at 28 dispatch sites |
| `load_gripspace` decomposition (~115 lines) | 4 focused functions instead of 1 monolithic 100-line function |
| `repo_iter` helpers (130 lines) | Infrastructure for future command simplification |
| `main.rs` dispatch modernization (~200 lines) | Consistent `ctx.workspace_root` / `ctx.manifest` / `ctx.quiet` / `ctx.json` |

## What's scoped out (and why)

| Item | Reason |
|------|--------|
| Output helpers (`blank_line`, `summary`, `raw`, `json`) | Commands already handle output directly; wrappers add indirection without value |
| Command signature migration to `&WorkspaceContext` | Would touch every command file + every test; current ctx field extraction in dispatch works fine |
| Compact dispatch function (Phase 7) | 612-line match for 30 commands is standard; only one dispatch site |
| sync.rs / release.rs decomposition (Phase 8) | Already have helpers (`sync_single_repo`, `execute_post_sync_hooks`, etc.) |
| Wiring `for_each_repo()` into commands | Most commands accumulate custom state that doesn't fit the simple Success/Skipped/Error enum |

## Files touched

- `src/main.rs` — core dispatch changes
- `src/cli/context.rs` — new file
- `src/cli/repo_iter.rs` — new file
- `src/cli/mod.rs` — 3 lines added
- `docs/IMPLEMENTATION_PLAN.md` — status update

## Verification

1. `cargo build` — compiles clean
2. `cargo test` — all tests pass (command signatures unchanged, tests unaffected)
3. `cargo clippy` — no new warnings
4. `cargo fmt --check` — formatted
5. Spot-check: `cargo run -- status` from workspace — ctx path works end-to-end
6. Spot-check: `cargo run -- completions bash > /dev/null` — non-ctx path works
