//! Agent command tests for gitgrip.
//!
//! Tests for the gr agent subcommands:
//! - context (markdown and JSON output)
//! - build
//! - test
//! - verify

mod common;

use std::fs;
use std::path::Path;

use common::fixtures::WorkspaceBuilder;

/// Helper to add per-repo agent config by inserting it into the repo's YAML block.
///
/// `repo_name` — the repo to add agent config to
/// `agent_yaml` — the agent block (indented 4 spaces under the repo key), e.g.:
///   `"      description: Test app\n      build: cargo build\n"`
fn add_repo_agent_config(workspace_root: &Path, repo_name: &str, agent_yaml: &str) {
    let manifest_path = workspace_root
        .join(".gitgrip")
        .join("spaces")
        .join("main")
        .join("gripspace.yml");
    let content = fs::read_to_string(&manifest_path).unwrap();

    // Find the repo block and insert agent config after default_branch line
    let search = format!("  {}:\n", repo_name);
    let repo_start = content
        .find(&search)
        .unwrap_or_else(|| panic!("repo '{}' not found in manifest", repo_name));

    // Find the end of the default_branch line for this repo
    let after_repo = &content[repo_start..];
    let db_needle = "    default_branch: main\n";
    let db_offset = after_repo
        .find(db_needle)
        .expect("default_branch line not found");
    let insert_pos = repo_start + db_offset + db_needle.len();

    let mut new_content = String::with_capacity(content.len() + agent_yaml.len() + 20);
    new_content.push_str(&content[..insert_pos]);
    new_content.push_str("    agent:\n");
    new_content.push_str(agent_yaml);
    new_content.push_str(&content[insert_pos..]);

    fs::write(&manifest_path, new_content).unwrap();
}

/// Helper to append workspace-level agent config to the manifest.
fn add_workspace_agent_config(workspace_root: &Path, workspace_yaml: &str) {
    let manifest_path = workspace_root
        .join(".gitgrip")
        .join("spaces")
        .join("main")
        .join("gripspace.yml");
    let mut content = fs::read_to_string(&manifest_path).unwrap();
    content.push_str(workspace_yaml);
    fs::write(&manifest_path, content).unwrap();
}

// ── Context Tests ────────────────────────────────────────────────

#[test]
fn test_agent_context_no_agent_config() {
    let ws = WorkspaceBuilder::new().add_repo("app").build();
    let manifest = ws.load_manifest();

    // Should succeed even without any agent config
    let result = gitgrip::cli::commands::agent::run_agent_context(
        &ws.workspace_root,
        &manifest,
        None,
        false,
    );
    assert!(
        result.is_ok(),
        "context should succeed without agent config: {:?}",
        result.err()
    );
}

#[test]
fn test_agent_context_with_workspace_agent_config() {
    let ws = WorkspaceBuilder::new().add_repo("app").build();

    add_workspace_agent_config(
        &ws.workspace_root,
        r#"workspace:
  agent:
    description: "Test workspace"
    conventions:
      - "Use conventional commits"
      - "Never push to main"
"#,
    );

    let manifest = ws.load_manifest();
    let result = gitgrip::cli::commands::agent::run_agent_context(
        &ws.workspace_root,
        &manifest,
        None,
        false,
    );
    assert!(
        result.is_ok(),
        "context should succeed with workspace agent config: {:?}",
        result.err()
    );
}

#[test]
fn test_agent_context_with_repo_agent_config() {
    let ws = WorkspaceBuilder::new().add_repo("app").build();

    add_repo_agent_config(
        &ws.workspace_root,
        "app",
        "      description: \"Test application\"\n      language: rust\n      build: cargo build\n      test: cargo test\n",
    );

    let manifest = ws.load_manifest();
    let result = gitgrip::cli::commands::agent::run_agent_context(
        &ws.workspace_root,
        &manifest,
        None,
        false,
    );
    assert!(
        result.is_ok(),
        "context should succeed with repo agent config: {:?}",
        result.err()
    );
}

#[test]
fn test_agent_context_json_output() {
    let ws = WorkspaceBuilder::new().add_repo("app").build();

    add_workspace_agent_config(
        &ws.workspace_root,
        r#"workspace:
  agent:
    description: "Test workspace"
"#,
    );

    let manifest = ws.load_manifest();
    let result = gitgrip::cli::commands::agent::run_agent_context(
        &ws.workspace_root,
        &manifest,
        None,
        true, // json mode
    );
    assert!(
        result.is_ok(),
        "context JSON should succeed: {:?}",
        result.err()
    );
}

#[test]
fn test_agent_context_repo_filter() {
    let ws = WorkspaceBuilder::new()
        .add_repo("app")
        .add_repo("lib")
        .build();

    let manifest = ws.load_manifest();

    // Filter to a specific repo
    let result = gitgrip::cli::commands::agent::run_agent_context(
        &ws.workspace_root,
        &manifest,
        Some("app"),
        false,
    );
    assert!(
        result.is_ok(),
        "context with repo filter should succeed: {:?}",
        result.err()
    );
}

