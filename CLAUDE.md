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
4. Review the diff with `gh pr diff <number>` (for each repo with changes)
5. Check feature completeness (see checklist below)
6. Add a review comment documenting what was checked
7. Only then merge with `gr pr merge` (if all tests pass and no issues found)

**Feature completeness checklist:**
- [ ] New command registered in `src/index.ts`
- [ ] Types added to `src/types.ts` if needed
- [ ] Tests added for new functionality
- [ ] `CLAUDE.md` updated with documentation
- [ ] `README.md` updated if user-facing

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
│   └── pr/               # PR subcommands
│       ├── index.ts
│       ├── create.ts
│       ├── status.ts
│       └── merge.ts
└── lib/                  # Core libraries
    ├── manifest.ts       # Manifest parsing and validation
    ├── git.ts            # Git operations
    ├── github.ts         # GitHub CLI wrapper
    ├── linker.ts         # PR-to-manifest linking
    ├── files.ts          # copyfile/linkfile operations
    ├── hooks.ts          # Post-sync/checkout hooks
    ├── scripts.ts        # Workspace script runner
    └── timing.ts         # Benchmarking & timing utilities
```

## Key Concepts

### Manifest
Workspace configuration in `.gitgrip/manifests/manifest.yaml`:
- `repos`: Repository definitions with URL, path, default_branch
- `manifest`: Self-tracking for the manifest repo itself
- `workspace`: Scripts, hooks, and environment variables
- `settings`: PR prefix, merge strategy

Note: Legacy `.codi-repo/` directories are also supported for backward compatibility.

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
- `gr link` - Manage copyfile/linkfile entries
- `gr run` - Execute workspace scripts
- `gr env` - Show workspace environment variables
- `gr bench` - Run benchmarks
- `gr forall -c "cmd"` - Run command in each repo

### File Linking
- `copyfile`: Copy file from repo to workspace
- `linkfile`: Create symlink from workspace to repo
- Path validation prevents directory traversal

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
