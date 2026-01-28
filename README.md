# gitgrip

**git a grip** - Multi-repo workflow tool

Manage multiple related repositories as a single workspace with synchronized branches, linked pull requests, and atomic merges.

Inspired by Android's [repo tool](https://source.android.com/docs/setup/create/repo), gitgrip brings manifest-based multi-repo management to any project.

## Features

- **Manifest-based configuration** - Define all your repos in a single YAML file
- **Synchronized branches** - Create and checkout branches across all repos at once
- **Linked PRs** - Create pull requests that reference each other across repos
- **Atomic merges** - All-or-nothing merge strategy ensures repos stay in sync
- **Status dashboard** - See the state of all repos at a glance

## Installation

```bash
npm install -g gitgrip
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
gr init git@github.com:your-org/my-workspace.git
```

This clones the manifest repo into `.gitgrip/manifests/` and all defined repositories.

### 3. Start working

```bash
# Check status of all repos
gr status

# Create a feature branch across all repos
gr branch feature/new-feature

# Make changes, commit in each repo, then create linked PRs
gr pr create --title "Add new feature"

# Sync all repos with latest from remote
gr sync
```

## Commands

| Command | Description |
|---------|-------------|
| `gr init <url>` | Initialize workspace from manifest repo |
| `gr sync` | Pull latest from all repos |
| `gr status` | Show status of all repos |
| `gr branch [name]` | Create or list branches |
| `gr checkout <branch>` | Checkout branch across repos |
| `gr add [files]` | Stage changes across repos |
| `gr diff` | Show diff across repos |
| `gr commit -m "msg"` | Commit across repos |
| `gr push` | Push across repos |
| `gr pr create` | Create linked PRs |
| `gr pr status` | Show PR status |
| `gr pr merge` | Merge all linked PRs |
| `gr forall -c "cmd"` | Run command in each repo |

### Command Details

#### `gr init <manifest-url>`

Initialize a new workspace by cloning the manifest repository and all defined repos.

#### `gr sync [options]`

Pull latest changes from the manifest and all repositories.

| Option | Description |
|--------|-------------|
| `--fetch` | Fetch only, don't merge |
| `--no-link` | Skip processing copyfile/linkfile entries |
| `--no-hooks` | Skip running post-sync hooks |

#### `gr status`

Show status of all repositories including branch, changes, and sync state.

#### `gr branch [name]`

Create a new branch across all repositories, or list existing branches.

| Option | Description |
|--------|-------------|
| `-r, --repo <repos...>` | Only operate on specific repos |
| `--include-manifest` | Include manifest repo |

#### `gr pr create`

Create linked PRs across repos with changes.

| Option | Description |
|--------|-------------|
| `-t, --title <title>` | PR title |
| `-b, --body <body>` | PR body |
| `-d, --draft` | Create as draft |
| `--push` | Push branches first |

#### `gr pr merge`

Merge all linked PRs atomically.

| Option | Description |
|--------|-------------|
| `-m, --method <method>` | merge, squash, or rebase |
| `--no-delete-branch` | Keep branches after merge |
| `-f, --force` | Merge even if checks pending |

#### `gr forall -c "<command>"`

Run a command in each repository (like AOSP's `repo forall`).

| Option | Description |
|--------|-------------|
| `-c, --command` | Command to run (required) |
| `-r, --repo <repos...>` | Only run in specific repos |
| `--include-manifest` | Include manifest repo |
| `--continue-on-error` | Continue if command fails |

Environment variables available in command:
- `REPO_NAME` - Repository name
- `REPO_PATH` - Absolute path to repo
- `REPO_URL` - Repository URL

## Manifest Format

The manifest file (`manifest.yaml`) defines your workspace:

```yaml
version: 1

manifest:
  url: git@github.com:your-org/workspace.git

repos:
  repo-name:
    url: git@github.com:your-org/repo.git
    path: ./local-path
    default_branch: main

settings:
  pr_prefix: "[cross-repo]"
  merge_strategy: all-or-nothing
```

### Merge Strategies

- **all-or-nothing** - All linked PRs must be approved before any can merge
- **independent** - PRs can be merged independently

## Shorthand

Use `gr` as the primary command:

```bash
gr status
gr sync
gr branch feature/foo
```

The long form `gitgrip` also works.

## Requirements

- Node.js >= 18.0.0
- Git
- GitHub CLI (`gh`) for PR operations

## License

MIT
