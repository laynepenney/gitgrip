# Issue #288: Agent context section in manifest

## Context

AI agents working with gitgrip workspaces currently have no structured way to discover build/test/lint commands per repo. They must read CLAUDE.md or guess the build system. Adding an `agent:` section to the manifest makes this metadata machine-readable and discoverable via `gr` commands.

## Approach

Add optional `agent:` config at both per-repo and workspace levels. This is purely additive — existing manifests continue to work unchanged.

## Changes

### 1. `src/core/manifest.rs` — Add agent structs and fields

**New structs:**

```rust
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct RepoAgentConfig {
    #[serde(skip_serializing_if = "Option::is_none")]
    pub description: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub language: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub build: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub test: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub lint: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub format: Option<String>,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct WorkspaceAgentConfig {
    #[serde(skip_serializing_if = "Option::is_none")]
    pub description: Option<String>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub conventions: Vec<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub workflows: Option<HashMap<String, String>>,
}
```

**Add to `RepoConfig`** (after `groups` field, line ~139):
```rust
#[serde(skip_serializing_if = "Option::is_none")]
pub agent: Option<RepoAgentConfig>,
```

**Add to `WorkspaceConfig`** (after `ci` field, line ~303):
```rust
#[serde(skip_serializing_if = "Option::is_none")]
pub agent: Option<WorkspaceAgentConfig>,
```

No special validation needed — all fields are optional strings/vecs.

### 2. `src/core/repo.rs` — Expose agent config in RepoInfo

Add `agent: Option<RepoAgentConfig>` to the `RepoInfo` struct. Extract from `config.agent.clone()` in `from_config()`.

### 3. `src/cli/commands/manifest.rs` — Update schema docs

Add agent fields to the markdown schema tables:
- Repo config table: `agent.description`, `agent.language`, `agent.build`, `agent.test`, `agent.lint`, `agent.format`
- Workspace config table: `agent.description`, `agent.conventions`, `agent.workflows`

Update YAML schema example in the same file.

### 4. `docs/manifest-schema.yaml` — Add agent examples

Add example `agent:` blocks to both repo and workspace sections.

### 5. Unit tests in `src/core/manifest.rs`

Add tests:
- `test_parse_repo_agent_config` — Parse manifest with per-repo agent metadata
- `test_parse_workspace_agent_config` — Parse manifest with workspace agent config
- `test_agent_config_optional` — Verify manifests without agent section still parse
- `test_agent_config_serialization_roundtrip` — Parse → serialize → parse

### 6. `src/core/gripspace.rs` — Agent config merging for gripspace includes

When resolving gripspaces, workspace-level agent config from included gripspaces should merge (local workspace agent config wins over inherited). Follow the pattern used for `scripts` and `env` merging.

## Files to modify

| File | Change |
|------|--------|
| `src/core/manifest.rs` | Add `RepoAgentConfig`, `WorkspaceAgentConfig` structs; add fields to `RepoConfig` and `WorkspaceConfig` |
| `src/core/repo.rs` | Add `agent` field to `RepoInfo` |
| `src/core/gripspace.rs` | Merge workspace agent config from gripspace includes |
| `src/cli/commands/manifest.rs` | Update schema docs |
| `docs/manifest-schema.yaml` | Add agent examples |

## What this does NOT include

- No new CLI commands (that's #289 `gr agent`)
- No changes to existing commands
- No runtime behavior changes

This is purely the manifest schema and parsing layer. Commands that use agent metadata come in #289.

## Verification

1. `cargo build` succeeds
2. `cargo test` passes (all existing + new agent tests)
3. `cargo clippy` clean
4. Manual: create a manifest with agent sections, verify `gr manifest schema` shows the new fields
5. Manual: verify `gr status` still works with and without agent sections
