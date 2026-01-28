# Manifest Schema Reference

Complete reference for `manifest.yaml` configuration.

## Top-Level Fields

| Field | Required | Description |
|-------|----------|-------------|
| `version` | Yes | Schema version (currently `1`) |
| `manifest` | No | Configuration for the manifest repo itself |
| `repos` | Yes | Map of repository configurations |
| `settings` | No | Global settings |
| `workspace` | No | Workspace scripts, hooks, and environment |

## Manifest Section

Self-tracking configuration for the manifest repository:

```yaml
manifest:
  url: git@github.com:org/manifest-repo.git
  default_branch: main
  copyfile:
    - src: file-in-manifest
      dest: destination-in-workspace
  linkfile:
    - src: file-in-manifest
      dest: symlink-in-workspace
```

## Repository Configuration

```yaml
repos:
  repo-name:                    # Key used as display name
    url: git@github.com:org/repo.git  # Required: Git URL
    path: ./local-path          # Required: Local path relative to workspace
    default_branch: main        # Optional: Default branch (default: main)
    copyfile:                   # Optional: Files to copy
      - src: relative/to/repo
        dest: relative/to/workspace
    linkfile:                   # Optional: Symlinks to create
      - src: relative/to/repo
        dest: relative/to/workspace
```

## Settings

```yaml
settings:
  pr_prefix: "[cross-repo]"     # Prefix for linked PR titles
  merge_strategy: all-or-nothing  # or "independent"
```

## Workspace Configuration

### Environment Variables

```yaml
workspace:
  env:
    NODE_ENV: development
    DEBUG: "true"
```

### Scripts

Single command:
```yaml
workspace:
  scripts:
    build:
      description: "Build all packages"
      command: "pnpm -r build"
      cwd: "./"  # Optional working directory
```

Multi-step:
```yaml
workspace:
  scripts:
    build-all:
      description: "Build packages in order"
      steps:
        - name: "Build core"
          command: "pnpm build"
          cwd: "./core"
        - name: "Build app"
          command: "pnpm build"
          cwd: "./app"
```

### Hooks

```yaml
workspace:
  hooks:
    post-sync:
      - command: "pnpm install"
        cwd: "./repo-name"
      - command: "pnpm build"
        cwd: "./repo-name"
    post-checkout:
      - command: "pnpm install"
```

## File Linking

### copyfile
Copies a file from repo to workspace. Creates a new file (not linked).

### linkfile
Creates a symbolic link from workspace to repo. Changes in either location reflect in both.

### Path Security
- Paths cannot escape their boundaries (no `../` escaping)
- Source paths are relative to the repo
- Destination paths are relative to workspace root
