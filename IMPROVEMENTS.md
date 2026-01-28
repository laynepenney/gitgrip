# codi-repo Improvement Ideas

This file captures friction points, feature ideas, and bugs discovered while using `cr`.
Items here should be reviewed before creating GitHub issues.

---

## Pending Review

### Workflow Gaps

#### Manifest repo not managed by cr
- **Problem**: The manifest repo (`.codi-repo/manifests/`) requires manual git commands
- **Observation**: This creates inconsistency - sometimes you use `cr`, sometimes raw `git`
- **Proposal**: Consider adding manifest repo to `cr status` output or special handling
- **GitHub Issue**: [#9](https://github.com/laynepenney/codi-repo/issues/9)
- **Priority**: Low

---

## Approved (Ready for Issues)

_Items moved here after user approval. Create GitHub issues and remove from this list._

---

## Completed

_Items that have been implemented. Keep for historical reference._

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
