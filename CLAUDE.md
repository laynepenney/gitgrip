# gitgrip Development Guide

**git a grip** - Multi-repo workflow tool

## Build & Test

```bash
pnpm install          # Install dependencies
pnpm build            # Compile TypeScript
pnpm test             # Run tests
pnpm lint             # Lint code
```

## Git Workflow

**IMPORTANT:** Never push directly to main. Never use raw `git` commands. Always use `gr` for all operations.

### Branch Strategy

**Main Branch (`main`)**
- Production-ready code
- Protected with PR requirements
- All PRs must target `main`
- Use `gr sync` to stay current (not `git pull`)

**Feature Branches (`feat/*`, `fix/*`, `chore/*`)**
- All development happens here
- Short-lived, deleted after merge

### Standard Workflow

```bash
# Start new work
gr sync                              # Pull latest from all repos
gr status                            # Verify clean state
gr branch feat/my-feature            # Create branch across repos

# Make changes...
gr diff                              # Review changes
gr add .                             # Stage changes across repos
gr commit -m "feat: description"     # Commit across repos
gr push -u                           # Push with upstream tracking

# Create PR
gr pr create -t "feat: description" --push

# After PR merged
gr sync                              # Pull latest and cleanup
gr checkout main                     # Switch back to main
```

### IMPORTANT: Never Use Raw Git

All git operations must go through `gr`. There is no exception.

```
❌ WRONG:
   git checkout -b feat/x
   git add . && git commit -m "msg" && git push
   gh pr create --title "msg"

✅ CORRECT:
   gr branch feat/x
   gr add . && gr commit -m "msg" && gr push -u
   gr pr create -t "msg" --push
```

`gr` manages all repos and the manifest together. Using raw `git` or `gh` bypasses multi-repo coordination and will miss the manifest repo.

### PR Review Process

**IMPORTANT: Never merge a PR without reviewing it first.** Always review your own PRs before merging.

**For AI agents (Claude, Codi, etc.):** Do NOT immediately merge after creating a PR. Always:
1. Create the PR with `gr pr create -t "title"`
2. Run `pnpm build && pnpm test` to verify nothing is broken
3. Check PR status with `gr pr status`
4. **Wait for GitHub checks to pass** - use `gh pr checks <number>` to verify
5. Review the diff with `gh pr diff <number>` (for each repo with changes)
6. Check feature completeness (see checklist below)
7. Only then merge with `gr pr merge` (if all checks pass and no issues found)

**CRITICAL: GitHub checks must pass before merging.** If checks are pending, wait. If checks fail, fix the issues first.

**Feature completeness checklist:**
- [ ] New command registered in `src/index.ts`
- [ ] Types added to `src/types.ts` if needed
- [ ] Tests added for new functionality

**CRITICAL: Run benchmarks for performance-related changes:**

When modifying `push.ts`, `sync.ts`, `commit.ts`, `add.ts`, `diff.ts`, or `git.ts`:

```bash
# Run workspace benchmarks (requires gitgrip workspace)
gr bench -n 10

# Run isolated microbenchmarks (runs in CI)
pnpm bench
```

Compare results before/after your changes. Document significant improvements or regressions in the PR description.

**CRITICAL: Update all documentation when changing commands/API:**
- [ ] `CLAUDE.md` - Development guide and command reference
- [ ] `README.md` - User-facing documentation
- [ ] `CONTRIBUTING.md` - If workflow changes
- [ ] `CHANGELOG.md` - Add entry for the change
- [ ] `.claude/skills/gitgrip/SKILL.md` - Claude Code skill definition

Forgetting to update docs creates drift between code and documentation. Always check these files when adding/modifying commands.

### Release Process

When creating a new release:

1. **Update version numbers:**
   - [ ] `package.json` - version field
   - [ ] `src/index.ts` - `.version()` in Commander setup
   - [ ] `CHANGELOG.md` - Change `[Unreleased]` to `[x.y.z] - YYYY-MM-DD`

2. **Create and merge release PR:**
   ```bash
   gr branch release/vX.Y.Z
   # Make version changes
   gr add . && gr commit -m "chore: release vX.Y.Z"
   gr push -u && gr pr create -t "chore: release vX.Y.Z"
   gr pr merge
   ```

3. **Create GitHub release:**
   ```bash
   gh release create vX.Y.Z --title "vX.Y.Z" --notes "..."
   ```
   This triggers GitHub Actions to automatically publish to npm.

4. **CRITICAL: Update Homebrew formula:**
   - [ ] Update `homebrew-tap/Formula/gitgrip.rb` with new version and SHA256
   - [ ] Test with `brew install --build-from-source ./Formula/gitgrip.rb`
   - [ ] Commit and push to homebrew-tap repo

Forgetting to update Homebrew means users on `brew upgrade` won't get the new version.

## Project Structure

```
src/
├── index.ts              # CLI entry point (Commander.js)
├── types.ts              # TypeScript interfaces
├── commands/             # CLI command implementations
│   ├── init.ts           # gr init
│   ├── migrate.ts        # gr migrate
│   ├── sync.ts           # gr sync
│   ├── status.ts         # gr status
│   ├── branch.ts         # gr branch
│   ├── checkout.ts       # gr checkout
│   ├── add.ts            # gr add
│   ├── diff.ts           # gr diff
│   ├── commit.ts         # gr commit
│   ├── push.ts           # gr push
│   ├── link.ts           # gr link
│   ├── run.ts            # gr run
│   ├── env.ts            # gr env
│   ├── bench.ts          # gr bench
│   ├── forall.ts         # gr forall
│   ├── tree.ts           # gr tree (worktree-based workspaces)
│   └── pr/               # PR subcommands
│       ├── index.ts
│       ├── create.ts
│       ├── status.ts
│       └── merge.ts
└── lib/                  # Core libraries
    ├── manifest.ts       # Manifest parsing and validation
    ├── git.ts            # Git operations
    ├── github.ts         # GitHub backward compatibility (deprecated)
    ├── linker.ts         # PR-to-manifest linking
    ├── files.ts          # copyfile/linkfile operations
    ├── hooks.ts          # Post-sync/checkout hooks
    ├── scripts.ts        # Workspace script runner
    ├── timing.ts         # Benchmarking & timing utilities
    └── platform/         # Multi-platform hosting support
        ├── types.ts      # Platform interfaces (HostingPlatform, etc.)
        ├── index.ts      # Platform detection and factory
        ├── github.ts     # GitHub adapter
        ├── gitlab.ts     # GitLab adapter
        └── azure-devops.ts # Azure DevOps adapter
```

