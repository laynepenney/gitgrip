# gitgrip Improvement Ideas

This file captures friction points, feature ideas, and bugs discovered while using `gr`.
Items here should be reviewed before creating GitHub issues.

> **Note**: Historical entries may reference `cr` (the old command name). The current command is `gr`.

> **Merge Conflicts**: When rebasing feature branches, you may encounter merge conflicts in this file when other PRs also add entries. This is expected behavior. To resolve:
>
> 1. Use `git rebase --skip` to skip documentation-only commits from other branches
> 2. Or manually merge both sets of entries
> 3. The alternative would be to use a dedicated documentation file, but we accept this tradeoff for now
>
> See issue #143 for context.

---

### Force-delete branch requires raw git

**Discovered**: 2026-02-05 while cleaning up merged tooling branches

**Problem**: `gr branch --delete` refuses to delete a branch after squash merge (not fully merged), and there is no force-delete option.

**Workaround used**: Ran raw `git` to force-delete the branch.

**Raw commands used**:
```bash
git -C /Users/layne/Development/codi-gripspace/gitgrip branch -D feat/gr-friction-logging
```

**Expected behavior**: `gr branch --delete --force <name>` (or similar) to delete unmerged branches.

---

### Manifest worktree blocks branch switching

**Discovered**: 2026-02-05 while trying to align manifest repo with main for PR creation

**Problem**: The manifest repo (`.gitgrip/manifests`) is a worktree, and `main` is already checked out in another worktree. There’s no `gr` command to target the manifest repo specifically, so I couldn’t switch it to `main` to avoid branch mismatch in `gr pr create`.

**Workaround used**: Attempted raw `git` checkout in the manifest repo (blocked by worktree lock).

**Raw commands used**:
```bash
git -C /Users/layne/Development/codi-gripspace/.gitgrip/manifests checkout main
```

**Expected behavior**: `gr checkout --include-manifest <branch>` or a repo filter for `gr checkout` to target the manifest repo.

---

### Need per-repo PR creation (or manifest exclusion)

**Discovered**: 2026-02-05 while creating a tooling-only PR

**Problem**: `gr pr create` fails when only one repo has changes but the manifest repo is on a different branch; there’s no way to exclude the manifest repo or target a single repo.

**Workaround used**: Use `gh pr create` directly in the repo that changed.

**Raw commands used**:
```bash
gh pr create --title "Log raw git branch delete" --body "Log raw git usage for forced branch deletion after squash merge."
```

**Expected behavior**: `gr pr create --repo <name>` or `--exclude-manifest` to create a PR for a single repo.

---

### gr sync should include manifest repo

**Discovered**: 2026-02-05 while syncing codi-gripspace

**Problem**: `gr sync` only syncs the configured repos and skips the manifest repo (`.gitgrip/manifests`). This leaves the manifest out of date, which can cause branch mismatch issues during PR creation.

**Expected behavior**: `gr sync` should include the manifest repo by default (or provide a `--include-manifest` flag).

---

### gr sync should use upstream branch in griptrees

**Discovered**: 2026-02-05 while syncing a griptree workspace

**Problem**: In griptrees (git worktrees), syncing against `main` alone can be incorrect if the workspace is tracking a different upstream (e.g., `origin/main` or whatever the primary griptree is on). This can cause `gr sync` to report clean status while the underlying upstream has advanced.

**Expected behavior**: When a griptree is created, record its upstream branch (e.g., `origin/main` or the primary griptree’s branch) and use that for sync and comparisons in worktrees.

---

## Completed

### Fix: PR Creation Timeout Issue ✓

**Completed**: 2026-02-02

**Problem**: `gr pr create` consistently times out (~30s) even when:
- `gh auth status` shows authenticated user with `repo` scope
- Git operations work (push, status, diff)
- Other `gr` commands work normally

**Root Cause**: HTTP clients (octocrab for GitHub, reqwest for GitLab/Azure/Bitbucket) had no explicit timeout configuration, relying on OS-level TCP timeouts (~30s) which made debugging difficult.

**Solution**: Added explicit timeout configurations to all platform adapters:
- Connect timeout: 10 seconds (fail fast on connection issues)
- Read/Write timeout: 30 seconds (reasonable for API operations)

