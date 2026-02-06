# Manifest Reference

The manifest file (`manifest.yaml`) defines your multi-repository workspace configuration. It is typically located at `.gitgrip/manifests/manifest.yaml`.

## Quick Start

Minimal manifest:

```yaml
version: 1

repos:
  frontend:
    url: git@github.com:myorg/frontend.git
    path: ./frontend

  backend:
    url: git@github.com:myorg/backend.git
    path: ./backend
```

## Schema Version

```yaml
version: 1  # Required - manifest schema version
```

Currently only version `1` is supported.

## Manifest Self-Tracking

Track the manifest repository itself for inclusion in sync, branch, and push operations:

```yaml
manifest:
  url: git@github.com:myorg/workspace-manifest.git
  default_branch: main

  # Optional: files to copy from manifest to workspace root
  copyfile:
    - src: envsetup.sh
      dest: envsetup.sh

  # Optional: symlinks from workspace to manifest files
  linkfile:
    - src: CLAUDE.md
      dest: CLAUDE.md
```

When `manifest` is defined:
- `gr sync` syncs the manifest repo first
- `gr branch` creates branches in the manifest repo
- `gr push` pushes the manifest repo
- `gr diff` shows manifest changes

## Repository Definitions

Each repository is defined under `repos`:

```yaml
repos:
  # Key is the repository name used in gr commands
  frontend:
    # Git URL - SSH or HTTPS (required)
    url: git@github.com:myorg/frontend.git

    # Local path relative to workspace root (required)
    path: ./frontend

    # Default branch (optional, defaults to "main")
    default_branch: main

    # Groups for selective operations (optional)
    groups:
      - core
      - web

    # Mark as read-only reference repo (optional, defaults to false)
    reference: false

    # Platform override (optional, auto-detected from URL)
    platform:
      type: github
      base_url: https://github.mycompany.com  # For Enterprise

    # Files to copy after clone/sync (optional)
    copyfile:
      - src: .env.example
        dest: .env.local

    # Symlinks to create in workspace (optional)
    linkfile:
      - src: dist/cli
        dest: .bin/tool
```

### Required Fields

| Field | Type | Description |
|-------|------|-------------|
| `url` | string | Git clone URL (SSH or HTTPS) |
| `path` | string | Local path relative to workspace root |

### Optional Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `default_branch` | string | `main` | Branch to use for sync operations |
| `groups` | array | `[]` | Group names for filtering |
| `reference` | boolean | `false` | Read-only reference repository |
| `platform` | object | auto | Platform configuration |
| `copyfile` | array | - | Files to copy to workspace |
| `linkfile` | array | - | Symlinks to create |

## Groups

Groups allow selective operations on subsets of repositories:

```yaml
repos:
  frontend:
    url: git@github.com:myorg/frontend.git
    path: ./frontend
    groups:
      - core
      - web

  backend:
    url: git@github.com:myorg/backend.git
    path: ./backend
    groups:
      - core
      - api

  docs:
    url: git@github.com:myorg/docs.git
    path: ./docs
    groups:
      - docs
```

Use groups with commands:

```bash
gr sync --group core              # Sync only core repos
gr status --group web,api         # Status of web and api repos
gr branch feat/x --group core     # Branch only in core repos
```

Manage groups:

```bash
gr group list                     # List all groups
gr group add core shared-lib      # Add shared-lib to core group
gr group remove docs frontend     # Remove frontend from docs group
```

## Reference Repositories

Mark repositories as read-only references:

```yaml
repos:
  opencode:
    url: https://github.com/anthropics/opencode.git
    path: ./ref/opencode
    reference: true
```

Reference repos:
- Are synced with `gr sync`
- Are excluded from `gr branch`, `gr checkout`, `gr commit`, `gr push`
- Are excluded from `gr pr create/status/merge`
- Show `[ref]` indicator in `gr status`

Use for external dependencies, documentation repos, or code you don't modify.

## File Linking

### copyfile

Copy files from repository to workspace root after sync:

```yaml
repos:
  config:
    url: git@github.com:myorg/config.git
    path: ./config
    copyfile:
      - src: eslint.config.js
        dest: eslint.config.js
      - src: prettier.config.js
        dest: prettier.config.js
```

Files are copied (not linked) - changes to the copy don't affect the source.

### linkfile

Create symlinks from workspace to repository files:

```yaml
repos:
  tooling:
    url: git@github.com:myorg/tooling.git
    path: ./tooling
    linkfile:
      - src: bin/deploy
        dest: .bin/deploy
      - src: scripts/setup.sh
        dest: setup.sh
```

Symlinks point to the source - changes affect both locations.

### Link Commands

```bash
gr link                  # Create/update all links
gr link --status         # Show link status
gr link --clean          # Remove orphaned links
gr link --force          # Overwrite existing files
gr link --dry-run        # Preview changes
```

## Platform Configuration

