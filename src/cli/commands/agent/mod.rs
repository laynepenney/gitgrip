//! Agent command implementations
//!
//! Subcommands for AI agent context discovery and workspace operations.

pub mod build;
pub mod context;
pub mod generate;
pub mod test;
pub mod verify;

pub use build::run_agent_build;
pub use context::run_agent_context;
pub use generate::run_agent_generate_context;
pub use test::run_agent_test;
pub use verify::run_agent_verify;

use serde::Serialize;
use std::collections::HashMap;

/// JSON output for gr agent context
#[derive(Serialize)]
pub struct AgentContextJson {
    pub workspace: WorkspaceContextJson,
    pub repos: Vec<RepoContextJson>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub griptree: Option<GriptreeContextJson>,
}

/// JSON workspace context
#[derive(Serialize)]
pub struct WorkspaceContextJson {
    pub root: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub description: Option<String>,
    #[serde(skip_serializing_if = "Vec::is_empty")]
    pub conventions: Vec<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub workflows: Option<HashMap<String, String>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub scripts: Option<Vec<String>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub env: Option<HashMap<String, String>>,
}

/// JSON repo context
#[derive(Serialize)]
pub struct RepoContextJson {
    pub name: String,
    pub path: String,
    pub url: String,
    pub default_branch: String,
    pub current_branch: String,
    pub clean: bool,
    pub exists: bool,
    #[serde(skip_serializing_if = "std::ops::Not::not")]
    pub reference: bool,
    #[serde(skip_serializing_if = "Vec::is_empty")]
    pub groups: Vec<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub agent: Option<RepoAgentContextJson>,
}

/// JSON repo agent config
#[derive(Serialize)]
pub struct RepoAgentContextJson {
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

/// JSON griptree context
#[derive(Serialize)]
pub struct GriptreeContextJson {
    pub branch: String,
    pub path: String,
    pub upstreams: HashMap<String, String>,
}
