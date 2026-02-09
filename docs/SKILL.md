---
name: gitgrip
description: Multi-repository workflow using gitgrip (gr). Use for syncing repos, creating branches, linked PRs, and cross-repo operations.
allowed-tools: Bash(gr *), Bash(gitgrip *)
---

# gitgrip Multi-Repository Workflow

You are working in a multi-repository workspace managed by **gitgrip** (alias: `gr`). Always use `gr` commands for git operations across repos.

## Quick Reference

```bash
gr sync                      # Pull latest from all repos (parallel)
gr status                    # Check status of all repos
gr branch feat/name          # Create branch across all repos
gr checkout feat/name        # Switch branch across all repos
gr checkout -b feat/name     # Create and switch to new branch
gr checkout --base           # Return to griptree base branch
gr tree return               # Return + sync + optional prune flow
gr add .                     # Stage all changes
gr diff                      # Show diff across all repos
gr commit -m "message"       # Commit staged changes
gr push -u                   # Push with upstream tracking
gr pull                      # Pull latest changes
gr pr create -t "title"      # Create linked PRs
gr pr status                 # Check PR status
gr pr merge                  # Merge all linked PRs
gr prune                     # Clean up merged branches (dry-run)
gr prune --execute           # Actually delete merged branches
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
gr sync                      # Pull + process links + run hooks (parallel)
gr sync --sequential         # Sync repos one at a time
gr sync --group core         # Sync only repos in 'core' group
gr sync --reset-refs         # Hard-reset reference repos to upstream
```

### Branching
```bash
gr branch feat/my-feature              # Create branch across ALL repos
gr branch feat/x --repo tooling        # Create branch in specific repo
gr checkout feat/my-feature            # Switch branch across ALL repos
gr checkout -b new-branch              # Create and switch in one command
gr checkout --base                     # Return to griptree base branch
gr branch -d old-branch                # Delete branch across repos
gr branch --move feat/new              # Move commits to new branch
```

### Git Operations
```bash
gr add .                     # Stage all changes
gr diff                      # Show diff (colored)
gr diff --staged             # Show staged changes only
gr commit -m "message"       # Commit across repos
gr push -u                   # Push with upstream tracking
gr pull                      # Pull latest across repos
gr pull --rebase             # Pull with rebase
```

### Rebasing
```bash
gr rebase origin/main        # Rebase onto specific target
gr rebase --upstream         # Rebase onto per-repo upstream (griptree-aware)
gr rebase --abort            # Abort in-progress rebase
gr rebase --continue         # Continue after conflict resolution
```

### Pull Requests
```bash
gr pr create -t "title"      # Create linked PRs
gr pr create -t "title" --push  # Push before creating
gr pr create -t "title" --draft # Create as draft
gr pr status                 # Check PR status
gr pr checks                 # Check CI status
gr pr diff                   # Show PR diff
gr pr merge                  # Merge all linked PRs
gr pr merge -m squash        # Squash merge
gr pr merge --force          # Merge even if checks pending
gr pr merge --update         # Update branch from base if behind, then merge
gr pr merge --auto           # Enable auto-merge (merges when checks pass)
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
gr prune                     # Dry-run: show merged branches
gr prune --execute           # Actually delete merged branches
gr prune --remote            # Also prune remote tracking refs
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
gr tree lock feat/auth       # Prevent accidental removal
gr tree unlock feat/auth     # Allow removal
gr tree remove feat/auth     # Remove when done
gr checkout --base           # Return to griptree base branch
gr tree return --prune-current --prune-remote # Return + cleanup
```

**Upstream Tracking:** Each griptree records per-repo upstream defaults. `gr tree add` sets tracking for the griptree branch, and `gr sync`/`gr rebase --upstream` use this mapping automatically when on the griptree base branch.

### Maintenance
```bash
gr gc                        # Garbage collect across repos
gr gc --aggressive           # More thorough gc
gr gc --dry-run              # Only report .git sizes
gr cherry-pick <sha>         # Cherry-pick across repos
gr ci status                 # Check CI/CD pipeline status
```

### Repository Management
```bash
gr repo list                 # List all repositories
gr repo add <url>            # Add repo to workspace
gr repo add <url> --name x   # Custom name in manifest
gr repo remove <name>        # Remove a repository
```

### Workspace Operations
```bash
gr run --list                # List available scripts
gr run build                 # Run a named script
gr env                       # Show workspace environment variables
gr link --status             # Show file link status
gr link --apply              # Apply/fix file links
gr forall -c "cmd"           # Run command in each repo
gr manifest schema           # Show manifest schema
gr bench                     # Run benchmarks
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
# Wait for CI, review
gr pr merge
gr sync
gr checkout --base
gr prune --execute           # Clean up merged branches
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

The canonical workspace manifest is `.gitgrip/spaces/main/gripspace.yml` (legacy `.gitgrip/manifests/manifest.yaml` is still supported). Use `gr manifest schema` to view the schema.

## Multi-Platform Support

gitgrip supports GitHub, GitLab, Azure DevOps, and Bitbucket. Platform is auto-detected from git URLs. Can be overridden in manifest with `platform:` config.
