---
name: gitgrip
description: Multi-repository workflow using gitgrip (gr). Use this when working with multiple repos, creating branches across repos, syncing repos, creating linked pull requests, or any cross-repo operations.
allowed-tools: Bash(gr *), Bash(gitgrip *)
---

# gitgrip Multi-Repository Workflow

You are working in a multi-repository workspace managed by **gitgrip** (alias: `gr`). Always use `gr` commands for git operations across repos.

## Essential Commands

### Check Status First
```bash
gr status                    # Always check status before operations
```

### Initializing Workspaces
```bash
# From manifest URL
gr init <manifest-url>               # Clone manifest and all repos

# From existing local directories
gr init --from-dirs                  # Auto-scan current dir for git repos
gr init --from-dirs --dirs ./a ./b   # Scan specific directories only
gr init --from-dirs --interactive    # Preview YAML and edit before saving

# From existing .repo/ directory (git-repo coexistence)
gr init --from-repo
```

### Syncing
```bash
gr sync                      # Pull latest from all repos (parallel) + process links + run hooks
gr sync --sequential         # Sync repos one at a time (ordered output)
gr sync --group core         # Sync only repos in a specific group
```

### Branching
```bash
gr branch feat/my-feature              # Create branch across ALL repos
gr branch feat/x --repo tooling        # Create branch in specific repo only
gr branch feat/x --repo a --repo b     # Create branch in multiple specific repos
gr checkout feat/my-feature            # Switch branch across ALL repos
gr checkout -b new-branch              # Create and switch to new branch
gr checkout --base                     # Return to griptree base branch
gr branch -d old-branch                # Delete branch across repos
gr branch --move feat/new              # Move recent commits to new branch
```

### Git Operations Across Repos
```bash
# Stage changes
gr add                       # Stage all changes in all repos
gr add .                     # Same as above
gr add src/file.ts           # Stage specific files

# View changes
gr diff                      # Show diff across all repos (colored)
gr diff --staged             # Show staged changes only

# Commit
gr commit -m "message"       # Commit staged changes in all repos

# Push
gr push                      # Push all repos with commits ahead
gr push -u                   # Set upstream tracking

# Pull
gr pull                      # Pull latest across repos
gr pull --rebase             # Pull with rebase instead of merge
```

### Rebasing
```bash
gr rebase origin/main        # Rebase onto specific target
gr rebase --upstream         # Rebase onto per-repo upstream (uses griptree config)
gr rebase --abort            # Abort in-progress rebase
gr rebase --continue         # Continue after conflict resolution
```

### Pull Request Workflow

**All changes must go through pull requests.**

```bash
# 1. Create linked PRs across repos with changes
gr pr create -t "feat: description"
gr pr create -t "title" -b "body" --draft    # Draft PR with body
gr pr create -t "title" --push               # Push before creating PR

# 2. Check PR status
gr pr status
gr pr checks                 # Check CI status

# 3. View PR diff
gr pr diff
gr pr diff --stat            # Summary only

# 4. Merge all linked PRs together
gr pr merge                  # Default merge
gr pr merge -m squash        # Squash merge
gr pr merge -m rebase        # Rebase merge
gr pr merge --update         # Update branch from base if behind, then merge
gr pr merge --auto           # Enable auto-merge (merges when checks pass)
gr pr merge --force          # Merge even if checks pending
```

### Searching
```bash
gr grep "pattern"            # Search across all repos
gr grep -i "pattern"         # Case insensitive
gr grep --parallel "pattern" # Concurrent search
gr grep "pattern" -- "*.rs"  # Filter by file pattern
```

### Branch Cleanup
```bash
gr prune                     # Dry-run: show merged branches that can be deleted
gr prune --execute           # Actually delete merged branches
gr prune --remote            # Also prune remote tracking refs
```

### Repository Management
```bash
gr repo list                         # List all repositories
gr repo add <url>                    # Add repo to workspace (updates manifest + clones)
gr repo add <url> --name my-repo     # Custom name in manifest
gr repo add <url> --path ./custom    # Custom local path
gr repo add <url> --branch develop   # Set default branch
gr repo add <url> --no-clone         # Only update manifest, don't clone
gr repo remove <name>                # Remove a repository
```

### Groups
```bash
gr group list                # List all groups and their repos
gr group add core backend    # Add backend to core group
gr group remove core backend # Remove backend from core group
gr sync --group core         # Scope operations to a group
```

### File Linking
```bash
gr link                      # Create/update all copyfile and linkfile entries
gr link --status             # Show link status (valid, broken, missing)
gr link --apply              # Apply/fix links
```

### Workspace Scripts
```bash
gr run --list                # List available scripts
gr run build                 # Run a named script
gr env                       # Show workspace environment variables
```

### Maintenance
```bash
gr gc                        # Garbage collect across repos
gr gc --aggressive           # More thorough gc (slower)
gr gc --dry-run              # Only report .git sizes
gr cherry-pick <sha>         # Cherry-pick commits across repos
gr cherry-pick --abort       # Abort in-progress cherry-pick
gr cherry-pick --continue    # Continue after conflict resolution
gr ci status                 # Check CI/CD pipeline status
gr ci list                   # List available CI pipelines
gr forall -c "cmd"           # Run command in each repo
```

