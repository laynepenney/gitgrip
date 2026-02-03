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

### Initializing Workspaces
```bash
# From manifest URL
gr init <manifest-url>               # Clone manifest and all repos

# From existing local directories
gr init --from-dirs                  # Auto-scan current dir for git repos
gr init --from-dirs --dirs ./a ./b   # Scan specific directories only
gr init --from-dirs --interactive    # Preview YAML and edit before saving
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

# Protect important griptrees
gr tree lock feat/auth       # Prevents accidental removal

# Cleanup when done
gr tree unlock feat/auth
gr tree remove feat/auth     # Removes worktrees, keeps branches
```

**Benefits:**
- No branch switching - work on multiple features in parallel
- Shared git objects - minimal disk usage, instant creation
- Independent working directories - separate node_modules, build artifacts

**Options:**
```bash
gr tree add feat/x --path ./custom-path  # Custom location
gr tree remove feat/x --force            # Remove even if locked
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

# Commit in specific repo only  
gr commit -m "fix: something" --repo tooling

# Push specific repo only
gr push --repo tooling
```

### PR Review Best Practices

Before merging a PR, always review it:

```bash
# Check PR status and CI
gr pr status
gh pr checks <number>

# Review the diff
gh pr diff <number>

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

If you find yourself needing raw git commands, document the friction point in `IMPROVEMENTS.md` so it can be fixed.

## Contributing Improvements

When you encounter friction or missing features while using `gr`:

1. Add an entry to `./IMPROVEMENTS.md` under "Pending Review"
2. Document what you expected vs what happened
3. Include the raw commands you had to use as a workaround
4. Ask the user if they want to create a GitHub issue

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
    reference: false           # Set to true for read-only reference repos
    platform: github           # Optional: github, gitlab, azure
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

settings:
  pr:
    prefix: "[BRANCH] "        # PR title prefix with branch name placeholder
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

Reference repos are still synced and shown in status with `[ref]` indicator, but:
- Not included in `gr branch` operations
- Not included in `gr checkout` operations  
- Not included in `gr pr create/status/merge`

Use this for reference implementations, documentation repos, or any repo you don't plan to modify.

### Complete Manifest Schema

```yaml
version: 1                    # Manifest format version

manifest:                     # Self-reference for manifest repo
  url: <url>                  # Git URL for manifest repo
  default_branch: <branch>    # Default branch name (e.g., main)
  linkfile:                   # Files to link from manifest to workspace root
    - src: <path>             # Source relative to manifest repo
      dest: <path>            # Destination relative to workspace root

repos:                        # Repository definitions
  <repo-name>:                # Unique repo identifier
    url: <git-url>            # Git clone URL
    path: <relative-path>     # Local path relative to workspace root
    default_branch: <branch>  # Default branch (e.g., main, master)
    reference: <bool>         # Read-only reference repo (default: false)
    platform: <platform>      # Hosting platform: github, gitlab, azure
    copyfile:                 # Files to copy into workspace
      - src: <path>           # Source relative to repo
        dest: <path>          # Destination relative to workspace root
    linkfile:                 # Symlinks to create in workspace
      - src: <path>           # Source relative to repo
        dest: <path>          # Destination relative to workspace root

workspace:                    # Workspace-wide configuration
  env:                        # Environment variables
    <VAR_NAME>: <value>
  scripts:                    # Named executable scripts
    <script-name>:
      description: <text>     # Human-readable description
      command: <shell-cmd>    # Command to execute
  hooks:                      # Lifecycle hooks
    post-sync:                # Run after gr sync completes
      - command: <cmd>        # Shell command
        cwd: <path>           # Working directory (relative to workspace)

settings:                     # Tool behavior settings
  pr:
    prefix: <string>          # PR title prefix pattern
  merge_strategy: <strategy>  # How to merge multi-repo PRs:
                              # - AllOrNothing: All PRs must merge together
                              # - Sequential: Merge in order, stop on failure
                              # - Independent: Merge each PR separately

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
