# codi-repo Improvement Ideas

This file captures friction points, feature ideas, and bugs discovered while using `cr`.
Items here should be reviewed before creating GitHub issues.

---

## Pending Review

### Missing Commands

#### `cr add`
- **Problem**: Must use raw `git add` in individual repos
- **Proposal**: `cr add .` or `cr add <file>` stages changes across repos
- **GitHub Issue**: [#7](https://github.com/laynepenney/codi-repo/issues/7)
- **Priority**: Medium

#### `cr diff`
- **Problem**: No way to see diffs across all repos in one view
- **Proposal**: `cr diff` shows combined diff, `cr diff --stat` for summary
- **GitHub Issue**: [#8](https://github.com/laynepenney/codi-repo/issues/8)
- **Priority**: Medium

### Command Improvements

#### `cr branch --repo <name>`
- **Problem**: `cr branch` always creates branches in ALL repos even when changes are isolated
- **Proposal**: Add `--repo` flag to target specific repos
- **GitHub Issue**: [#2](https://github.com/laynepenney/codi-repo/issues/2)
- **Priority**: Medium

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
