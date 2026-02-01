# gitgrip Improvement Ideas

This file captures friction points, feature ideas, and bugs discovered while using `gr`.
Items here should be reviewed before creating GitHub issues.

> **Note**: Historical entries may reference `cr` (the old command name). The current command is `gr`.

---

### PR Creation Timeout Issue

**Discovered**: 2025-12-05 during codi.md documentation PR

**Problem**: `gr pr create` consistently times out (~30s) even when:
- `gh auth status` shows authenticated user with `repo` scope
- Git operations work (push, status, diff)
- Other `gr` commands work normally

**Reproduction**:
```bash
gr pr create -t "title" --push    # times out
gr pr create -t "title"           # times out
```

**Workaround**:
```bash
cd codi && gh pr create --title "docs: clarify codi/codi-private setup" --body "..." --base main
```

**Potential causes**:
- Browser-based auth flow required
- Token refresh issue in this environment  
- Missing `--body` flag causing interactive prompt

---

## Completed

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

### Feature: Reference repos (read-only repos excluded from branch/PR operations) → Issue #113

**Discovered**: 2026-02-01 during Rust migration planning

**Problem**: When adding reference implementations to a workspace (e.g., `opencode`, `codex`, `crush`), these repos are only for reading/learning - we never plan to edit them or create PRs. Currently, `gr branch` creates branches across ALL repos, and `gr pr create` would try to create PRs in all repos with the branch.

**Current behavior**:
```bash
gr branch feat/my-feature  # Creates branch in ALL repos including references
gr pr create -t "title"    # Would try to create PRs in reference repos too
```

**Suggested behavior**:
Add a `reference: true` flag in manifest to mark repos as read-only:

```yaml
repos:
  # Normal repos - participate in branch/PR operations
  public:
    url: git@github.com:org/public.git
    path: ./public

  # Reference repos - excluded from branch/PR operations
  opencode:
    url: https://github.com/anomalyco/opencode.git
    path: ./ref/opencode
    reference: true  # <-- NEW FLAG

  codex:
    url: https://github.com/openai/codex.git
    path: ./ref/codex
    reference: true
```

