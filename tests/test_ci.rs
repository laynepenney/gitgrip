//! Integration tests for the CI pipeline commands (Phase 6).

mod common;

use common::fixtures::WorkspaceBuilder;
use std::fs;

/// Helper: append workspace CI config to the existing manifest YAML.
fn write_ci_manifest(ws: &common::fixtures::WorkspaceFixture, ci_yaml: &str) {
    let manifest_path = ws
        .workspace_root
        .join(".gitgrip")
        .join("manifests")
        .join("manifest.yaml");
    let existing = fs::read_to_string(&manifest_path).unwrap();
    let full = format!(
        "{}\nworkspace:\n  ci:\n    pipelines:\n{}",
        existing, ci_yaml
    );
    fs::write(&manifest_path, full).unwrap();
}

// ── ci list ──────────────────────────────────────────────────────

#[test]
fn test_ci_list_no_pipelines() {
    let ws = WorkspaceBuilder::new().add_repo("app").build();
    let manifest = ws.load_manifest();

    // No workspace.ci config → prints "No CI pipelines defined."
    let result = gitgrip::cli::commands::ci::run_ci_list(&manifest, false);
    assert!(
        result.is_ok(),
        "ci list with no pipelines should succeed: {:?}",
        result.err()
    );
}

#[test]
fn test_ci_list_pipelines() {
    let ws = WorkspaceBuilder::new().add_repo("app").build();

    write_ci_manifest(
        &ws,
        r#"      build:
        description: "Build project"
        steps:
          - name: compile
            command: "echo compiling"
      test:
        description: "Run tests"
        steps:
          - name: unit
            command: "echo testing"
"#,
    );

    let manifest = ws.load_manifest();
    let result = gitgrip::cli::commands::ci::run_ci_list(&manifest, false);
    assert!(result.is_ok(), "ci list should succeed: {:?}", result.err());
}

#[test]
fn test_ci_list_json() {
    let ws = WorkspaceBuilder::new().add_repo("app").build();

    write_ci_manifest(
        &ws,
        r#"      lint:
        description: "Lint code"
        steps:
          - name: check
            command: "echo linting"
"#,
    );

    let manifest = ws.load_manifest();
    let result = gitgrip::cli::commands::ci::run_ci_list(&manifest, true);
    assert!(
        result.is_ok(),
        "ci list json should succeed: {:?}",
        result.err()
    );
}

// ── ci run ──────────────────────────────────────────────────────

#[test]
fn test_ci_run_simple() {
    let ws = WorkspaceBuilder::new().add_repo("app").build();

    write_ci_manifest(
        &ws,
        r#"      build:
        steps:
          - name: step1
            command: "echo hello"
          - name: step2
            command: "echo world"
"#,
    );

    let manifest = ws.load_manifest();
    let result =
        gitgrip::cli::commands::ci::run_ci_run(&ws.workspace_root, &manifest, "build", false);
    assert!(
        result.is_ok(),
        "ci run simple should succeed: {:?}",
        result.err()
    );
}

#[test]
fn test_ci_run_step_failure_stops() {
    let ws = WorkspaceBuilder::new().add_repo("app").build();

    write_ci_manifest(
        &ws,
        r#"      fail-pipeline:
        steps:
          - name: pass
            command: "echo ok"
          - name: fail
            command: "false"
          - name: never-reached
            command: "echo should not run"
"#,
    );

    let manifest = ws.load_manifest();
    let result = gitgrip::cli::commands::ci::run_ci_run(
        &ws.workspace_root,
        &manifest,
        "fail-pipeline",
        false,
    );
    assert!(result.is_err(), "ci run should fail when a step fails");
}

#[test]
fn test_ci_run_continue_on_error() {
    let ws = WorkspaceBuilder::new().add_repo("app").build();

    write_ci_manifest(
        &ws,
        r#"      resilient:
        steps:
          - name: flaky
            command: "false"
            continue_on_error: true
          - name: after-flaky
            command: "echo still running"
"#,
    );

    let manifest = ws.load_manifest();
    // Even though flaky fails, continue_on_error lets it proceed.
    // The pipeline still reports overall failure (the flaky step failed).
    let result =
        gitgrip::cli::commands::ci::run_ci_run(&ws.workspace_root, &manifest, "resilient", false);
    // Pipeline overall fails because at least one step failed
    assert!(
        result.is_err(),
        "pipeline should report failure even with continue_on_error"
    );
}

