# codi-repo Improvement Ideas

This file captures friction points, feature ideas, and bugs discovered while using `cr`.
Items here should be reviewed before creating GitHub issues.

---

## Pending Review

### Missing Commands

#### `cr commit`
- **Problem**: Must use raw `git commit` in individual repos, breaking the "always use cr" philosophy
- **Proposal**: `cr commit -m "message"` commits staged changes across all repos with changes
- **GitHub Issue**: [#5](https://github.com/laynepenney/codi-repo/issues/5)
- **Priority**: High - this is used constantly

#### `cr push`
- **Problem**: Must use raw `git push` for iterative pushes during PR development
- **Proposal**: `cr push` pushes current branch in all repos that have commits ahead
- **Note**: `cr pr create --push` exists but requires creating a PR
- **GitHub Issue**: [#6](https://github.com/laynepenney/codi-repo/issues/6)
- **Priority**: High

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

#### `cr sync` fails after PR merge when manifest was on feature branch
- **Problem**: After merging a PR that included manifest changes, `cr sync` fails with "no such ref was fetched" because the manifest repo is still tracking the deleted remote branch
- **Workaround**: Manually `git checkout main && git pull` in manifest repo
- **GitHub Issue**: [#4](https://github.com/laynepenney/codi-repo/issues/4)
- **Priority**: High - happens every PR merge cycle

---

## Approved (Ready for Issues)

_Items moved here after user approval. Create GitHub issues and remove from this list._

---

## Completed

_Items that have been implemented. Keep for historical reference._

### `cr bench` command
- **Added in**: PR #1
- **Description**: Benchmark workspace operations with `cr bench`

### `--timing` flag
- **Added in**: PR #1
- **Description**: Global `--timing` flag shows operation timing breakdown