This provides:
1. Faster failure detection when connection issues occur
2. Clearer error messages indicating timeout vs other failures
3. Consistent behavior across all platforms

**Files Changed**:
- `src/platform/github.rs` - Added timeouts to Octocrab builder and helper `http_client()` method
- `src/platform/gitlab.rs` - Added timeouts to reqwest Client
- `src/platform/azure.rs` - Added timeouts to reqwest Client
- `src/platform/bitbucket.rs` - Added timeouts via helper `http_client()` method

Closes #63

---

### Feature: Shell autocompletions ✓

### Feature: Shell autocompletions ✓

**Completed**: 2026-01-31

Added `gr completions <shell>` command using clap_complete crate.
- Supports: bash, zsh, fish, elvish, powershell
- Usage: `gr completions bash > ~/.local/share/bash-completion/completions/gr`
- Or eval: `eval "$(gr completions bash)"`

---

### Feature: E2E PR testing on GitLab ✓

**Completed**: 2026-01-31

- Added `test_gitlab_full_pr_workflow` test
- Fixed GitLab token parsing to find "Token found:" pattern from glab
- Changed GitLab API auth from PRIVATE-TOKEN to Bearer auth (works for OAuth2 tokens from glab)
- Azure DevOps tests added but require user to complete interactive browser login once

---

### Fix: Griptree worktree operations ✓

**Completed**: 2026-01-31

- Fixed "fatal: this operation must be run in a work tree" errors in griptrees
- Changed all git CLI calls to use `repo.workdir()` instead of `repo.path().parent()`
- `repo.path()` returns `.git/worktrees/<name>` for worktrees, which broke git commands
- `repo.workdir()` correctly returns the actual working directory for both regular repos and worktrees
- Affected commands: `gr sync`, `gr add`, `gr commit`, `gr push`, `gr status`, etc.

---

## Pending Review

### Missing: `gr sync` shows which repos failed ✓

**Status**: ✅ **COMPLETED** - Implemented in PR #131 (v0.5.6)

**Discovered**: 2026-02-01

**Problem**: `gr sync` reports "X failed" with no details about which repositories failed or why.

**Solution**: Now shows per-repo status with clear indicators:
```
Syncing 8 repositories...
✓ tooling: synced
✓ codex: synced
⚠ opencode: not cloned
✗ private: failed - Failed to fetch: authentication required
```

---

### Missing: `gr push` shows which repos failed ✓

**Status**: ✅ **COMPLETED** - Implemented in PR #141 (v0.5.6)

**Discovered**: 2026-02-01

**Problem**: `gr push` reports "X failed, Y skipped" with no details about which repositories failed or were skipped.

**Solution**: Now shows detailed results with per-repo status:
```
Pushing 8 repositories...
✓ tooling: pushed to feat/my-feature
✓ codex: pushed to feat/my-feature  
⚠ opencode: skipped (no changes)
✗ private: failed - authentication required
```

---


### Feature: Reference repos (read-only repos excluded from branch/PR operations) ✓

**Status**: ✅ **COMPLETED** - Implemented in PR for v0.5.4

**Discovered**: 2026-02-01 during Rust migration planning

**Problem**: When adding reference implementations to a workspace (e.g., `opencode`, `codex`, `crush`), these repos are only for reading/learning - we never plan to edit them or create PRs. Previously `gr branch` created branches across all repos, and `gr pr create` would try to create PRs in all repos with the branch.

**Solution**: Added `reference: true` flag in manifest to mark repos as read-only:

```yaml
repos:
  opencode:
    url: https://github.com/anomalyco/opencode.git
    path: ./ref/opencode
    reference: true  # Excluded from branch/PR operations
```

**Behavior**: Reference repos still sync and show in status (with `[ref]` indicator) but are skipped in branch/checkout and PR operations.

---

### Feature: `gr status` should show ahead/behind main ✓

**Status**: ✅ **COMPLETED** - Implemented in PR for v0.5.3

**Discovered**: 2026-01-31