#[test]
fn test_ci_run_nonexistent_pipeline() {
    let ws = WorkspaceBuilder::new().add_repo("app").build();

    write_ci_manifest(
        &ws,
        r#"      real:
        steps:
          - name: step1
            command: "echo hi"
"#,
    );

    let manifest = ws.load_manifest();
    let result =
        gitgrip::cli::commands::ci::run_ci_run(&ws.workspace_root, &manifest, "nonexistent", false);
    assert!(result.is_err(), "should error on nonexistent pipeline");
    let err_msg = result.unwrap_err().to_string();
    assert!(
        err_msg.contains("not found"),
        "error should mention 'not found': {}",
        err_msg
    );
}

#[test]
fn test_ci_run_cwd_resolution() {
    let ws = WorkspaceBuilder::new().add_repo("app").build();

    // Create a subdirectory with a marker file
    let subdir = ws.workspace_root.join("app");
    fs::create_dir_all(&subdir).ok();

    write_ci_manifest(
        &ws,
        r#"      cwd-test:
        steps:
          - name: in-app
            command: "pwd"
            cwd: "app"
"#,
    );

    let manifest = ws.load_manifest();
    let result =
        gitgrip::cli::commands::ci::run_ci_run(&ws.workspace_root, &manifest, "cwd-test", false);
    assert!(
        result.is_ok(),
        "ci run with cwd should succeed: {:?}",
        result.err()
    );
}

#[test]
fn test_ci_run_json_output() {
    let ws = WorkspaceBuilder::new().add_repo("app").build();

    write_ci_manifest(
        &ws,
        r#"      json-test:
        steps:
          - name: echo
            command: "echo json"
"#,
    );

    let manifest = ws.load_manifest();
    let result =
        gitgrip::cli::commands::ci::run_ci_run(&ws.workspace_root, &manifest, "json-test", true);
    assert!(
        result.is_ok(),
        "ci run with json should succeed: {:?}",
        result.err()
    );
}

// ── ci result saved ──────────────────────────────────────────────

#[test]
fn test_ci_result_saved() {
    let ws = WorkspaceBuilder::new().add_repo("app").build();

    write_ci_manifest(
        &ws,
        r#"      save-test:
        steps:
          - name: echo
            command: "echo saved"
"#,
    );

    let manifest = ws.load_manifest();
    gitgrip::cli::commands::ci::run_ci_run(&ws.workspace_root, &manifest, "save-test", false)
        .unwrap();

    let result_path = ws
        .workspace_root
        .join(".gitgrip")
        .join("ci-results")
        .join("save-test.json");
    assert!(
        result_path.exists(),
        "CI result file should exist at {}",
        result_path.display()
    );
}

// ── ci status ──────────────────────────────────────────────────────

#[test]
fn test_ci_status_no_results() {
    let ws = WorkspaceBuilder::new().add_repo("app").build();

    let result = gitgrip::cli::commands::ci::run_ci_status(&ws.workspace_root, false);
    assert!(
        result.is_ok(),
        "ci status with no results should succeed: {:?}",
        result.err()
    );
}

#[test]
fn test_ci_status_after_run() {
    let ws = WorkspaceBuilder::new().add_repo("app").build();

    write_ci_manifest(
        &ws,
        r#"      status-test:
        steps:
          - name: echo
            command: "echo done"
"#,
    );

    let manifest = ws.load_manifest();
    gitgrip::cli::commands::ci::run_ci_run(&ws.workspace_root, &manifest, "status-test", false)
        .unwrap();

    // Now check status
    let result = gitgrip::cli::commands::ci::run_ci_status(&ws.workspace_root, false);
    assert!(
        result.is_ok(),
        "ci status after run should succeed: {:?}",
        result.err()
    );
}