### Griptrees (Multi-Branch Workspaces)

Griptrees let you work on multiple feature branches simultaneously without switching branches. Each griptree is a parallel workspace using git worktrees.

```bash
# Create a griptree for a feature branch
gr tree add feat/auth
# Creates: ../feat-auth/ with all repos on feat/auth branch

# List all griptrees
gr tree list

# Work in a griptree
cd ../feat-auth
gr status                    # Works just like main workspace
gr commit -m "changes"
gr push

# Return to griptree base branch
gr checkout --base

# Sync uses per-repo upstream when on griptree base branch
gr sync

# Rebase onto per-repo upstream
gr rebase --upstream

# Protect important griptrees
gr tree lock feat/auth       # Prevents accidental removal

# Cleanup when done
gr tree unlock feat/auth
gr tree remove feat/auth     # Removes worktrees, keeps branches
```

**Upstream Tracking:** Each griptree records per-repo upstream defaults in `.gitgrip/griptree.json`. Repos in the same workspace can track different upstream branches (e.g., `origin/main` vs `origin/dev`).

**Benefits:**
- No branch switching - work on multiple features in parallel
- Shared git objects - minimal disk usage, instant creation
- Independent working directories - separate dependencies and build artifacts
- Per-repo upstream tracking

### Benchmarking
```bash
gr bench                     # Run all benchmarks
gr bench --list              # List available benchmarks
gr bench manifest-load -n 10 # Run specific benchmark
```

### Manifest Operations
```bash
gr manifest schema                   # Show manifest schema (YAML)
gr manifest schema --format json     # JSON format
gr manifest schema --format markdown # Markdown format
gr manifest import <path>            # Import git-repo XML manifest
gr manifest sync                     # Re-sync from .repo/ manifest
```

## Workflow Rules

1. **Always run `gr sync` before starting new work**
2. **Always use `gr branch` to create branches** - Creates across all repos simultaneously
3. **Use `gr add`, `gr commit`, `gr push`** instead of raw git commands
4. **Always use pull requests** - No direct pushes to main
5. **Check `gr status` frequently** - Before and after operations

## Common Workflow Patterns

### Fixing Accidental Main Branch Commits

If you accidentally committed to `main` instead of a feature branch:

```bash
# Move the last commit to a new feature branch
gr branch feat/my-fix --move --repo <repo-name>
```

This creates a new branch at HEAD, resets the current branch to origin/main, and switches to the new branch.

### Single-Repository Operations

When you need to operate on just one repo:

```bash
# Create branch in specific repo only
gr branch feat/fix --repo tooling

# Push specific repo only
gr push --repo tooling
```

### PR Review Best Practices

Before merging a PR, always review it:

```bash
# Check PR status and CI
gr pr status
gr pr checks

# Review the diff
gr pr diff

# Wait for CI to pass before merging
gr pr merge
```

### Never Use Raw Git Commands

**Always use `gr` instead of raw `git` or `gh` commands.**

```bash
# ❌ WRONG - bypasses multi-repo coordination
gh pr create --title "..." --body "..."
git push -u origin <branch>

# ✅ CORRECT - includes manifest repo automatically
gr pr create -t "title" -b "body"
gr push -u
```

If you find yourself needing raw git commands, it reveals a gap in `gr`. Tell the user and ask if they want a GitHub issue created.

## Typical Workflow

```bash
# Starting new work
gr sync
gr status
gr branch feat/my-feature

# Making changes
# ... edit files ...
gr diff                             # Review changes
gr add .                            # Stage changes
gr commit -m "feat: my changes"     # Commit
gr push -u                          # Push with upstream

# Creating PR
gr pr create -t "feat: my feature"

# After PR approval
gr pr merge
gr sync
gr checkout main
gr prune --execute                  # Clean up merged branches
```

## Manifest Structure

The workspace manifest is at `.gitgrip/manifests/manifest.yaml`:

```yaml
version: 1

manifest:
  url: git@github.com:org/manifest.git
  default_branch: main

repos:
  repo-name:
    url: git@github.com:org/repo.git
    path: ./repo-name
    default_branch: main
    reference: false           # Set to true for read-only reference repos
    platform: github           # Optional: github, gitlab, azure, bitbucket

settings:
  pr:
    prefix: "[BRANCH] "
  merge_strategy: AllOrNothing  # AllOrNothing, Sequential, or Independent
```

### Reference Repositories

Mark repositories as `reference: true` to exclude them from branch and PR operations:

```yaml
repos:
  opencode:
    url: https://github.com/anomalyco/opencode.git
    path: ./ref/opencode
    reference: true  # Skipped in gr branch, gr pr create, etc.
```

Reference repos sync with `gr sync` and show in status with `[ref]` indicator, but are excluded from branch, checkout, push, and PR operations.

## Multi-Platform Support

gitgrip supports GitHub, GitLab, Azure DevOps, and Bitbucket. Platform is auto-detected from git URLs. Can be overridden in manifest with `platform:` config.

## Error Recovery

```bash
# Check what's happening
gr status

# If repos are out of sync
gr sync

# If on wrong branch
gr checkout correct-branch

# If links are broken
gr link --apply
```