**Problem**: `gr status` showed local uncommitted changes but didn't show how the current branch compares to main/upstream. This made it hard to know if you need to rebase before creating a PR or if main has moved ahead.

**Solution**: Added "vs main" column showing ahead/behind status:
```
Repo          Branch           Status  vs main
------------  ---------------  ------  -------
tooling       feat/new-api     ~3      ↑2 ↓5
frontend      feat/new-api     ✓       ↑4
backend       main             ✓       -

  3/3 cloned | 1 with changes | 2 ahead of main
```

- `↑N` = N commits ahead of default branch (your changes)
- `↓N` = N commits behind default branch (need to rebase/merge)
- `-` = on default branch, no comparison needed
- `↑N ↓M` = both ahead and behind (diverged)

---

### Missing: Single-repo branch creation from existing commit ✓

**Status**: ✅ **COMPLETED** - Implemented in PR #167

**Discovered**: 2026-01-29 during centralized griptree metadata implementation

**Problem**: Accidentally committed to `main` instead of a feature branch.

**Solution**: Added `--move` flag to `gr branch`:
```bash
gr branch feat/x --move --repo tooling
```
This creates the new branch at HEAD, resets current branch to origin/main, and checkouts the new branch.

### Missing: Non-interactive `gr pr create --body` ✓

**Status**: ✅ **COMPLETED** - Implemented

**Discovered**: 2026-01-29 during PR creation

**Problem**: `gr pr create -t "title"` prompted interactively for the PR body. This blocked automation and required falling back to raw `gh pr create` with `--body` flag.

**Solution**: Added `-b/--body` flag to `gr pr create`:
```bash
gr pr create -t "title" -b "body content"
```

### Missing: `gr commit --amend` support ✓

**Status**: ✅ **COMPLETED** - Already implemented in main.rs

**Discovered**: 2026-01-29 during sync fix + repo add implementation

**Problem**: Wanted to amend a commit after review found minor issues (unused import, misleading comment). However, `--amend` flag was already available but not documented in IMPROVEMENTS.md.

**Solution Verified**: The `--amend` flag already existed and works correctly:
```bash
# Amend with new message
gr commit --amend -m "Updated message"

# Keep same message (still requires -m flag)
gr commit --amend -m "Updated message"
```

**Implementation**
- CLI: `#[arg(long)] amend: bool` in main.rs
- Backend: `create_commit()` handles amend correctly
- Tests: Unit test `test_amend_commit` passes

Closes #59

### Missing: `gr pr checks` command ✓

**Status**: ✅ **COMPLETED** - Already implemented

**Discovered**: 2026-01-29 during PR review workflow

**Problem**: Wanted to check CI status across all repos with PRs, assumed it wasn't implemented.

**Solution Verified**: `gr pr checks` command already exists and works:
```bash
gr pr checks              # Pretty output
gr pr checks --json       # JSON output for scripting
```

**Output Format**:
```
CI/CD Check Status

● strategy
● homebrew-tap #9
● public #253
    ● Type Check queued
    ● Test (ubuntu-latest) queued
    ✓ Test (macos-latest) success

Summary: 3 passed, 0 failed, 3 pending
```

**Features**:
- Shows all linked PRs for current branch
- Aggregates status across repos (GitHub/GitLab/AzureDevOps)
- Lists individual checks with indicators
- Summary with counts
- JSON output for scripts
- Exit code non-zero if checks failing

Closes #60

### Feature: `gr forall` should default to changed repos only ✓

**Status**: ✅ **COMPLETED** - Implemented in PR #165

**Discovered**: 2026-01-29 during workflow discussion

**Problem**: `gr forall -c "pnpm test"` runs in ALL repos, even ones with no changes. This wastes time running tests in repos that haven't been modified. Running in all repos should be opt-in, not the default.

**Solution**: Default changed to repos with changes only:
```bash
# Only run in repos with changes (NEW DEFAULT)
gr forall -c "pnpm test"

# Explicitly run in ALL repos
gr forall -c "pnpm test" --all
```

**Breaking change**: Yes, use `--all` for previous behavior.

---

## Session Reports

### PR merge check runs fix (2026-02-01)

**Task**: Fix #93 - gr pr merge doesn't recognize passing GitHub checks

