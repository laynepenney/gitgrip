<p align="center">
  <img src="assets/banner.svg" alt="codi-repo" width="600">
</p>

<p align="center">
  <a href="#installation">Installation</a> •
  <a href="#quick-start">Quick Start</a> •
  <a href="#commands">Commands</a> •
  <a href="#manifest-format">Manifest</a>
</p>

---

Multi-repository orchestration CLI for unified PR workflows. Manage multiple related repositories as a single workspace with synchronized branches, linked pull requests, and atomic merges.

Inspired by Android's [repo tool](https://source.android.com/docs/setup/create/repo), `codi-repo` brings manifest-based multi-repo management to any project.

## Features

- **Manifest-based configuration** - Define all your repos in a single YAML file
- **Synchronized branches** - Create and checkout branches across all repos at once
- **Linked PRs** - Create pull requests that reference each other across repos
- **Atomic merges** - All-or-nothing merge strategy ensures repos stay in sync
- **Status dashboard** - See the state of all repos at a glance

## Installation

```bash
npm install -g codi-repo
```

Or with pnpm:

```bash
pnpm add -g codi-repo
```

## Quick Start

### 1. Create a manifest repository

Create a new repo to hold your workspace manifest (e.g., `my-workspace`), then add a `manifest.yaml`:

```yaml
version: 1

manifest:
  url: git@github.com:your-org/my-workspace.git

repos:
  frontend:
    url: git@github.com:your-org/frontend.git
    path: ./frontend
    default_branch: main

  backend:
    url: git@github.com:your-org/backend.git
    path: ./backend
    default_branch: main

  shared:
    url: git@github.com:your-org/shared-libs.git
    path: ./shared
    default_branch: main

settings:
  pr_prefix: "[cross-repo]"
  merge_strategy: all-or-nothing
```

### 2. Initialize a workspace

```bash
mkdir my-workspace && cd my-workspace
cr init git@github.com:your-org/my-workspace.git
```

This clones the manifest repo into `.codi-repo/manifests/` and all defined repositories.

### 3. Start working

```bash
# Check status of all repos
cr status

# Create a feature branch across all repos
cr branch feature/new-feature

# Make changes, commit in each repo, then create linked PRs
cr pr create --title "Add new feature"

# Sync all repos with latest from remote
cr sync
```

## Commands

### `cr init <manifest-url>`

Initialize a new workspace by cloning the manifest repository and all defined repos.

### `cr sync [options]`

Pull latest changes from the manifest and all repositories.

| Option | Description |
|--------|-------------|
| `--fetch` | Fetch only, don't merge |
| `--all` | Include repos not on default branch |

### `cr status [options]`

Show status of all repositories including branch, changes, and sync state. Also shows manifest repo status in a separate section.

### `cr branch [name]`

Create a new branch across all repositories, or list existing branches.

| Option | Description |
|--------|-------------|
| `--all` | Show branches from all repos |
| `--include-manifest` | Include manifest repo in branch operation |

The manifest repo is automatically included if it has uncommitted changes.

### `cr checkout <branch>`

Checkout a branch across all repositories.

### `cr pr`

Pull request management subcommands:

- `cr pr create` - Create linked PRs across repos with changes (including manifest if it has commits)
- `cr pr status` - Show status of linked PRs (including manifest PR)
- `cr pr merge` - Merge all linked PRs atomically (including manifest PR)

### `cr forall -c "<command>"`

Run a command in each repository (like AOSP's `repo forall`).

| Option | Description |
|--------|-------------|
| `-c, --command` | Command to run (required) |
| `-r, --repo <repos...>` | Only run in specific repos |
| `--include-manifest` | Include manifest repo |
| `--continue-on-error` | Continue if command fails in a repo |

Environment variables available in command:
- `REPO_NAME` - Repository name
- `REPO_PATH` - Absolute path to repo
- `REPO_URL` - Repository URL

Example:
```bash
# Show current branch in all repos
cr forall -c "git rev-parse --abbrev-ref HEAD"

# Rebase all repos onto main
cr forall -c "git rebase origin/main"

# Run only in specific repos
cr forall -c "npm test" --repo frontend --repo backend
```

## Manifest Format

The manifest file (`manifest.yaml`) defines your workspace:

```yaml
version: 1

# Optional: URL for the manifest repo itself (enables sync)
manifest:
  url: git@github.com:your-org/workspace.git

# Repository definitions
repos:
  repo-name:
    url: git@github.com:your-org/repo.git  # Git URL (SSH or HTTPS)
    path: ./local-path                      # Local path relative to workspace
    default_branch: main                    # Default branch name

# Global settings
settings:
  pr_prefix: "[cross-repo]"      # Prefix for linked PR titles
  merge_strategy: all-or-nothing  # or "independent"
```

### Merge Strategies

- **all-or-nothing** - All linked PRs must be approved before any can merge. Ensures repos stay in sync.
- **independent** - PRs can be merged independently. Use when repos don't have tight dependencies.

## Alias

You can use `cr` as a shorthand for `codi-repo`:

```bash
cr status
cr sync
cr branch feature/foo
```

## Requirements

- Node.js >= 18.0.0
- Git
- GitHub CLI (`gh`) for PR operations

## License

MIT
