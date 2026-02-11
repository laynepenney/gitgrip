# Issue #289: `gr agent` command — context discovery and workspace operations

## Context

When an AI agent starts a session, it needs to understand the workspace quickly. Currently it must read CLAUDE.md, run `gr status`, check links, and guess build systems. There's no single command that gives an agent everything it needs.

Issue #288 (already merged) added `RepoAgentConfig` and `WorkspaceAgentConfig` types to the manifest — the schema is ready but no command consumes it yet. Issue #289 adds the `gr agent` command family to surface this data.

**Pre-requisite:** PRs #300 (`gr verify`) and #301 (post-sync hooks) show as OPEN on GitHub despite earlier merge attempts. These need to be checked/re-merged before starting #289.

## Approach

Create a `gr agent` command with four subcommands following the `pr/` directory pattern:

```
gr agent context                    # Full workspace context (plain markdown for system prompts)
gr agent context --repo gitgrip     # Single repo context
gr agent context --json             # Structured JSON
gr agent build [repo]               # Run agent.build command per repo
gr agent test [repo]                # Run agent.test command per repo
gr agent verify [repo]              # Run build + test + lint for all configured repos
```

**Key design decisions:**
- Context output is **plain markdown** (no ANSI colors) — designed for system prompt injection
- `--json` produces structured JSON for programmatic consumption
- `build`/`test` execute shell commands from manifest `agent:` config via `sh -c`
- `verify` runs build + test + lint, reports summary, exits non-zero on failure
- Hook failures in verify are hard errors (unlike post-sync hooks which are warnings)

## Changes

### 1. `src/cli/commands/agent/mod.rs` — Module exports and JSON types

```rust
pub mod context;
pub mod build;
pub mod test;
pub mod verify;

// Re-export public functions
pub use context::run_agent_context;
pub use build::run_agent_build;
pub use test::run_agent_test;
pub use verify::run_agent_verify;
```

JSON structs for `--json` output:
- `AgentContextJson` — top-level: workspace, repos[], griptree?
- `WorkspaceContextJson` — root, description, conventions, workflows, scripts, env
- `RepoContextJson` — name, path, url, default_branch, current_branch, clean, exists, reference, groups, agent config
- `GriptreeContextJson` — branch, path, upstreams map

### 2. `src/cli/commands/agent/context.rs` — Main context command

**`run_agent_context(workspace_root, manifest, repo_filter, json)`**

Steps:
1. Get all repos via `filter_repos(manifest, workspace_root, None, None, true)` (include reference)
2. Get git status for each via `get_repo_status()` from `src/git/status.rs`
3. Load griptree config via `GriptreeConfig::load_from_workspace()`
4. Extract workspace agent config, scripts, env from manifest

Human-readable output format (markdown):
```
# Workspace: /path/to/workspace
Description here

## Conventions
- Convention 1
- Convention 2

## Repos
- **gitgrip** (rust) — Multi-repo workflow tool [build: cargo build] [test: cargo test]
  Branch: main | Status: clean
- **codi** (typescript) — AI coding CLI [build: pnpm build] [test: pnpm test]
  Branch: feat/x | Status: 2 modified

## Griptree: feat/branch
Upstreams: gitgrip→origin/main, codi→origin/main
```

When `--repo` is specified: still show workspace section, but filter repos list to just the named repo.

### 3. `src/cli/commands/agent/build.rs` — Build subcommand

**`run_agent_build(workspace_root, manifest, repo_filter)`**

For each repo (or filtered repo): read `repo.agent.build`, execute via `sh -c` in repo dir. Exit non-zero on first failure. Skip repos without `agent.build` (unless user named a specific repo — then error).

### 4. `src/cli/commands/agent/test.rs` — Test subcommand

Same pattern as build but reads `repo.agent.test`.

### 5. `src/cli/commands/agent/verify.rs` — Verify subcommand

**`run_agent_verify(workspace_root, manifest, repo_filter)`**

