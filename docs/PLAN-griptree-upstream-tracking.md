# Plan: Griptree Base Branch + Upstream Tracking

## Context
In griptree workspaces, the local “base” branch is the griptree branch (e.g. `codi-gripspace`), not `main`. Each repo may track a different upstream default (e.g. `origin/main` vs `origin/dev`). Today, `gr` hardcodes `main` in several workflows, which causes confusion, failed rebases, and accidental branch switches.

## Goals
- Persist the griptree base branch per worktree.
- Persist per-repo upstream defaults (fallback to manifest default branch).
- Make `gr sync` and `gr rebase --upstream` use the stored upstream per repo.
- Add a way to return to the griptree base branch (`gr checkout --base`).

## Non-goals (Phase 1)
- Full repo-scoped operations (`--repo`) across all commands.
- Auto-migrating historical worktrees without user confirmation.
- Changing git’s own upstream configuration.

## Data Model
Add a small JSON file in the worktree root:

`.gitgrip/griptree.json`
```json
{
  "griptree_branch": "codi-gripspace",
  "repos": {
    "gitgrip": { "upstream": "origin/main" },
    "opencode": { "upstream": "origin/dev" }
  }
}
```

Notes:
- `griptree_branch` is the base branch for the worktree.
- `repos[repo].upstream` is the upstream default to use for sync/rebase.
- Missing entries fall back to manifest defaults (e.g. `origin/<default_branch>`).

## Command Changes
1) `gr tree add <branch>`
   - Create `.gitgrip/griptree.json` with `griptree_branch=<branch>`.
   - For each repo, detect upstream via `git rev-parse --abbrev-ref @{upstream}`.
   - If detection fails, set upstream to `origin/<manifest.default_branch>`.

2) `gr sync`
   - If `griptree.json` exists, use `repos[repo].upstream` instead of `origin/main` for comparisons and pulls.

3) `gr rebase --upstream`
   - If `griptree.json` exists, rebase each repo onto `repos[repo].upstream`.

4) `gr checkout --base` (new)
   - Checkout `griptree_branch` for all repos.
   - If metadata missing, error with guidance to run `gr tree add` or `gr tree init`.

## Migration / Init
- New command: `gr tree init` (or reuse `gr tree add` if it already runs in current worktree).
- It writes `.gitgrip/griptree.json` for an existing worktree based on current branch + upstreams.

## Error Handling
- If a repo lacks a configured upstream, fall back to `origin/<manifest.default_branch>`.
- If no `origin` exists, warn and skip rebase/pull for that repo.
- If `griptree.json` is malformed, return a clear error and suggest deletion/regeneration.

## Tests
- Unit tests for metadata read/write and upstream fallback resolution.
- Integration tests:
  - `gr rebase --upstream` uses per-repo upstream (main vs dev).
  - `gr sync` uses per-repo upstream.
  - `gr checkout --base` returns to griptree branch.

## Rollout
- Phase 1: metadata + `sync`/`rebase`/`checkout --base` changes.
- Phase 2: UI improvements in `gr status` to show griptree base + upstream mapping.
- Phase 3: per-repo targeting for checkout/sync/rebase with `--repo`.
