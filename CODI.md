# codi-repo Development Guide

Multi-repository orchestration CLI for unified PR workflows.

## Build & Test

```bash
pnpm install          # Install dependencies
pnpm build            # Compile TypeScript
pnpm test             # Run tests
pnpm lint             # Lint code
```

## Git Workflow

**IMPORTANT: Never push directly to main.** Always use feature branches and pull requests.

### Branch Strategy

**Main Branch (`main`)**
- Production-ready code
- Protected with PR requirements
- All PRs must target `main`
- Use `git pull origin main --rebase` to stay current

**Feature Branches (`feat/*`, `fix/*`, `chore/*`)**
- All development happens here
- Short-lived, deleted after merge
- Always rebase from `origin/main`, never merge

### Rebase vs Merge

**✅ Use REBASE** (correct):
```bash
git rebase origin/main           # Keeps history linear
git push --force-with-lease      # Safe force-push after rebase
```

**❌ DO NOT Use MERGE** (incorrect):
```bash
git merge origin/main            # Creates unnecessary merge commits
```

### Standard Workflow

```bash
# Start new work
cr sync                              # Pull latest from all repos
cr branch feat/my-feature            # Create branch across repos

# Make changes...
cr add .                             # Stage changes across repos
cr commit -m "feat: description"     # Commit across repos
cr push -u                           # Push with upstream tracking

# Create PR
cr pr create -t "feat: description"  # Create linked PRs

# After PR merged
cr sync                              # Pull latest and cleanup
cr checkout main                     # Switch back to main
```

### PR Review Process

**IMPORTANT: Never merge a PR without reviewing it first.** Always review your own PRs before merging. This creates a traceable review history and catches mistakes before they reach main.

**For AI agents (Claude, Codi, etc.):** Do NOT immediately merge after creating a PR. Always:
1. Create the PR with `cr pr create -t "title"`
2. Run `pnpm build && pnpm test` to verify nothing is broken
3. Check PR status with `cr pr status`
4. Review the diff with `gh pr diff <number>` (for each repo with changes)
5. Check feature completeness (see checklist below)
6. Add a review comment documenting what was checked
7. Only then merge with `cr pr merge` (if all tests pass and no issues found)

**Full Process:**

1. **Create the PR** with clear title and description:
   ```bash
   cr pr create -t "feat: description" --push
   ```
2. **Run build and tests** to verify nothing is broken:
   ```bash
   pnpm build && pnpm test
   ```
   If tests fail, fix the issues before proceeding.
3. **Check PR status** across all repos:
   ```bash
   cr pr status
   ```
4. **Review the diff** thoroughly using `gh pr diff <number>` for each repo
5. **Check feature completeness** (for new features/commands):
   - [ ] New command registered in `src/index.ts`
   - [ ] Types added to `src/types.ts` if needed
   - [ ] Tests added for new functionality
   - [ ] `CLAUDE.md` updated with documentation
   - [ ] `README.md` updated if user-facing
6. **Document the review** - add a comment listing what was verified:
   ```bash
   gh pr comment <number> --body "## Self-Review
   - ✅ Build passes
   - ✅ All tests pass
   - ✅ Diff reviewed
   - ✅ Feature completeness checked
   - No issues found. Ready to merge."
   ```
7. **If issues found**, fix in a new commit (don't amend if already pushed)
8. **For issues to address later**, create a GitHub issue:
   ```bash
   gh issue create --title "Title" --body "Description"
   ```
9. **Merge only after review is complete and all tests pass**:
   ```bash
   cr pr merge
   ```

This ensures:
- All review feedback is tracked in the PR history
- Future contributors can understand why changes were made
- AI agents don't blindly merge without verification
- **No broken code reaches main** - tests must pass before merge

## Project Structure

```
src/
├── index.ts              # CLI entry point (Commander.js)
├── types.ts              # TypeScript interfaces
├── commands/             # CLI command implementations
│   ├── init.ts           # cr init
│   ├── migrate.ts        # cr migrate (legacy format conversion)
│   ├── sync.ts           # cr sync
│   ├── status.ts         # cr status (includes manifest section)
│   ├── branch.ts         # cr branch (supports --include-manifest)
│   ├── checkout.ts       # cr checkout
│   ├── add.ts            # cr add (includes manifest)
│   ├── diff.ts           # cr diff (includes manifest)
│   ├── commit.ts         # cr commit (includes manifest)
│   ├── push.ts           # cr push (includes manifest)
│   ├── link.ts           # cr link
│   ├── run.ts            # cr run
│   ├── env.ts            # cr env
│   ├── bench.ts          # cr bench
│   └── pr/               # PR subcommands
│       ├── index.ts
│       ├── create.ts     # Includes manifest PR
│       ├── status.ts     # Includes manifest PR
│       └── merge.ts      # Includes manifest PR
└── lib/                  # Core libraries
    ├── manifest.ts       # Manifest parsing, validation, getManifestRepoInfo()
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
Workspace configuration in `.codi-repo/manifests/manifest.yaml`:
- `repos`: Repository definitions with URL, path, default_branch
- `manifest`: Self-tracking for the manifest repo itself
- `workspace`: Scripts, hooks, and environment variables
- `settings`: PR prefix, merge strategy

### Commands
All commands use `cr` alias:
- `cr init <url>` - Initialize workspace from manifest
- `cr sync` - Pull all repos + process links + run hooks
- `cr status` - Show repo and manifest status
- `cr branch/checkout` - Branch operations across all repos
- `cr add` - Stage changes across all repos (including manifest)
- `cr diff` - Show diff across all repos (including manifest)
- `cr commit` - Commit staged changes across all repos (including manifest)
- `cr push` - Push current branch in all repos (including manifest)
- `cr pr create/status/merge` - Linked PR workflow (including manifest PRs)
- `cr link` - Manage copyfile/linkfile entries
- `cr run` - Execute workspace scripts
- `cr env` - Show workspace environment variables
- `cr bench` - Run benchmarks

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

codi-repo is self-improving. When using `cr` commands, capture any friction or ideas in:

```
./IMPROVEMENTS.md
```

**Do NOT create GitHub issues directly.** Instead:
1. Add observations to IMPROVEMENTS.md under "Pending Review"
2. Prompt the user: "I added [observation] to IMPROVEMENTS.md. Want me to create an issue?"
3. Only create issues after user approval