## Key Concepts

### Manifest
Workspace configuration in `.gitgrip/manifests/manifest.yaml`:
- `repos`: Repository definitions with URL, path, default_branch
- `manifest`: Self-tracking for the manifest repo itself
- `workspace`: Scripts, hooks, and environment variables
- `settings`: PR prefix, merge strategy


### Commands
All commands use `gr` (or `gitgrip`):
- `gr init <url>` - Initialize workspace from manifest
- `gr sync` - Pull all repos + process links + run hooks
- `gr status` - Show repo and manifest status
- `gr branch/checkout` - Branch operations across all repos
- `gr add` - Stage changes across all repos
- `gr diff` - Show diff across all repos
- `gr commit` - Commit staged changes across all repos
- `gr push` - Push current branch in all repos
- `gr pr create/status/merge` - Linked PR workflow
- `gr repo add <url>` - Add a new repository to workspace
- `gr link` - Manage copyfile/linkfile entries
- `gr run` - Execute workspace scripts
- `gr env` - Show workspace environment variables
- `gr bench` - Run benchmarks
- `gr forall -c "cmd"` - Run command in each repo
- `gr tree add/list/remove` - Manage worktree-based multi-branch workspaces

### Trees (Multi-Branch Workspaces)

Trees allow you to work on multiple branches simultaneously without switching branches. Each tree is a parallel workspace using git worktrees.

```bash
# Create a tree for a feature branch
gr tree add feat/auth

# This creates a directory structure:
# ../feat-auth/
#   ├── codi/           # worktree of main/codi on feat/auth
#   ├── codi-private/   # worktree of main/codi-private on feat/auth
#   └── .gitgrip/manifests/  # worktree of manifest on feat/auth

# List all trees
gr tree list

# Lock a tree to prevent accidental removal
gr tree lock feat/auth

# Remove a tree (removes worktrees, not branches)
gr tree remove feat/auth
```

**Benefits:**
- No branch switching - work on multiple features in parallel
- Shared git objects - worktrees share `.git/objects` with main
- Faster than cloning - worktree creation is nearly instant

**Limitations:**
- Branch exclusivity - can't checkout same branch in two worktrees
- Separate node_modules - each worktree needs own dependencies

### File Linking
- `copyfile`: Copy file from repo to workspace
- `linkfile`: Create symlink from workspace to repo
- Path validation prevents directory traversal

### Multi-Platform Support

gitgrip supports multiple hosting platforms:
- **GitHub** (github.com and GitHub Enterprise)
- **GitLab** (gitlab.com and self-hosted)
- **Azure DevOps** (dev.azure.com and Azure DevOps Server)

**Platform Detection:**
- Platform is auto-detected from git URLs
- Can be overridden in manifest with `platform:` config

**Example mixed-platform manifest:**
```yaml
repos:
  frontend:
    url: git@github.com:org/frontend.git
    path: ./frontend
  backend:
    url: git@gitlab.com:org/backend.git
    path: ./backend
  infra:
    url: https://dev.azure.com/org/project/_git/infra
    path: ./infra
```

**Platform Architecture:**
- `HostingPlatform` interface defines all platform operations
- Each platform has an adapter in `src/lib/platform/`
- Use `getPlatformAdapter(type, config)` to get platform instance
- Platform adapters handle: PR create/merge/status, reviews, status checks, URL parsing

**Adding a New Platform:**
1. Create adapter in `src/lib/platform/newplatform.ts`
2. Implement `HostingPlatform` interface
3. Add detection logic in `src/lib/platform/index.ts`
4. Add tests in `src/lib/__tests__/platform.test.ts`

## Testing

```bash
pnpm test              # Run all tests
pnpm test:watch        # Watch mode
pnpm test -- --grep "manifest"  # Filter tests
```

Test files are in `src/lib/__tests__/`.

## Adding a New Command

1. Create `src/commands/mycommand.ts`
2. Export the handler function
3. Register in `src/index.ts` with Commander
4. Add types to `src/types.ts` if needed

## Code Style

- TypeScript strict mode
- Async/await for all I/O
- Use `chalk` for colored output
- Use `ora` for spinners
- Validate manifest schema in `lib/manifest.ts`

## Continuous Improvement

gitgrip is self-improving. When using `gr` commands, capture any friction or ideas in:

```
./IMPROVEMENTS.md
```

**Do NOT create GitHub issues directly.** Instead:
1. Add observations to IMPROVEMENTS.md under "Pending Review"
2. Prompt the user: "I added [observation] to IMPROVEMENTS.md. Want me to create an issue?"
3. Only create issues after user approval

### CRITICAL: Document When Falling Back to Raw Commands

**If you ever use raw `git` or `gh` commands, you MUST immediately:**

1. Add an entry to `IMPROVEMENTS.md` explaining why `gr` couldn't handle the use case
2. Tell the user about the friction point

This is mandatory. Every workaround reveals a gap in `gr` that should be fixed.