For each repo with agent config: run build, test, lint (any that are defined). Continue through failures. Report summary at end. Exit non-zero if any failed.

### 6. `src/main.rs` — Register command

Add `AgentCommands` enum:
```rust
#[derive(Subcommand)]
enum AgentCommands {
    Context { #[arg(long)] repo: Option<String>, #[arg(long)] json: bool },
    Build { repo: Option<String> },
    Test { repo: Option<String> },
    Verify { repo: Option<String> },
}
```

Add to `Commands` enum:
```rust
Agent { #[command(subcommand)] action: AgentCommands },
```

Dispatch matches the `Pr`/`Tree` pattern.

### 7. `src/cli/commands/mod.rs` — Register module

Add `pub mod agent;`

### 8. Tests — `tests/test_agent.rs`

New test file with WorkspaceBuilder fixtures:
- `test_agent_context_shows_workspace_info` — verify markdown output contains workspace description
- `test_agent_context_json_output` — verify JSON deserializes correctly
- `test_agent_context_repo_filter` — verify `--repo` filters to single repo
- `test_agent_context_no_agent_config` — verify graceful output with no agent section
- `test_agent_build_runs_command` — add `agent.build: "echo ok"`, verify runs
- `test_agent_build_fails_on_error` — add `agent.build: "exit 1"`, verify error
- `test_agent_test_runs_command` — same pattern for test
- `test_agent_verify_summary` — verify runs all checks and reports summary

## Files to create/modify

| File | Action | Change |
|------|--------|--------|
| `src/cli/commands/agent/mod.rs` | CREATE | Module exports, JSON structs |
| `src/cli/commands/agent/context.rs` | CREATE | `run_agent_context` |
| `src/cli/commands/agent/build.rs` | CREATE | `run_agent_build` |
| `src/cli/commands/agent/test.rs` | CREATE | `run_agent_test` |
| `src/cli/commands/agent/verify.rs` | CREATE | `run_agent_verify` |
| `src/cli/commands/mod.rs` | MODIFY | Add `pub mod agent;` |
| `src/main.rs` | MODIFY | Add `AgentCommands` enum, `Agent` variant, dispatch |
| `tests/test_agent.rs` | CREATE | Integration tests |

## Existing utilities to reuse

| Utility | File | Purpose |
|---------|------|---------|
| `RepoAgentConfig` | `src/core/manifest.rs:115-130` | Per-repo agent metadata |
| `WorkspaceAgentConfig` | `src/core/manifest.rs:132-141` | Workspace agent metadata |
| `RepoInfo.agent` | `src/core/repo.rs:38` | Already populated from manifest |
| `filter_repos()` | `src/core/repo.rs:190-213` | Repo filtering with group/name support |
| `get_repo_status()` / `get_all_repo_status()` | `src/git/status.rs:204-261` | Git status per repo |
| `RepoStatus` | `src/git/status.rs:33-56` | Branch, clean, staged, modified, ahead/behind |
| `GriptreeConfig::load_from_workspace()` | `src/core/griptree.rs:102` | Detect griptree + upstream mappings |
| `Output::header/success/error/info/kv` | `src/cli/output.rs` | Terminal display formatting |
| Shell execution pattern | `src/cli/commands/run.rs:95-107` | `sh -c` command execution |
| Subcommand enum pattern | `src/main.rs:308-415` | `PrCommands`, `TreeCommands` |

## Verification

1. `cargo build` succeeds
2. `cargo test` — all existing tests pass + new agent tests
3. `cargo clippy` clean
4. `cargo fmt` clean
5. `gr agent context` — shows workspace and repo information
6. `gr agent context --json` — valid JSON output
7. `gr agent context --repo gitgrip` — shows only gitgrip repo
8. `gr agent build gitgrip` — runs cargo build in gitgrip dir (if agent config exists in manifest)
9. `gr agent verify` — runs all configured checks