#[test]
fn test_agent_context_repo_filter_not_found() {
    let ws = WorkspaceBuilder::new().add_repo("app").build();
    let manifest = ws.load_manifest();

    // Filter to nonexistent repo should fail
    let result = gitgrip::cli::commands::agent::run_agent_context(
        &ws.workspace_root,
        &manifest,
        Some("nonexistent"),
        false,
    );
    assert!(result.is_err(), "should fail for nonexistent repo");
    let err = result.unwrap_err().to_string();
    assert!(
        err.contains("not found"),
        "error should mention not found: {}",
        err
    );
}

// ── Build Tests ──────────────────────────────────────────────────

#[test]
fn test_agent_build_runs_command() {
    let ws = WorkspaceBuilder::new().add_repo("app").build();

    let marker = ws.workspace_root.join("app").join("build-marker.txt");
    let agent_yaml = format!("      build: echo built > \"{}\"\n", marker.display());
    add_repo_agent_config(&ws.workspace_root, "app", &agent_yaml);

    let manifest = ws.load_manifest();
    let result =
        gitgrip::cli::commands::agent::run_agent_build(&ws.workspace_root, &manifest, Some("app"));
    assert!(result.is_ok(), "build should succeed: {:?}", result.err());
    assert!(
        marker.exists(),
        "build command should have created marker file"
    );
}

#[test]
fn test_agent_build_fails_on_error() {
    let ws = WorkspaceBuilder::new().add_repo("app").build();

    add_repo_agent_config(&ws.workspace_root, "app", "      build: exit 1\n");

    let manifest = ws.load_manifest();
    let result =
        gitgrip::cli::commands::agent::run_agent_build(&ws.workspace_root, &manifest, Some("app"));
    assert!(result.is_err(), "build should fail when command fails");
}

#[test]
fn test_agent_build_no_config_skips() {
    let ws = WorkspaceBuilder::new().add_repo("app").build();
    let manifest = ws.load_manifest();

    // No agent config — should succeed silently (no repos to build)
    let result =
        gitgrip::cli::commands::agent::run_agent_build(&ws.workspace_root, &manifest, None);
    assert!(
        result.is_ok(),
        "build with no config should succeed: {:?}",
        result.err()
    );
}

#[test]
fn test_agent_build_specific_repo_no_config_errors() {
    let ws = WorkspaceBuilder::new().add_repo("app").build();
    let manifest = ws.load_manifest();

    // Naming a specific repo with no agent.build should error
    let result =
        gitgrip::cli::commands::agent::run_agent_build(&ws.workspace_root, &manifest, Some("app"));
    assert!(
        result.is_err(),
        "build should error when named repo has no build command"
    );
}

// ── Test Tests ───────────────────────────────────────────────────

#[test]
fn test_agent_test_runs_command() {
    let ws = WorkspaceBuilder::new().add_repo("app").build();

    let marker = ws.workspace_root.join("app").join("test-marker.txt");
    let agent_yaml = format!("      test: echo tested > \"{}\"\n", marker.display());
    add_repo_agent_config(&ws.workspace_root, "app", &agent_yaml);

    let manifest = ws.load_manifest();
    let result =
        gitgrip::cli::commands::agent::run_agent_test(&ws.workspace_root, &manifest, Some("app"));
    assert!(result.is_ok(), "test should succeed: {:?}", result.err());
    assert!(
        marker.exists(),
        "test command should have created marker file"
    );
}

// ── Verify Tests ─────────────────────────────────────────────────

#[test]
fn test_agent_verify_runs_all_checks() {
    let ws = WorkspaceBuilder::new().add_repo("app").build();

    add_repo_agent_config(
        &ws.workspace_root,
        "app",
        "      build: \"true\"\n      test: \"true\"\n      lint: \"true\"\n",
    );

    let manifest = ws.load_manifest();
    let result =
        gitgrip::cli::commands::agent::run_agent_verify(&ws.workspace_root, &manifest, Some("app"));
    assert!(
        result.is_ok(),
        "verify should succeed when all checks pass: {:?}",
        result.err()
    );
}

#[test]
fn test_agent_verify_reports_failures() {
    let ws = WorkspaceBuilder::new().add_repo("app").build();

    add_repo_agent_config(
        &ws.workspace_root,
        "app",
        "      build: \"true\"\n      test: exit 1\n      lint: \"true\"\n",
    );

    let manifest = ws.load_manifest();
    let result =
        gitgrip::cli::commands::agent::run_agent_verify(&ws.workspace_root, &manifest, Some("app"));
    assert!(result.is_err(), "verify should fail when a check fails");
    let err = result.unwrap_err().to_string();
    assert!(
        err.contains("1 verification"),
        "should report 1 failure: {}",
        err
    );
}