**Overall Assessment**: gr workflow was smooth, minor friction with PR creation body flag.

#### What Worked Well ✅

1. **`gr branch`** - Created feature branch across all repos seamlessly
2. **`gr add`** - Staged changes correctly in tooling repo
3. **`gr commit`** - Committed with descriptive message
4. **`gr pr create`** (via gh) - Created PR successfully

#### Issues Created

| Issue | Title |
|-------|-------|
| #63 | fix: gr pr create command times out |

#### Raw Commands Used (Friction Log)

| Raw Command | Why `gr` Couldn't Handle It | Issue |
|-------------|----------------------------|-------|
| `gh pr create --body` | `gr pr create` lacks `--body` flag for PR body | #58 |

#### Minor Friction (No Raw Commands Needed)

| Observation | Notes |
|-------------|-------|
| `gr sync` - 1 failed | "7 synced, 1 failed" with no details on which repo failed | New friction point |
| `gr push` - 2 failed | "5 pushed, 2 failed, 1 skipped" with no error details | New friction point |

---


### Multi-Platform Support Implementation (2026-01-29)

**Overall Assessment**: `gr` worked smoothly for this feature. No raw `git` or `gh` commands were needed.

#### What Worked Well ✅

1. **`gr branch`** - Created feature branch across all repos
2. **`gr add`, `gr commit`, `gr push`** - Smooth workflow for iterative commits
3. **`gr pr create`** - Created PR correctly
4. **`gr pr merge --force`** - Merged successfully
5. **`gr checkout main && gr sync`** - Clean return to main after merge

#### Issues Created

| Issue | Title |
|-------|-------|
| #34 | feat: Add Bitbucket platform support |
| #35 | feat: Use GitHub Check Runs API for better status checks |
| #36 | feat: Add retry logic with exponential backoff |
| #37 | feat: Add rate limiting handling |
| #39 | feat: improve check status messaging in gr pr merge |

#### Minor Friction (No Raw Commands Needed)

| Observation | Notes |
|-------------|-------|
| Check status messaging | `gr pr merge` showed "checks not passing" when check was actually SKIPPED. Issue #39 created. |

---

### Homebrew Tap Addition (2026-01-29)

**Task**: Add homebrew-tap repo to workspace and update formula for v0.3.0

#### Issues Created

| Issue | Title |
|-------|-------|
| #43 | feat: add gr repo add command for adding new repos to workspace |
| #44 | fix: gr sync should not discard uncommitted manifest changes |

#### Raw Commands Used (Friction Log)

| Raw Command | Why `gr` Couldn't Handle It | Issue |
|-------------|----------------------------|-------|
| `git clone git@github.com:laynepenney/homebrew-tap.git` | No command to add new repo to workspace | #43 |
| `cd .gitgrip/manifests && git add && git commit` | Manifest changes needed manual handling after sync reset | #44 |
| `cd homebrew-tap && git checkout -b && git push` | New repo not yet managed by gr | #43 |

---

### Commercial Plugin Architecture Implementation (2026-01-28)

**Overall Assessment**: `cr` worked very well for this multi-repo workflow. The core commands handled the majority of operations smoothly.

#### What Worked Well ✅

1. **`cr branch`** - Created branches across all 4 repos seamlessly
2. **`cr status`** - Excellent visibility into repo states, showed changes clearly
3. **`cr add`, `cr commit`, `cr push`** - Worked exactly as expected across repos
4. **`cr pr create`** - Created linked PRs in both codi and codi-private correctly
5. **`cr pr status`** - Showed PR status with checks, approval, mergeable state
6. **`cr sync`** - Pulled and synced repos correctly after merges
7. **`cr checkout main`** - Switched all repos back to main after merge
8. **`cr diff --stat`** - Useful for reviewing changes before commit

#### Issues Created

| Issue | Title |
|-------|-------|
| #25 | fix: improve error handling for cr pr merge failures |
| #26 | fix: cr pr status shows stale check status |
| #27 | feat: add cr branch --delete for cleanup |
| #28 | feat: add cr rebase with upstream branch tracking |
| #29 | feat: add cr pr diff to show combined PR diff |
| #30 | feat: add cr pr checks to show CI status |

