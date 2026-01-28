---
name: codi-repo
description: Multi-repository workflow using codi-repo (cr). Use this when working with multiple repos, creating branches across repos, syncing repos, creating linked pull requests, or any cross-repo operations.
allowed-tools: Bash(cr *), Bash(node */codi-repo/dist/index.js *)
---

# codi-repo Multi-Repository Workflow

You are working in a multi-repository workspace managed by **codi-repo** (alias: `cr`). Always use `cr` commands for git operations across repos.

## Essential Commands

### Check Status First
```bash
cr status                    # Always check status before operations
```

### Syncing
```bash
cr sync                      # Pull latest from all repos + process links + run hooks
cr sync --fetch              # Fetch only (no merge)
cr sync --no-link            # Skip file linking
cr sync --no-hooks           # Skip post-sync hooks
```

### Branching
```bash
cr branch feat/my-feature              # Create branch across ALL repos
cr branch feat/x --repo tooling        # Create branch in specific repo only
cr branch feat/x --repo a --repo b     # Create branch in multiple specific repos
cr branch feat/x --include-manifest    # Force include manifest repo
cr checkout feat/my-feature            # Switch branch across ALL repos
cr checkout -b new-branch              # Create and switch to new branch
```

Manifest repo is automatically included in branch operations when it has uncommitted changes.

### Git Operations Across Repos
```bash
# Stage changes
cr add                       # Stage all changes in all repos
cr add .                     # Same as above
cr add src/file.ts           # Stage specific files

# View changes
cr diff                      # Show diff across all repos (colored)
cr diff --staged             # Show staged changes only
cr diff --stat               # Show diffstat summary
cr diff --name-only          # Show only filenames

# Commit
cr commit -m "message"       # Commit staged changes in all repos
cr commit -a -m "message"    # Stage all and commit

# Push
cr push                      # Push all repos with commits ahead
cr push -u                   # Set upstream tracking
```

### Pull Request Workflow

**All changes must go through pull requests.**

```bash
# 1. Create linked PRs across repos with changes
cr pr create -t "feat: description"
cr pr create -t "title" -b "body" --draft    # Draft PR with body
cr pr create -t "title" --push               # Push before creating PR

# 2. Check PR status
cr pr status
cr pr status --json

# 3. Merge all linked PRs together
cr pr merge                  # Default merge
cr pr merge -m squash        # Squash merge
cr pr merge -m rebase        # Rebase merge
cr pr merge --no-delete-branch  # Keep branches after merge
```

### File Linking
```bash
cr link                      # Create/update all copyfile and linkfile entries
cr link --status             # Show link status (valid, broken, missing)
cr link --clean              # Remove orphaned links
cr link --force              # Overwrite existing files/links
cr link --dry-run            # Preview changes
```

### Workspace Scripts
```bash
cr run --list                # List available scripts
cr run build                 # Run a named script
cr run build -- --verbose    # Pass arguments to script
cr env                       # Show workspace environment variables
```

### Benchmarking & Timing
```bash
cr status --timing           # Show timing breakdown for any command
cr bench                     # Run all benchmarks
cr bench --list              # List available benchmarks
cr bench manifest-load -n 10 # Run specific benchmark
```

## Workflow Rules

1. **Always run `cr sync` before starting new work**
2. **Always use `cr branch` to create branches** - Creates across all repos simultaneously
3. **Use `cr add`, `cr commit`, `cr push`** instead of raw git commands
4. **Always use pull requests** - No direct pushes to main
5. **Check `cr status` frequently** - Before and after operations

## Typical Workflow

```bash
# Starting new work
cr sync
cr status
cr branch feat/my-feature

# Making changes
# ... edit files ...
cr diff                             # Review changes
cr add .                            # Stage changes
cr commit -m "feat: my changes"     # Commit
cr push -u                          # Push with upstream

# Creating PR
cr pr create -t "feat: my feature"

# After PR approval
cr pr merge
cr sync
cr checkout main
```

## Manifest Structure

The workspace manifest is at `.codi-repo/manifests/manifest.yaml`:

```yaml
version: 1

manifest:
  url: git@github.com:org/manifest.git
  default_branch: main
  linkfile:
    - src: CLAUDE.md
      dest: CLAUDE.md

repos:
  repo-name:
    url: git@github.com:org/repo.git
    path: ./repo-name
    default_branch: main
    copyfile:
      - src: config.example
        dest: config.example
    linkfile:
      - src: dist
        dest: .bin/tool

workspace:
  env:
    NODE_ENV: development
  scripts:
    build:
      description: "Build all packages"
      command: "pnpm -r build"
  hooks:
    post-sync:
      - command: "pnpm install"
        cwd: "./repo-name"
```

## Manifest Repo Management

The manifest repo (`.codi-repo/manifests/`) is automatically included in commands when it has changes:

- **`cr status`** shows a separate "Manifest" section with branch, changes, and ahead/behind
- **`cr add/diff/commit/push`** operate on the manifest alongside regular repos
- **`cr pr create/status/merge`** handle manifest PRs alongside repo PRs
- **`cr branch --include-manifest`** explicitly includes manifest in branch creation

No special flags needed for most commands - manifest is auto-detected.

## Error Recovery

If you encounter issues:

```bash
# Check what's happening
cr status

# If repos are out of sync
cr sync

# If on wrong branch
cr checkout correct-branch

# If links are broken
cr link --force
```
