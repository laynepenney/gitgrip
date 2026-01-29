---
name: gitgrip
description: Multi-repository workflow using gitgrip (gr). Use this when working with multiple repos, creating branches across repos, syncing repos, creating linked pull requests, or any cross-repo operations.
allowed-tools: Bash(gr *), Bash(gitgrip *), Bash(node */gitgrip/dist/index.js *)
---

# gitgrip Multi-Repository Workflow

You are working in a multi-repository workspace managed by **gitgrip** (alias: `gr`). Always use `gr` commands for git operations across repos.

## Essential Commands

### Check Status First
```bash
gr status                    # Always check status before operations
```

### Syncing
```bash
gr sync                      # Pull latest from all repos + process links + run hooks
gr sync --fetch              # Fetch only (no merge)
gr sync --no-link            # Skip file linking
gr sync --no-hooks           # Skip post-sync hooks
```

### Branching
```bash
gr branch feat/my-feature              # Create branch across ALL repos
gr branch feat/x --repo tooling        # Create branch in specific repo only
gr branch feat/x --repo a --repo b     # Create branch in multiple specific repos
gr checkout feat/my-feature            # Switch branch across ALL repos
gr checkout -b new-branch              # Create and switch to new branch
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
gr diff --stat               # Show diffstat summary
gr diff --name-only          # Show only filenames

# Commit
gr commit -m "message"       # Commit staged changes in all repos
gr commit -a -m "message"    # Stage all and commit

# Push
gr push                      # Push all repos with commits ahead
gr push -u                   # Set upstream tracking
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
gr pr status --json

# 3. Merge all linked PRs together
gr pr merge                  # Default merge
gr pr merge -m squash        # Squash merge
gr pr merge -m rebase        # Rebase merge
gr pr merge --no-delete-branch  # Keep branches after merge
```

### File Linking
```bash
gr link                      # Create/update all copyfile and linkfile entries
gr link --status             # Show link status (valid, broken, missing)
gr link --clean              # Remove orphaned links
gr link --force              # Overwrite existing files/links
gr link --dry-run            # Preview changes
```

### Adding Repositories
```bash
gr repo add <url>                    # Add repo to workspace (updates manifest + clones)
gr repo add <url> --name my-repo     # Custom name in manifest
gr repo add <url> --path ./custom    # Custom local path
gr repo add <url> --branch develop   # Set default branch
gr repo add <url> --no-clone         # Only update manifest, don't clone
```

### Workspace Scripts
```bash
gr run --list                # List available scripts
gr run build                 # Run a named script
gr run build -- --verbose    # Pass arguments to script
gr env                       # Show workspace environment variables
```

### Benchmarking & Timing
```bash
gr status --timing           # Show timing breakdown for any command
gr bench                     # Run all benchmarks
gr bench --list              # List available benchmarks
gr bench manifest-load -n 10 # Run specific benchmark
```

## Workflow Rules

1. **Always run `gr sync` before starting new work**
2. **Always use `gr branch` to create branches** - Creates across all repos simultaneously
3. **Use `gr add`, `gr commit`, `gr push`** instead of raw git commands
4. **Always use pull requests** - No direct pushes to main
5. **Check `gr status` frequently** - Before and after operations

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
```

## Manifest Structure

The workspace manifest is at `.gitgrip/manifests/manifest.yaml`:

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

## Error Recovery

If you encounter issues:

```bash
# Check what's happening
gr status

# If repos are out of sync
gr sync

# If on wrong branch
gr checkout correct-branch

# If links are broken
gr link --force
```