#### Raw Commands Used (Friction Log)

| Raw Command | Why `cr` Couldn't Handle It | Issue |
|-------------|----------------------------|-------|
| `git fetch origin main && git rebase origin/main` | No rebase command | #28 |
| `git push --force-with-lease` | No force push after rebase | #28 |
| `gh pr merge 209 --squash` | `cr pr merge` failed with 405 | #25 |
| `gh pr diff 209` | No PR diff command | #29 |
| `gh pr checks 209` | No PR checks command | #30 |
| `git branch -d feat/...` | No branch delete command | #27 |
| `git push origin --delete feat/...` | No remote branch delete | #27 |

---

## Approved (Ready for Issues)

_No items approved._

---

## Completed

_Items that have been implemented. Keep for historical reference._

### `cr pr status/merge` branch check fix (Issue #20)
- **Added in**: PR #21
- **Description**: `cr pr status` and `cr pr merge` now find PRs by checking each repo's own branch. Repos on their default branch are skipped.

### `cr pr create` branch check fix
- **Added in**: PR #19
- **Description**: `cr pr create` now only checks branch consistency for repos with changes. Repos on `main` with no changes no longer block PR creation.

### `cr forall` command (Issue #15)
- **Added in**: PR #17
- **Description**: Run arbitrary commands in each repository with `cr forall -c "command"`. Supports `--repo`, `--include-manifest`, and `--continue-on-error` flags.

### Manifest repo managed by cr (Issue #9)
- **Added in**: PR #12
- **Description**: Manifest repo (`.codi-repo/manifests/`) is now automatically included in all `cr` commands when it has changes. `cr status` shows manifest in a separate section. `cr branch --include-manifest` explicitly includes manifest. `cr pr create/status/merge` handle manifest PRs.

### `cr sync` manifest recovery (Issue #4)
- **Added in**: PR #10
- **Description**: `cr sync` now automatically recovers when manifest's upstream branch was deleted after PR merge

### `cr commit` command (Issue #5)
- **Added in**: PR #10
- **Description**: Commit staged changes across all repos with `cr commit -m "message"`

### `cr push` command (Issue #6)
- **Added in**: PR #10
- **Description**: Push current branch across all repos with `cr push`

### `cr bench` command
- **Added in**: PR #1
- **Description**: Benchmark workspace operations with `cr bench`

### `--timing` flag
- **Added in**: PR #1
- **Description**: Global `--timing` flag shows operation timing breakdown

### `cr add` command (Issue #7)
- **Added in**: PR #11
- **Description**: Stage changes across all repos with `cr add .` or `cr add <files>`

### `cr diff` command (Issue #8)
- **Added in**: PR #11
- **Description**: Show diff across all repos with `cr diff`, supports `--staged`, `--stat`, `--name-only`

### `cr branch --repo` flag (Issue #2)
- **Added in**: PR #11
- **Description**: Create branches in specific repos only with `cr branch feat/x --repo tooling`

---

## Issues Created from These Entries

| Issue # | Title |
|---------|-------|
| #58 | feat: add --body flag to gr pr create |
| #59 | feat: add --amend flag to gr commit |
| #60 | feat: add gr pr checks command |
| #61 | feat: gr forall should default to changed repos only |
| #62 | feat: add single-repo branch creation for fixing commits |
| #63 | fix: gr pr create command times out |
| #99 | fix: gr pr merge doesn't recognize passing checks |
| #112 | fix: gr repo add corrupts manifest YAML structure |
| #113 | feat: add reference repos (read-only repos excluded from branch/PR operations) |
| #129 | fix: gr push shows 'failed' for repos with no changes to push |
| #130 | fix: gr pr merge reports 'checks failing' when checks actually passed |

Created: 2025-12-05
Updated: 2026-02-01


---

### Bug: `gr repo add` corrupts manifest YAML structure ✓

**Status**: ✅ **COMPLETED** - Fixed in PR for v0.5.6

**Discovered**: 2026-02-01 during reference repo addition

**Problem**: `gr repo add` placed the new repo entry between `version:` and `manifest:` sections instead of under `repos:`. This caused manifest parsing to fail.

