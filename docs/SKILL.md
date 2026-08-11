---
name: gitgrip
description: Manage a multi-repository workspace with gitgrip (`gr`). Use when a meta-project coordinates nested Git repositories, or when work needs synchronized branches, workspace-wide status and sync, linked pull requests, isolated working copies, or an atomic multi-repo merge.
---

# gitgrip

Copy this file to `.claude/skills/gitgrip/SKILL.md` in your project, or `~/.claude/skills/gitgrip/SKILL.md` to have it in every project.

Use gitgrip when one meta-project contains several related repositories. Each nested repository keeps its own Git database and remote history. The root gripspace coordinates them as one workspace.

Prefer `gr` for any action that needs a workspace-wide view or must stay consistent across repositories. Before using an unfamiliar option, run `gr <command> --help`. Command output is the authority for the installed version.

## Install and verify

Choose one installation route:

```bash
# Homebrew on macOS or Linux
brew tap synapt-dev/tap
brew install synapt-dev/tap/gitgrip

# Rust toolchain
cargo install gitgrip
```

Pre-built binaries for supported platforms are available from [GitHub Releases](https://github.com/synapt-dev/grip/releases).

Verify the installation before creating a workspace:

```bash
gr --version
gr --help
```

## Start a gripspace

Initialize from a repository containing `gripspace.yml`:

```bash
gr init https://github.com/acme/product-workspace.git
cd product-workspace
gr status
```

Or adopt repositories that already exist beneath the current directory:

```bash
gr init --from-dirs --interactive
gr status
```

The manifest defines which repositories belong to the gripspace, where they live, which branches they target, and which workspace operations are available. Read the [manifest reference](https://github.com/synapt-dev/grip/blob/main/docs/MANIFEST.md) when creating or changing that contract.

## Daily workflow

### 1. Inspect the whole workspace

Run this before changing branches, syncing, or publishing work:

```bash
gr status
```

Use machine-readable output when another tool will consume the result:

```bash
gr --json status
```

### 2. Sync registered repositories

```bash
gr sync
```

Narrow the operation when needed:

```bash
gr sync --repo frontend
gr sync --group services
gr sync --sequential
```

Run `gr status` first. Do not reach for `--force` until the local changes it may affect are understood.

### 3. Add or inspect repositories

```bash
gr repo list
gr repo add https://github.com/acme/payments.git --path services/payments
```

`gr repo add` updates the workspace contract and brings the repository into the coordinated workspace. Check `gr repo add --help` before relying on version-specific materialization options.

### 4. Create a synchronized branch

```bash
gr branch feat/invoice-export
```

To move every participating repository to an existing branch:

```bash
gr checkout feat/invoice-export
```

Use `--repo` when the change intentionally belongs to only part of the gripspace.

### 5. Review changes across repositories

```bash
gr diff
gr diff --repo frontend
```

### 6. Stage changes

```bash
gr add .
gr add src/ tests/ --repo backend
```

Treat `gr add .` as workspace-wide. Use `--repo` when only one repository should be staged, then confirm with `gr status`.

### 7. Commit the staged repositories

```bash
gr commit -m "feat: export invoices"
```

Only repositories with staged changes receive a commit. Review the workspace status again after committing.

### 8. Push participating branches

```bash
gr push
```

Use the repository and branch summary printed by `gr` as the publication receipt.

### 9. Create linked pull requests

Preview first when the base branch or participating repositories are uncertain:

```bash
gr pr create --dry-run --title "Add invoice export"
```

Then create and, if necessary, push in the same operation:

```bash
gr pr create --push --title "Add invoice export"
```

Override the configured target only when the workspace contract requires it:

```bash
gr pr create --base dev --title "Add invoice export"
```

### 10. Inspect linked pull requests

```bash
gr pr status
gr pr checks
gr pr diff
```

Resolve failures in the repository that owns them. Re-run the workspace-wide checks before merging.

### 11. Merge the linked change

```bash
gr pr merge --method merge
```

`gr pr merge` resolves the pull requests owned by the current branch. It does not take a pull request number. It checks approval, CI, and mergeability before changing any remote.

Name the merge method explicitly when history shape matters. Do not waive readiness checks merely to make a blocked merge proceed. Diagnose approval, CI, and mergeability separately.

### 12. Work in an isolated copy

Create another working copy without disturbing the current one:

```bash
gr tree add feat/invoice-export
gr tree list
```

Move into the path printed by `gr tree add`, work normally, and return after the branch merges:

```bash
gr tree return
```

Treat the isolated-copy contract as stable and its storage mechanism as version-specific. Let the installed command choose how the copy is materialized.

## Newcomer traps

### Confirm what the workspace actually owns

gitgrip coordinates repositories registered in the manifest. An unregistered directory beneath the root is not automatically part of workspace-wide status, sync, commit, or PR operations. Use `gr repo list` as the source of truth.

### Separate sync from destructive recovery

`gr sync` normally preserves local work. `gr sync --force`, `gr sync --reset-refs`, and `gr prune --execute` have stronger consequences. Inspect status and run dry modes where available before using them. `gr prune` without `--execute` is the safe preview.

### Read the merge receipt, not only the exit code

A linked merge is a set of repository-specific operations. Read the resolved repositories, target branches, merge method, and any waived gates printed by `gr pr merge`. A successful command is not evidence that it targeted the branch or history shape you intended.

## Go deeper

- [gitgrip product page](https://synapt.dev/grip/)
- [README and complete command overview](https://github.com/synapt-dev/grip#readme)
- [Documentation directory](https://github.com/synapt-dev/grip/tree/main/docs)
- [Manifest reference](https://github.com/synapt-dev/grip/blob/main/docs/MANIFEST.md)
- [Platform and authentication capabilities](https://github.com/synapt-dev/grip/blob/main/docs/PLATFORM_CAPABILITIES.md)

Keep this skill at the workflow-contract level. Consult the linked documentation and `gr <command> --help` for platform setup, full manifest schema, MCP integration, automation, and version-specific implementation details.