gitgrip auto-detects platforms from URLs. Override for self-hosted instances:

```yaml
repos:
  internal:
    url: git@github.mycompany.com:team/repo.git
    path: ./internal
    platform:
      type: github
      base_url: https://github.mycompany.com
```

### Supported Platforms

| Type | Description |
|------|-------------|
| `github` | GitHub.com or GitHub Enterprise |
| `gitlab` | GitLab.com or self-hosted GitLab |
| `azure-devops` | Azure DevOps or Azure DevOps Server |
| `bitbucket` | Bitbucket Cloud or Bitbucket Server |

## Workspace Configuration

Global workspace settings:

```yaml
workspace:
  # Environment variables
  env:
    NODE_ENV: development
    WORKSPACE_NAME: myproject

  # Named scripts
  scripts:
    build:
      description: Build all packages
      command: npm run build

    test:
      description: Run all tests
      steps:
        - name: Lint
          command: npm run lint
        - name: Unit tests
          command: npm test

  # Lifecycle hooks
  hooks:
    post-sync:
      - command: npm install
        cwd: ./frontend
      - command: cargo build
        cwd: ./backend

    post-checkout:
      - command: ./scripts/setup.sh

  # CI/CD pipelines
  ci:
    pipelines:
      test:
        description: Run test suite
        steps:
          - name: Install
            command: npm ci
          - name: Test
            command: npm test
```

### Environment Variables

```yaml
workspace:
  env:
    NODE_ENV: development
    API_URL: http://localhost:3000
```

Access via `gr env` or in scripts.

### Scripts

```yaml
workspace:
  scripts:
    build:
      description: Build all packages
      command: pnpm -r build

    deploy:
      description: Deploy to production
      steps:
        - name: Build
          command: pnpm build
        - name: Push
          command: ./scripts/deploy.sh
          env:
            DEPLOY_ENV: production
```

Run with `gr run <name>`:

```bash
gr run --list            # List available scripts
gr run build             # Run build script
gr run build -- --watch  # Pass arguments
```

### Hooks

```yaml
workspace:
  hooks:
    post-sync:
      - command: npm install
        cwd: ./frontend

    post-checkout:
      - command: ./scripts/setup-env.sh
```

Hooks run automatically after their trigger event.

### CI/CD Pipelines

```yaml
workspace:
  ci:
    pipelines:
      test:
        description: Run test suite
        steps:
          - name: Install dependencies
            command: npm ci
          - name: Run tests
            command: npm test
            continue_on_error: false
          - name: Upload coverage
            command: npm run coverage:upload
            env:
              COVERAGE_TOKEN: ${COVERAGE_TOKEN}
```

Run with `gr ci`:

```bash
gr ci list               # List pipelines
gr ci run test           # Run test pipeline
gr ci status             # Show last run status
```

## Settings

Global tool behavior:

```yaml
settings:
  # PR title prefix
  pr_prefix: "[cross-repo]"

  # How to merge linked PRs
  merge_strategy: all-or-nothing
```

### Merge Strategies

| Strategy | Description |
|----------|-------------|
| `all-or-nothing` | All PRs must merge together or none do |
| `independent` | Each PR can be merged separately |

## Path Security

Paths must be relative and within the workspace:

- Paths cannot start with `..` or `/`
- Paths cannot contain `/../`
- Paths are validated to prevent directory traversal

```yaml
# Valid paths
path: ./frontend
path: apps/backend
path: packages/shared

# Invalid paths (rejected)
path: ../outside
path: /absolute/path
path: ./some/../../../escape
```

## Complete Example

```yaml
version: 1

manifest:
  url: git@github.com:myorg/workspace.git
  default_branch: main
  linkfile:
    - src: CLAUDE.md
      dest: CLAUDE.md

repos:
  frontend:
    url: git@github.com:myorg/frontend.git
    path: ./frontend
    default_branch: main
    groups:
      - core
      - web
    copyfile:
      - src: .env.example
        dest: .env.local

  backend:
    url: git@github.com:myorg/backend.git
    path: ./backend
    groups:
      - core
      - api

  shared:
    url: git@github.com:myorg/shared.git
    path: ./packages/shared
    groups:
      - core

  docs:
    url: git@github.com:myorg/docs.git
    path: ./docs
    reference: true

workspace:
  env:
    NODE_ENV: development

  scripts:
    build:
      description: Build all packages
      command: pnpm -r build

    test:
      description: Run all tests
      command: pnpm -r test

  hooks:
    post-sync:
      - command: pnpm install

settings:
  pr_prefix: "[multi-repo]"
  merge_strategy: all-or-nothing
```

## CLI Commands

View schema from CLI:

```bash
gr manifest schema              # YAML format
gr manifest schema --format json     # JSON format
gr manifest schema --format markdown # Markdown table
```

Import from git-repo XML:

```bash
gr manifest import              # Import default.xml
gr manifest sync                # Re-sync after repo changes
```