**Behavior changes for reference repos**:
- `gr branch` - Skip (don't create branches)
- `gr checkout` - Skip (stay on default branch)
- `gr pr create` - Skip (no PRs)
- `gr pr merge` - Skip
- `gr sync` - Still sync (pull latest from upstream)
- `gr status` - Still show (maybe with `[ref]` indicator)
- `gr forall` - Include by default, or add `--no-ref` flag

**Alternative**: Could use path convention instead of flag:
- Any repo with `path: ./ref/*` is automatically treated as reference

**Use cases**:
1. Reference implementations for learning/comparison
2. Upstream dependencies you track but don't modify
3. Documentation repos you only read

---

### Feature: `gr status` should show ahead/behind main

**Discovered**: 2026-01-31

**Problem**: `gr status` shows local uncommitted changes but doesn't show how the current branch compares to main/upstream. This makes it hard to know if you need to rebase before creating a PR or if main has moved ahead.

**Current behavior**:
```
Repo          Branch           Status
------------  ---------------  ------
tooling       feat/new-api     ~3
frontend      feat/new-api     ✓
```

**Suggested behavior**:
```
Repo          Branch           Status  Ahead/Behind
------------  ---------------  ------  ------------
tooling       feat/new-api     ~3      ↑2 ↓5
frontend      feat/new-api     ✓       ↑4
backend       main             ✓       -

  3/3 cloned | 1 with changes | 2 ahead of main
```

**What it would show**:
- `↑2` = 2 commits ahead of default branch (your changes)
- `↓5` = 5 commits behind default branch (need to rebase/merge)
- `-` = on default branch, no comparison needed

**Options**:
- `--ahead` or `-a` flag to enable (if too slow by default)
- `--diff-stat` to show file change summary vs main
- Could be default behavior since it's fast to compute with `git rev-list`

**Implementation**:
```rust
// For each repo not on default branch:
let (ahead, behind) = repo.graph_ahead_behind(head_oid, main_oid)?;
```

---

### Missing: Single-repo branch creation from existing commit

**Discovered**: 2026-01-29 during centralized griptree metadata implementation

**Problem**: Accidentally committed to `main` instead of a feature branch. Needed to create a feature branch from the current commit, then reset main to origin/main. `gr branch` creates branches across ALL repos, which isn't appropriate for fixing a single-repo mistake.

**Workaround**:
```bash
cd gitgrip
git branch feat/centralized-griptree-metadata  # Create branch at HEAD
git reset --hard HEAD~1                         # Reset main
git checkout feat/centralized-griptree-metadata # Switch to feature
```

**Suggested**: Add `--repo` support for branch creation in a single repo:
```bash
gr branch feat/x --repo tooling  # Already supported, but doesn't handle "move commit" scenario
```

Or add a "move last commit to new branch" helper.

### Missing: Non-interactive `gr pr create --body`

**Discovered**: 2026-01-29 during PR creation

**Problem**: `gr pr create -t "title"` prompts interactively for the PR body. This blocks automation and requires falling back to raw `gh pr create` with `--body` flag.

**Workaround**:
```bash
gh pr create --title "title" --body "$(cat <<'EOF'
body content
EOF
)"
```

**Suggested**: Add `--body` or `-b` flag to `gr pr create`:
```bash
gr pr create -t "title" -b "body content"
# Or read from stdin:
echo "body" | gr pr create -t "title" --body-stdin
```

### Missing: `gr commit --amend` support

**Discovered**: 2026-01-29 during sync fix + repo add implementation

**Problem**: Needed to amend a commit after review found minor issues (unused import, misleading comment). Had to use `git commit --amend --no-edit` directly.

**Workaround**: `gr add <files> && git commit --amend --no-edit`

**Suggested**: Add `--amend` flag to `gr commit`

### Missing: `gr pr checks` command

**Discovered**: 2026-01-29 during PR review workflow

**Problem**: To check CI status across all repos with PRs, must run `gh pr checks <number>` separately for each repo. No way to see combined check status across all linked PRs.

**Workaround**:
```bash
gh pr checks 47 --repo laynepenney/gitgrip
# Repeat for each repo with a PR...
```

**Suggested**: Add `gr pr checks` command that:
1. Shows check status for all linked PRs in the current branch
2. Aggregates pass/fail/pending status across repos
3. Blocks/warns if any checks are failing

**Example output**:
```
PR Checks for branch: feat/my-feature

  Repo       PR    Check              Status
  ─────────────────────────────────────────────
  tooling    #47   build              ✓ pass
  tooling    #47   test               ✓ pass
  tooling    #47   sync-status        ⏭ skipped
  frontend   #123  build              ✓ pass
  frontend   #123  deploy-preview     ⏳ pending

  Summary: 4 passed, 1 pending, 0 failed
```

**Related**: Issue #30 (cr pr checks) was created previously but not yet implemented.

### Feature: `gr forall` should default to changed repos only

**Discovered**: 2026-01-29 during workflow discussion

**Problem**: `gr forall -c "pnpm test"` runs in ALL repos, even ones with no changes. This wastes time running tests in repos that haven't been modified. Running in all repos should be opt-in, not the default.

**Current behavior**:
```bash
gr forall -c "pnpm test"  # Runs in ALL repos (wasteful)
gr forall -c "pnpm test" --repo tooling  # Must manually specify repos
```

**Suggested**: Default to repos with changes, require `--all` for all repos:

```bash
# Only run in repos with changes (NEW DEFAULT)
gr forall -c "pnpm test"

# Explicitly run in ALL repos
gr forall -c "pnpm test" --all

# Only repos with staged changes
gr forall -c "pnpm build" --staged

# Only repos with commits ahead of main
gr forall -c "pnpm lint" --ahead
```

**Use cases**:
1. Run tests only in modified repos before committing (default)
2. Run build only in repos that changed (default)
3. CI/CD that needs all repos uses `--all`
4. Pre-push hooks automatically only check affected repos

**Implementation notes**:
- Default = has uncommitted changes OR commits ahead of default branch
- `--staged` = only repos with staged changes
- `--ahead` = only repos with commits ahead of default branch
- `--all` = all repos (current behavior, becomes opt-in)

**Breaking change**: Yes, but safer default. Could warn for one version.

---

## Session Reports

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

Created: 2025-12-05
Updated: 2026-02-01


---

### Bug: `gr repo add` corrupts manifest YAML structure → Issue #112

**Discovered**: 2026-02-01 during reference repo addition

**Problem**: `gr repo add` placed the new repo entry between `version:` and `manifest:` sections instead of under `repos:`. This caused manifest parsing to fail with error: `version: invalid type: string "1\n\nopencode", expected u32`

**Reproduction**:
```bash
gr repo add https://github.com/opencode-ai/opencode.git --path ./ref/opencode
```

**What happened**:
```yaml
version: 1

  opencode:                              # <-- WRONG! Placed here
    url: https://github.com/opencode-ai/opencode.git
    path: ./ref/opencode
    default_branch: main
manifest:
  url: ...
```

**What should happen**:
```yaml
version: 1

manifest:
  url: ...

repos:
  # ... existing repos ...

  opencode:                              # <-- Should be here under repos:
    url: https://github.com/opencode-ai/opencode.git
    path: ./ref/opencode
    default_branch: main
```

**Workaround**: Manually edit manifest.yaml to move the repo entry under `repos:` section.

**Root cause**: The YAML insertion logic in `gr repo add` is not correctly identifying the `repos:` section location.

---

### Bug: `gr push -u` shows failures for repos with no changes

**Discovered**: 2026-02-01 during sync no-upstream fix

**Problem**: When pushing a branch that only has commits in some repos, the repos without changes/commits show as "failed" instead of "skipped". This is misleading - there's nothing to push, so it's not really a failure.

**Reproduction**:
```bash
gr branch fix/something
# Make changes only in tooling repo
gr add . && gr commit -m "fix: something"
gr push -u
# Output: "5 pushed, 3 failed, 0 skipped"
```

**Expected behavior**:
```
# Output should be: "1 pushed, 0 failed, 7 skipped (no changes)"
```

**Notes**: The "failed" repos are ones where the branch exists locally but has no commits to push. They should be counted as "skipped" or "nothing to push".

---

### Bug: `gr pr merge` reports "checks failing" when checks passed

**Discovered**: 2026-02-01 during sync no-upstream fix (PR #127)

**Problem**: `gr pr merge` reported "checks failing" and refused to merge, but when checking with `gh pr checks`, all checks had passed (including the CI summary job). Had to fall back to `gh pr merge --admin`.

**Reproduction**:
```bash
gr pr merge
# Output: "tooling PR #127: checks failing"
# But: gh pr checks 127 --repo laynepenney/gitgrip shows all passing
```

**Workaround**:
```bash
gh pr merge 127 --repo laynepenney/gitgrip --squash --admin
```

**Possible causes**:
- Stale check status caching
- Not waiting for CI summary job to complete
- Check status API query not matching GitHub's merge requirements

**Related**: Issue #99 (gr pr merge doesn't recognize passing checks)

---

### Missing: Auto-discovery of legacy griptrees

**Discovered**: 2026-01-31 during Rust migration testing

**Problem**: The Rust implementation stores griptrees in `.gitgrip/griptrees.json`, but the TypeScript version stored a `.griptree` marker file in each griptree directory. Existing griptrees from the TypeScript version don't show up in `gr tree list`.

**Current behavior**:
- `gr tree list` only reads from `.gitgrip/griptrees.json`
- Existing griptrees with `.griptree` marker files are invisible

**Expected behavior**:
- `gr tree list` should scan sibling directories for `.griptree` marker files
- Discovered griptrees should be automatically registered in `griptrees.json`
- Or at minimum, show a message like "Found unregistered griptree: codi-dev"

**Workaround**:
Manually create `.gitgrip/griptrees.json`:
```json
{
  "griptrees": {
    "codi-dev": {
      "path": "/Users/layne/Development/codi-dev",
      "branch": "codi-dev",
      "locked": false,
      "lock_reason": null
    }
  }
}
```

**Suggested implementation**:
Add a `gr tree discover` command or auto-discovery in `gr tree list`.