**Solution**: YAML insertion logic now correctly places repos under `repos:` section.


---

### Bug: `gr push -u` shows failures for repos with no changes ✓

**Status**: ✅ **COMPLETED** - Already working correctly

**Discovered**: 2026-02-01 during sync no-upstream fix

**Problem**: Assumed repos without changes showed as "failed" instead of "skipped".

**Verified Working**: Current behavior correctly handles this:
```bash
$ gr push
Pushing changes...

ℹ tooling: nothing to push
ℹ public: nothing to push

Nothing to push.
```

**Implementation Verified**:
- `has_commits_to_push()` checks for commits ahead of remote
- Repos with nothing to push show "ℹ {repo}: nothing to push"
- Summary correctly shows "Nothing to push." when all skipped
- Error handling distinguishes between "nothing to push" and actual failures

Closes #129

---

### Bug: `gr pr merge` reports "checks failing" when checks passed / API errors ✓

**Status**: ✅ **COMPLETED** - Fixed in PR

**Discovered**: 2026-02-01 during sync no-upstream fix (PR #127)

**Problem**: `gr pr merge` reported "checks failing" when:
1. GitHub API returned 404/no checks found (API errors treated as failing)
2. Checks were actually passing but API query failed
3. Had to fall back to `gh pr merge --admin`

**Root Cause**: In `merge.rs`, the code treated ALL errors from `get_status_checks()` as "checks failing":
```rust
Err(_) => false,  // Bug: Any API error = checks failing
```

**Solution**: Added proper error handling with `CheckStatus` enum:
- `Passing` - Checks succeeded
- `Failing` - Checks actually failing (blocks merge)
- `Pending` - Checks still running (blocks merge with warning)
- `Unknown` - Could not determine status (warns but allows merge)

Now API errors (404, network issues, etc.) show a warning but don't block merge:
```rust
Err(e) => {
    Output::warning(&format!(
        "{}: Could not check CI status for PR #{}: {}",
        repo.name, pr.number, e
    ));
    CheckStatus::Unknown
}
```

**Benefits**:
- No longer blocked by transient API issues
- Clear distinction between "checks failing" vs "can't check"
- Better messaging for pending/running checks
- Users can still `--force` if needed

Closes #130

---

### Feature: Auto-discovery of legacy griptrees ✓

**Status**: ✅ **COMPLETED** - Already implemented in tree.rs

**Discovered**: 2026-01-31 during Rust migration testing

**Problem**: The Rust implementation stores griptrees in `.gitgrip/griptrees.json`, but the TypeScript version stored a `.griptree` marker file in each griptree directory. Existing griptrees from the TypeScript version don't show up in `gr tree list`.

**Solution**: `gr tree list` now automatically discovers unregistered griptrees:
1. Scans sibling directories for `.griptree` pointer files
2. Checks if they point to the current workspace
3. Shows discovered griptrees with "unregistered" status
4. Provides guidance on how to add them to griptrees.json

**Output Example**:
```
Griptrees

  feat-auth -> /Users/layne/Development/feat-auth

⚠ Found unregistered griptrees:
  codi-dev -> /Users/layne/Development/codi-dev (unregistered)

These griptrees point to this workspace but are not in griptrees.json.
You can manually add them to griptrees.json if needed.
```

**Implementation**: `discover_legacy_griptrees()` function in `src/cli/commands/tree.rs`


---

### Fix: Git worktree conflict provides helpful error message ✓

**Completed**: 2026-02-02

**Discovered**: 2026-02-02 during PR #118, #141 work

**Problem**: When a branch is checked out in another worktree, git gives a cryptic error:
```
fatal: 'main' is already used by worktree at '/Users/layne/Development/codi-workspace/gitgrip'
```

**Solution**: Enhanced error handling in `checkout_branch()` and `create_and_checkout_branch()` to detect worktree conflicts and provide actionable guidance:
```
Branch 'main' is checked out in another worktree at '/path/to/worktree'.
Either use that worktree or create a new branch with 'gr branch <name>'
```

**Files Changed**: `src/git/branch.rs`

Note: This is a git limitation - the same branch cannot be checked out in multiple worktrees simultaneously. The improved error message helps users understand the situation and suggests alternatives.

---

### Friction: Repeated merge conflicts in IMPROVEMENTS.md

**Discovered**: 2026-02-02 during multiple PR rebases

**Problem**: When rebasing feature branches, kept hitting merge conflicts in IMPROVEMENTS.md because documentation commits from other PRs were also on main.

**Reproduction**:
```bash
gr branch fix/pr-merge-check-runs
# ... work on PR ...
git fetch origin main && git rebase origin/main
# CONFLICT in IMPROVEMENTS.md!
```

**Expected behavior**: Either:
- Documentation changes don't cause merge conflicts during rebase
- Better tooling to resolve such conflicts

**Suggested fix**: Consider whether documentation should be kept in a separate file/location, or document this as expected behavior and provide conflict resolution helpers.

---

### Friction: CI blocking merge with unclear status

**Discovered**: 2026-02-02 during PR #141 merge

**Problem**: PR showed "Repository rule violations found - Required status check 'CI' is expected" even though tests were passing. Had to wait significantly longer for the CI check to actually complete.

**Reproduction**:
```bash
gh pr checks 141
# Shows: Check pass, Clippy pass, Tests pass...
# But merge fails with: "Required status check 'CI' is expected"

# Wait 2+ minutes...
gh pr view 141 --json mergeStateStatus  # Still shows CLEAN, but CI pending
```

**Expected behavior**: Either:
- Better visibility of which specific CI check is pending
- Merge blocked with clearer message about what's pending
- Auto-wait for CI to complete before reporting block

**Suggested fix**: Improve status reporting in CLI to show pending CI jobs more prominently.

---

### Friction: Formatting required multiple passes

**Discovered**: 2026-02-02 during PR #138, #140 work

**Problem**: Had to run `cargo fmt` multiple times as formatting kept failing CI even though it passed locally once.

**Reproduction**:
```bash
cargo fmt  # Passes locally
gr push    # CI fails on Format check
# Fix formatting locally again
cargo fmt  # Now finds more issues
```

**Expected behavior**: `cargo fmt` should be deterministic and produce consistent results in CI.

**Suggested fix**: Add pre-commit hook for formatting, or ensure CI uses same rust-toolchain as local.

---

### Friction: PR got contaminated with unrelated changes

**Discovered**: 2026-02-02 during PR #140 → #141

**Problem**: Created PR #140 with github.rs changes that belonged to PR #118. Had to close it and create a clean PR #141 with only push.rs changes.

**Reproduction**:
```bash
# Working on two branches
gr branch fix/push-nothing-to-push     # For push count fix
gr branch fix/pr-merge-check-runs     # For check runs fix

# Changes from fix/pr-merge-check-runs got committed to fix/push branch
gh pr create  # PR #140 contains both fixes mixed together
```

**Expected behavior**: Either:
- Branch isolation prevents cross-contamination
- Clear visual indicator of which files changed in PR diff before creating

**Suggested fix**: Better branch management, or PR preview before creation showing all modified files.

---

### gr pr merge --force still fails with all-or-nothing strategy

**Discovered**: 2026-02-03 while merging documentation PRs

**Problem**: Even with `--force` flag, `gr pr merge --force` failed because the `all-or-nothing` merge strategy requires ALL PRs to merge together. When some PRs had false-positive issues ("not approved", "checks still running" for docs repos), the entire merge was blocked.

**Error**: "Stopping due to all-or-nothing merge strategy. Error: API error: Failed to merge PR"

**Workaround used**: Had to use individual `gh pr merge` commands for each PR:
```bash
gh pr merge 179 --repo laynepenney/gitgrip --squash --delete-branch
gh pr merge 16 --repo laynepenney/codi-strategy --squash --delete-branch
```

**Expected behavior**:
- `--force` should bypass all checks and merge regardless of strategy
- Or have a `--strategy independent` flag to merge PRs separately
- Documentation-only PRs shouldn't require CI checks

---

### Friction: `gr pr merge --force` fails on repos with branch protection

**Discovered**: 2026-02-03 during PR #267 merge
**Recurrence**: 2026-02-04 during PR #194 merge (Phase 4 features)

**Problem**: `gr pr merge --force` fails with "API error: Failed to merge PR: GitHub" when the repository has branch protection rules requiring review approvals. The `--force` flag is supposed to bypass `gr`-level checks (like "not approved" warnings), but it cannot override GitHub branch protection.

**Workaround used**: Had to fall back to `gh pr merge --squash --admin` which bypasses branch protection with admin privileges.

**Raw commands used**:
```bash
gh pr merge 267 --squash --auto    # PR #267
gh pr merge 194 --repo laynepenney/gitgrip --squash --admin  # PR #194
```

**Expected behavior**: Either:
- `gr pr merge --force` should use `--admin` flag on GitHub to bypass protection (with a warning)
- Or provide a clearer error message: "Branch protection requires review approval. Use `gh pr merge --admin` to bypass."
- Or support `gr pr merge --admin` flag that passes through to the platform

---

### Feature: `--quiet` flag for AI-optimized output ✓

**Status**: ✅ **COMPLETED**

**Discovered**: 2026-02-03 during AI workspace optimization

**Problem**: When AI tools (Claude Code, Codi, etc.) use `gr` commands, every command outputs per-repo status lines even for repos with no relevant changes. In a workspace with 8+ repos, most of `gr status` output is "✓ clean" lines, `gr sync` outputs "up to date" for every repo, and `gr push` outputs "nothing to push" for every repo. This wastes tokens -- each unnecessary output line costs tokens for the AI to process and adds no information.

**Solution**: Added global `--quiet` / `-q` flag that suppresses output for repos with no relevant changes:

```bash
# Normal output (8 repos, only 1 has changes):
gr status
# Shows all 8 repos in table

# Quiet mode (only shows repos that matter):
gr -q status
# Shows only the 1 repo with changes + summary

# Works with other commands:
gr -q sync     # Suppresses "up to date" messages
gr -q push     # Suppresses "nothing to push" messages
```

**Token savings**: For a workspace with N repos where K have changes:
- `gr status`: Output reduced from ~N lines to ~K lines
- `gr sync`: Output reduced from ~N lines to ~K lines (only cloned/pulled repos shown)
- `gr push`: Output reduced from ~N lines to ~K lines (only pushed repos shown)
- Typical savings: 60-80% fewer output tokens for status/sync/push in a 5-8 repo workspace

**Implementation**:
- Global `--quiet` / `-q` flag via clap (available on all subcommands)
- `status.rs`: Filters table to only repos with changes or not on default branch
- `sync.rs`: Suppresses "up to date" spinner messages
- `push.rs`: Suppresses "nothing to push" info messages
- Errors and warnings always shown regardless of quiet mode
- Summary lines always shown (compact overview)

**AI workspace value proposition**: `gr` saves tokens vs raw `git` in two ways:
1. **Fewer commands**: One `gr status` replaces N separate `git status` calls
2. **Less output** (with `-q`): Only shows repos that need attention

---

### gr pr create doesn't work for manifest-only changes

**Discovered**: 2026-02-03 while adding git-repo reference

**Problem**: `gr pr create` reported "No PRs were created" even though the manifest repo had uncommitted changes (manifest.yaml and CODI.md updates). The command pushed branches but failed to create the actual PR.

**Workaround used**: Had to manually push with `git push -u origin codi-gripspace` from the manifest directory, then use `gh pr create` with `--repo laynepenney/codi-workspace` flag to create the PR.

**Raw commands used**:
```bash
cd /Users/layne/Development/codi-gripspace/.gitgrip/manifests
git push -u origin codi-gripspace
gh pr create --title "..." --body "..." --repo laynepenney/codi-workspace
```

**Expected behavior**: `gr pr create` should:
- Detect manifest repo changes like it does for regular repos
- Create the PR automatically without manual intervention
- Handle the manifest repo URL correctly

**Additional friction**:
- Had to cd to `.gitgrip/manifests` directory to run git commands
- `gr push -u` showed "Nothing to push" even though manifest had commits
- The manifest repo wasn't being tracked as having changes by `gr`

---
