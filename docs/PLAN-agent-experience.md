# Agent Experience Improvements for gitgrip

## Problem Statement

AI coding agents (Claude Code, Codex, OpenCode, Cursor, etc.) are increasingly primary users of multi-repo tools like gitgrip. Current `gr` commands are designed for human-readable terminal output, leading to:

- **Silent failures** agents can't detect (e.g., `gr pr merge --force` reports success but PR stays open)
- **Text parsing** instead of structured data (agents guess outcomes from colored terminal output)
- **Manual multi-step workflows** agents must orchestrate step-by-step (releases, PR-merge-cleanup)
- **Missing context discovery** — agents need to understand a workspace quickly but there's no single command for that
- **Per-agent-tool maintenance burden** — CLAUDE.md, .opencode/skill/, .codex/skills/, .cursorrules all need separate linkfile entries

## Scope

This plan covers three tiers:

1. **Foundation** — JSON output, reliability fixes (agent can trust tool output)
2. **Workflow** — PR wait, post-sync hooks, release automation (agent can orchestrate without raw `gh`)
3. **Agent-native** — Manifest agent context, `gr agent` command, multi-tool context generation (workspace is agent-aware)

---

## Tier 1: Foundation

### 1.1 JSON output on all commands

**Issue:** Agents parse human-readable text to determine outcomes. This is fragile and error-prone.

**Solution:** Add `--json` flag to every command that produces output. Return structured JSON with:
- `success: bool`
- `action: string` (what happened)
- `details: object` (command-specific structured data)
- `warnings: string[]`
- `errors: string[]`

**Priority commands** (agents use these most):

| Command | JSON shape |
|---------|-----------|
| `gr status --json` | Already exists, extend with link status |
| `gr sync --json` | `{repos: [{name, action, commits}], links: {applied, errors}, composefiles: n}` |
| `gr pr create --json` | `{prs: [{repo, number, url}]}` |
| `gr pr merge --json` | `{merged: [{repo, pr, sha}], failed: [{repo, pr, reason}], skipped: [repo]}` |
| `gr pr checks --json` | `{repos: [{repo, pr, checks: [{name, status, url}]}]}` |
| `gr branch --json` | `{created: [repo], skipped: [repo], failed: [{repo, reason}]}` |
| `gr push --json` | `{pushed: [repo], nothing: [repo], failed: [{repo, reason}]}` |
| `gr commit --json` | `{committed: [{repo, sha}], skipped: [repo]}` |
| `gr link --json` | `{links: [{type, src, dest, status}], valid: n, broken: n}` |

**Implementation:**
- Add `--json` flag to `Cli` struct in `main.rs`
- Pass through to each command handler
- Each command returns a `serde_json::Value` when JSON mode is active
- Suppress all `Output::*` calls in JSON mode
- Print JSON to stdout at the end

**Effort:** Medium (touch every command, but pattern is repetitive)

### 1.2 Fix silent merge failures

**Issue:** `gr pr merge --force` reports "Successfully merged 1 PR(s)" even when the GitHub API merge call fails or the PR remains open. An agent proceeds assuming success.

**Solution:**
- After each `gh` merge API call, verify the PR state is actually `MERGED`
- If verification fails, report it as a failure (not success)
- In JSON mode, include `verified: bool` in the response

**Effort:** Small (localized to `src/cli/commands/pr/merge.rs`)

### 1.3 Verification commands

**Issue:** Agents need boolean pass/fail answers, not text to interpret.

**Solution:** `gr verify` subcommand:

```bash
gr verify --clean              # Exit 0 if no uncommitted changes anywhere
gr verify --links              # Exit 0 if all links valid
gr verify --pr-merged <number> # Exit 0 if PR is merged
gr verify --checks <number>    # Exit 0 if all checks pass
gr verify --on-branch <name>   # Exit 0 if all repos on this branch
```

All commands: exit 0 = pass, exit 1 = fail. `--json` returns `{pass: bool, details: ...}`.

**Effort:** Small-medium (mostly wrappers around existing logic)

---

## Tier 2: Workflow Automation

### 2.1 `gr pr merge --wait`

**Issue:** Agents must poll `gh pr checks --watch` manually, then call merge separately. This is the most common raw `gh` fallback.

