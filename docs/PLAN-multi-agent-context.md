# Issue #290: Multi-agent-tool context generation

## Context

Every AI coding tool has its own context file format (CLAUDE.md, `.opencode/skill/`, `.codex/skills/`, `.cursorrules`). The current workspace manages 13+ linkfile entries across gripspaces just to distribute context to different tools. Adding support for a new tool means editing every gripspace manifest with new linkfile entries. There's also duplication: `.opencode/` and `.codex/` skill files are identical copies.

Issue #290 adds single-source context generation: define context once, generate for all tools automatically during `gr sync`.

## CLI Interface

```bash
gr agent generate-context              # Generate context files for all configured targets
gr agent generate-context --dry-run    # Show what would be generated
gr sync                                # Also runs context generation (before linkfiles)
```

## Manifest Config

```yaml
workspace:
  agent:
    description: "Multi-repo workspace for Codi"
    conventions: [...]
    context_source: WORKSPACE_CONTEXT.md    # Source file in manifest repo
    targets:
      - format: claude
        dest: CLAUDE.md
        compose_with: [CLAUDE_PRIVATE.md]   # Additional files to append
      - format: opencode
        dest: .opencode/skill/{repo}/SKILL.md   # {repo} = per-repo generation
      - format: codex
        dest: .codex/skills/{repo}/SKILL.md
      - format: cursor
        dest: .cursorrules
      - format: raw
        dest: AGENTS.md
```

## Approach

Add `context_source` and `targets` fields to `WorkspaceAgentConfig`. Implement format adapters that transform context for each AI tool. Integrate generation into `gr sync` pipeline (after composefiles, before linkfiles). Add `gr agent generate-context` subcommand for manual generation.

**Key design decisions:**
- **Workspace-level targets** (no `{repo}` in dest): generate a single file from `context_source` + optional `compose_with`
- **Per-repo targets** (`{repo}` in dest): generate one skill file per repo using `agent.description`, `agent.language`, `agent.build`, `agent.test` from manifest
- Format adapters are simple transforms, not a full template engine
- `context_source` resolved via existing `resolve_file_source()` (supports gripspace sources)
- Generation runs during `gr sync` by default; can be run standalone with `gr agent generate-context`

## Changes

### 1. `src/core/manifest.rs` — Extend agent config types

Add to `WorkspaceAgentConfig`:
```rust
pub context_source: Option<String>,  // Source file path (supports gripspace: prefix)
pub targets: Option<Vec<AgentContextTarget>>,
```

New type:
```rust
pub struct AgentContextTarget {
    pub format: String,             // claude, opencode, codex, cursor, raw
    pub dest: String,               // Destination path ({repo} placeholder for per-repo)
    pub compose_with: Option<Vec<String>>,  // Additional files to append
}
```

### 2. `src/cli/commands/agent/generate.rs` — Context generation (NEW)

**`pub fn run_agent_generate_context(workspace_root, manifest, dry_run) -> Result<()>`**

Steps:
1. Read `workspace.agent.context_source` (resolve via `resolve_file_source()`)
2. For each target:
   - If dest contains `{repo}`: per-repo generation (iterate repos with agent config)
   - Else: workspace-level generation (single file from source)
3. Apply format adapter to content
4. Write to dest (creating parent dirs as needed)

**Format adapters:**
- `raw`: Pass-through, just copy the content
- `claude`: Wrap source content. For `{repo}` targets: add YAML frontmatter (`name`, `description`, `allowed-tools` based on `agent.language`)
- `opencode`: For `{repo}` targets: add simple frontmatter (`name`, `description`). For workspace: pass-through
- `codex`: Same as opencode (reuse adapter)
- `cursor`: Strip markdown headings to create .cursorrules format (summarize key rules)

**Per-repo skill generation:**
For each repo with `agent` config, generate a SKILL.md containing:
```markdown
---
name: {repo_name}
description: {agent.description}
---
# {repo_name}

Language: {agent.language}
Build: {agent.build}
Test: {agent.test}
Lint: {agent.lint}
```

### 3. `src/cli/commands/agent/mod.rs` — Register new subcommand

Add `pub mod generate;` and `pub use generate::run_agent_generate_context;`

### 4. `src/main.rs` — Add GenerateContext to AgentCommands

```rust
AgentCommands::GenerateContext {
    #[arg(long)]
    dry_run: bool,
}
```

### 5. `src/cli/commands/sync.rs` — Integrate into sync pipeline

After composefiles are processed, before linkfiles, call:
```rust
if let Some(agent_config) = manifest.workspace.as_ref().and_then(|w| w.agent.as_ref()) {
    if agent_config.targets.is_some() {
        agent::run_agent_generate_context(workspace_root, manifest, false)?;
    }
}
```

### 6. `tests/test_agent.rs` — Add tests

- `test_agent_generate_context_raw` — raw format passes through source content
- `test_agent_generate_context_per_repo` — {repo} generates one file per configured repo
- `test_agent_generate_context_compose_with` — appends compose_with files
- `test_agent_generate_context_dry_run` — prints what would be generated without writing
- `test_agent_generate_context_opencode_format` — verifies frontmatter for opencode skill
- `test_agent_generate_context_claude_format` — verifies frontmatter for claude skill

## Files to create/modify

| File | Action | Change |
|------|--------|--------|
| `src/core/manifest.rs` | MODIFY | Add `context_source`, `targets` to `WorkspaceAgentConfig`; add `AgentContextTarget` |
| `src/cli/commands/agent/generate.rs` | CREATE | Context generation with format adapters |
| `src/cli/commands/agent/mod.rs` | MODIFY | Add `pub mod generate;` and re-export |
| `src/main.rs` | MODIFY | Add `GenerateContext` to `AgentCommands` |
| `src/cli/commands/sync.rs` | MODIFY | Call generation after composefiles |
| `tests/test_agent.rs` | MODIFY | Add generation tests |
| `docs/PLAN-multi-agent-context.md` | CREATE | Plan doc |

## Existing utilities to reuse

| Utility | File | Purpose |
|---------|------|---------|
| `resolve_file_source()` | `src/files/mod.rs` | Resolve gripspace source paths |
| `process_composefiles()` | `src/files/mod.rs` | Composefile concat pattern |
| `WorkspaceAgentConfig` | `src/core/manifest.rs` | Existing agent config |
| `RepoAgentConfig` | `src/core/manifest.rs` | Per-repo agent metadata |
| `filter_repos()` | `src/core/repo.rs` | Get repos list |
| `Output::*` | `src/cli/output.rs` | Terminal display |

## Verification

1. `cargo build` succeeds
2. `cargo test` — all existing tests pass + new generation tests
3. `cargo clippy` clean
4. `cargo fmt` clean
5. `gr agent generate-context --dry-run` — shows what would be generated
6. Manual: configure a target in test manifest, run generate, verify output file exists with correct format
