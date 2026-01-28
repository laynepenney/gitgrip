# codi-repo Improvement Ideas

This file captures friction points, feature ideas, and bugs discovered while using `cr`.
Items here should be reviewed before creating GitHub issues.

---

## Pending Review

#### `cr pr status` and `cr pr merge` should work when repos are on different branches
- **Problem**: Similar to the `cr pr create` issue (now fixed), `cr pr status` and `cr pr merge` check the branch of ALL repos instead of repos with PRs/changes.
- **Example**: After fixing `cr pr create`, I still had to use raw `gh pr merge` because `cr pr merge` couldn't find the PRs - it was looking at `main` branch instead of the feature branch.
- **Proposal**: Apply the same fix as `cr pr create` - only check branch consistency for repos that have open PRs.

---

## Approved (Ready for Issues)

_No items approved._

---

## Completed

_Items that have been implemented. Keep for historical reference._

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