**Solution:**

```bash
gr pr merge --wait              # Wait for checks, then merge
gr pr merge --wait --timeout 600  # Timeout after 10 minutes
gr pr merge --auto              # Enable GitHub auto-merge (already exists)
```

`--wait` behavior:
1. Poll check status every 15 seconds
2. If all checks pass → merge
3. If any check fails → abort with error
4. If timeout → abort with error
5. Show progress in non-JSON mode, structured updates in JSON mode

**Effort:** Medium (new polling loop, integrate with existing merge logic)

### 2.2 `gr pr checks` improvements

**Issue:** No way to wait for or filter checks from `gr`.

**Solution:**

```bash
gr pr checks                   # Show check status (exists)
gr pr checks --wait            # Block until all complete
gr pr checks --required-only   # Only show required checks
gr pr checks --json            # Structured output
```

**Effort:** Small (extend existing checks command)

### 2.3 Post-sync hooks

**Issue:** After `gr sync` pulls new code, agents often need to rebuild. Currently no way to automate this.

**Solution:** Add `hooks.post-sync` to manifest:

```yaml
workspace:
  hooks:
    post-sync:
      - name: build-gitgrip
        command: cargo build --release
        repos: [gitgrip]
        condition: changed  # Only run if repo had changes
      - name: build-codi
        command: pnpm build
        repos: [codi, codi-private]
        condition: changed
```

