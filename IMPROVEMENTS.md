# gitgrip Improvement Ideas

This file captures friction points, feature ideas, and bugs discovered while using `gr`.
Items here should be reviewed before creating GitHub issues.

> **Note**: Historical entries may reference `cr` (the old command name). The current command is `gr`.

---

## Pending Review

_No items pending review._

---

## Session Reports

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
