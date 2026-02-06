---
name: gitgrip
description: Multi-repository workflow using gitgrip (gr). Use for syncing repos, creating branches, linked PRs, and cross-repo operations.
allowed-tools: Bash(gr *), Bash(gitgrip *)
---

# gitgrip Multi-Repository Workflow

You are working in a multi-repository workspace managed by **gitgrip** (alias: `gr`). Always use `gr` commands for git operations across repos.

## Quick Reference

```bash
gr sync                      # Pull latest from all repos
gr status                    # Check status of all repos
gr branch feat/name          # Create branch across all repos
gr checkout feat/name        # Switch branch across all repos
gr checkout -b feat/name     # Create and switch to new branch
gr add .                     # Stage all changes
gr diff                      # Show diff across all repos
gr commit -m "message"       # Commit staged changes
gr push -u                   # Push with upstream tracking
gr pr create -t "title"      # Create linked PRs
gr pr status                 # Check PR status
gr pr merge                  # Merge all linked PRs
```

## Workflow Rules

1. **Always run `gr sync` before starting new work**
2. **Always use `gr branch` to create branches** - Creates across all repos
3. **Use `gr add`, `gr commit`, `gr push`** instead of raw git commands
4. **Always use pull requests** - No direct pushes to main
5. **Check `gr status` frequently** - Before and after operations

## Essential Commands

### Syncing
```bash
gr sync                      # Pull + process links + run hooks
gr sync --sequential         # Sync repos one at a time
gr sync --group core         # Sync only repos in 'core' group
```

### Branching
```bash
gr branch feat/my-feature              # Create branch across ALL repos
gr branch feat/x --repo tooling        # Create branch in specific repo
gr checkout feat/my-feature            # Switch branch across ALL repos
gr checkout -b new-branch              # Create and switch in one command
```

### Git Operations
```bash
gr add .                     # Stage all changes
gr diff                      # Show diff (colored)
gr diff --staged             # Show staged changes only
gr commit -m "message"       # Commit across repos
gr push -u                   # Push with upstream tracking
```

### Pull Requests
```bash
gr pr create -t "title"      # Create linked PRs
gr pr create -t "title" --push  # Push before creating
gr pr status                 # Check PR status
gr pr merge                  # Merge all linked PRs
gr pr merge -m squash        # Squash merge
gr pr merge --force          # Merge even if checks pending
```

### Groups
```bash
gr group list                # List all groups
gr group add core backend    # Add backend to core group
gr group remove core backend # Remove from group
gr sync --group core         # Sync only core repos
```

### Griptrees (Parallel Workspaces)
```bash
gr tree add feat/auth        # Create parallel workspace
gr tree list                 # List all griptrees
gr tree remove feat/auth     # Remove when done
```

## Typical Workflow

```bash
# Start work
gr sync
gr status
gr branch feat/my-feature

# Make changes
# ... edit files ...
gr diff
gr add .
gr commit -m "feat: my changes"
gr push -u

# Create and merge PR
gr pr create -t "feat: my feature"
gr pr merge
gr sync
gr checkout main
```

## Never Use Raw Git

Always use `gr` instead of `git` or `gh` commands:

```bash
# ❌ WRONG
git checkout -b feat/x
gh pr create --title "..."

# ✅ CORRECT
gr branch feat/x
gr pr create -t "title"
```

## Manifest Location

The workspace manifest is at `.gitgrip/manifests/manifest.yaml`. Use `gr manifest schema` to view the schema.