Behavior:
- Runs after repos are synced, links applied
- `condition: changed` — only runs if the repo received new commits
- `condition: always` — runs every sync
- Failures are warnings (don't fail sync)
- `--no-hooks` to skip

**Effort:** Medium (new hook system, manifest schema change)

### 2.4 `gr release` workflow

**Issue:** Release is 8+ manual steps that agents must orchestrate perfectly.

**Solution:** Built-in release workflow, configurable per-workspace:

```bash
gr release v0.12.4 --notes "Description of changes"
```

Default steps:
1. Bump version in detected config files (Cargo.toml, package.json)
2. Update CHANGELOG.md (insert new section)
3. Build (`cargo build --release` / `pnpm build`)
4. Create branch `release/vX.Y.Z`
5. Commit, push, create PR
6. Wait for CI
7. Merge PR
8. Create GitHub release with tag

Configurable via manifest:

```yaml
workspace:
  scripts:
    release:
      steps:
        - bump-version
        - update-changelog
        - build
        - create-pr
        - wait-ci
        - merge
        - create-release
        - update-homebrew  # Custom step
      version_files:
        - Cargo.toml
      changelog: CHANGELOG.md
      homebrew:
        repo: laynepenney/homebrew-tap
        formula: Formula/gitgrip.rb
```

**Effort:** Large (new command, multi-step orchestration, configurable)

---

## Tier 3: Agent-Native Workspace

### 3.1 Agent context in manifest

**Issue:** Agent build/test/lint commands are not discoverable from the manifest. Agents must guess or read CLAUDE.md.

**Solution:** Add `agent` section to repo definitions:

```yaml
repos:
  gitgrip:
    url: https://github.com/laynepenney/gitgrip.git
    path: ./gitgrip
    default_branch: main
    agent:
      description: "Multi-repo workflow tool (Rust)"
      build: cargo build --release
      test: cargo test
      lint: cargo clippy
      format: cargo fmt
      language: rust

  codi:
    url: https://github.com/laynepenney/codi.git
    path: ./codi
    default_branch: main
    agent:
      description: "AI coding wingman CLI (TypeScript)"
      build: pnpm build
      test: pnpm test
      lint: pnpm lint
      language: typescript
```

Workspace-level agent config:

```yaml
workspace:
  agent:
    description: "Codi AI coding wingman workspace"
    conventions:
      - "Never use raw git commands, always use gr"
      - "Never push directly to main"
      - "All PRs require CI to pass before merge"
    workflows:
      release: "gr release"
      pr-cleanup: "gr checkout --base && gr sync && gr prune --execute"
```

**Effort:** Medium (manifest schema extension, parsing, validation)

### 3.2 `gr agent` command

**Issue:** When an agent starts a session, it needs to understand the workspace quickly. Currently it must read CLAUDE.md, run `gr status`, check links, etc.

**Solution:**

```bash
gr agent context                    # Full workspace context dump
gr agent context --repo gitgrip     # Single repo context
gr agent build [repo]               # Build repo(s) using manifest config
gr agent test [repo]                # Test repo(s)
gr agent verify                     # Run all verification checks
```

`gr agent context` output (designed for system prompt injection):

```
# Workspace: codi-workspace
Codi AI coding wingman workspace

## Repos (7 active + 6 reference)
- gitgrip (Rust) — Multi-repo workflow tool [build: cargo build --release] [test: cargo test]
- codi (TypeScript) — AI coding wingman CLI [build: pnpm build] [test: pnpm test]
- codi-rs (Rust) — Codi Rust implementation [build: cargo build] [test: cargo test]
...

## Conventions
- Never use raw git commands, always use gr
- Never push directly to main
- All PRs require CI to pass before merge

## Current State
- Branch: main
- Status: clean (0 changes)
- Links: 13/13 valid
- Open issues: 27
- Open PRs: 8
```

With `--json` for structured consumption.

**Effort:** Medium (new command, reads from manifest agent config + live state)

### 3.3 Griptree context for agents

**Issue:** When an agent starts in a griptree, it needs to know what branch, what's the upstream, what changed.

**Solution:** Extend `gr agent context` and `gr tree` for griptree awareness:

```bash
gr tree context
# Branch: feat/sync-apply-links
# Upstream: origin/main (3 ahead, 0 behind)
# Modified repos: gitgrip (2 files)
# Last commit: "feat: apply linkfiles/copyfiles during gr sync"
# Related PRs: #280 (MERGED)
```

**Effort:** Small (extend existing griptree info)

### 3.4 Multi-agent-tool context generation

**Issue:** Every new AI coding tool requires its own context file format (CLAUDE.md, .cursorrules, .opencode/skill/, .codex/skills/, AGENTS.md). Each needs separate linkfile/composefile entries in the manifest. Adding a new tool means updating every gripspace.

**Solution:** Single-source context with multi-format output:

```yaml
workspace:
  agent:
    context_source: WORKSPACE_CONTEXT.md    # One source of truth
    targets:
      - format: claude
        dest: CLAUDE.md
        compose_with: [CLAUDE_PRIVATE.md]   # Optional additional content
      - format: opencode
        dest: .opencode/skill/{repo}/
      - format: codex
        dest: .codex/skills/{repo}/
      - format: cursor
        dest: .cursorrules
      - format: raw
        dest: AGENTS.md
```

When `gr sync` runs (or `gr agent generate-context`):
1. Read the source context
2. For each target, transform to the tool's expected format
3. Write/link to destination

Adding support for a new tool = one manifest line, not N linkfiles across gripspaces.

**Effort:** Large (new context generation system, format adapters)

---

## Implementation Priority

| Phase | Features | Issues | Why |
|-------|----------|--------|-----|
| **Phase 1** | 1.1 JSON output, 1.2 Fix silent failures, 1.3 Verify commands | Foundation | Agents can't build on unreliable tools |
| **Phase 2** | 2.1 PR merge --wait, 2.2 PR checks improvements | Workflow | Eliminates most raw `gh` fallbacks |
| **Phase 3** | 2.3 Post-sync hooks, 3.1 Agent manifest context | Integration | Workspace becomes agent-aware |
| **Phase 4** | 3.2 `gr agent` command, 3.3 Griptree context | Discovery | Agents can self-orient |
| **Phase 5** | 2.4 Release workflow, 3.4 Multi-tool context | Automation | Full agent-native workflow |

## Labels

Create a new label: `area/agent` — Agent experience and AI tool integration

## Milestone

Consider a new milestone: `Agent Experience` — Making gitgrip agent-native

---

## Success Criteria

An AI agent should be able to:
1. Start a session and understand the workspace with one command (`gr agent context`)
2. Complete a full feature cycle (branch → code → test → PR → merge → cleanup) using only `gr` commands
3. Never need to parse human-readable text to determine outcomes (`--json`)
4. Trust that command output matches reality (no silent failures)
5. Automate releases without manual multi-step orchestration
6. Work in any supported agent tool without per-tool manifest maintenance
