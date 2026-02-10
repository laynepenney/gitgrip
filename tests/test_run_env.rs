//! Integration tests for the run and env commands.

mod common;

use common::fixtures::WorkspaceBuilder;
use std::fs;

/// Helper: append workspace config with env and/or scripts to the manifest.
fn write_workspace_manifest(ws: &common::fixtures::WorkspaceFixture, workspace_yaml: &str) {
    let manifest_path =
        gitgrip::core::manifest_paths::resolve_gripspace_manifest_path(&ws.workspace_root)
            .expect("workspace manifest path should resolve");
    let existing = fs::read_to_string(&manifest_path).unwrap();
    let full = format!("{}\nworkspace:\n{}", existing, workspace_yaml);
    fs::write(&manifest_path, full).unwrap();
}

// ── env ──────────────────────────────────────────────────────

#[test]
fn test_env_no_workspace_config() {
    let ws = WorkspaceBuilder::new().add_repo("app").build();
    let manifest = ws.load_manifest();

    let result = gitgrip::cli::commands::env::run_env(&ws.workspace_root, &manifest);
    assert!(
        result.is_ok(),
        "env with no workspace config should succeed: {:?}",
        result.err()
    );
}

#[test]
fn test_env_with_vars() {
    let ws = WorkspaceBuilder::new().add_repo("app").build();

    write_workspace_manifest(
        &ws,
        r#"  env:
    NODE_ENV: production
    LOG_LEVEL: debug
"#,
    );

    let manifest = ws.load_manifest();
    let result = gitgrip::cli::commands::env::run_env(&ws.workspace_root, &manifest);
    assert!(
        result.is_ok(),
        "env with vars should succeed: {:?}",
        result.err()
    );
}

// ── run ──────────────────────────────────────────────────────

#[test]
fn test_run_list_no_scripts() {
    let ws = WorkspaceBuilder::new().add_repo("app").build();
    let manifest = ws.load_manifest();

    let result = gitgrip::cli::commands::run::run_run(
        &ws.workspace_root,
        &manifest,
        None,
        true, // list
    );
    assert!(
        result.is_ok(),
        "run list with no scripts should succeed: {:?}",
        result.err()
    );
}

#[test]
fn test_run_list_with_scripts() {
    let ws = WorkspaceBuilder::new().add_repo("app").build();

    write_workspace_manifest(
        &ws,
        r#"  scripts:
    build:
      command: "echo building"
    test:
      command: "echo testing"
"#,
    );

    let manifest = ws.load_manifest();
    let result = gitgrip::cli::commands::run::run_run(
        &ws.workspace_root,
        &manifest,
        None,
        true, // list
    );
    assert!(
        result.is_ok(),
        "run list with scripts should succeed: {:?}",
        result.err()
    );
}

#[test]
fn test_run_nonexistent_script() {
    let ws = WorkspaceBuilder::new().add_repo("app").build();
    let manifest = ws.load_manifest();

    let result = gitgrip::cli::commands::run::run_run(
        &ws.workspace_root,
        &manifest,
        Some("nonexistent"),
        false,
    );
    assert!(result.is_err(), "running nonexistent script should fail");
    let err_msg = result.unwrap_err().to_string();
    assert!(
        err_msg.contains("not found"),
        "error should mention not found: {}",
        err_msg
    );
}
