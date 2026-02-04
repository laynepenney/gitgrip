//! Integration tests for the branch command.

mod common;

use common::assertions::{
    assert_all_on_branch, assert_branch_exists, assert_branch_not_exists, assert_on_branch,
};
use common::fixtures::WorkspaceBuilder;
use common::git_helpers;

#[test]
fn test_branch_create_across_repos() {
    let ws = WorkspaceBuilder::new()
        .add_repo("frontend")
        .add_repo("backend")
        .build();

    let manifest = ws.load_manifest();

    let result = gitgrip::cli::commands::branch::run_branch(
        &ws.workspace_root,
        &manifest,
        Some("feat/new-feature"),
        false,
        false,
        None,
    );
    assert!(
        result.is_ok(),
        "branch create should succeed: {:?}",
        result.err()
    );

    // Both repos should now be on the new branch
    assert_on_branch(&ws.repo_path("frontend"), "feat/new-feature");
    assert_on_branch(&ws.repo_path("backend"), "feat/new-feature");
}

#[test]
fn test_branch_delete() {
    let ws = WorkspaceBuilder::new()
        .add_repo("frontend")
        .add_repo("backend")
        .build();

    let manifest = ws.load_manifest();

    // Create branch first
    gitgrip::cli::commands::branch::run_branch(
        &ws.workspace_root,
        &manifest,
        Some("feat/to-delete"),
        false,
        false,
        None,
    )
    .unwrap();

    // Switch back to main so we can delete
    gitgrip::cli::commands::checkout::run_checkout(&ws.workspace_root, &manifest, "main").unwrap();

    // Delete the branch
    let result = gitgrip::cli::commands::branch::run_branch(
        &ws.workspace_root,
        &manifest,
        Some("feat/to-delete"),
        true, // delete
        false,
        None,
    );
    assert!(
        result.is_ok(),
        "branch delete should succeed: {:?}",
        result.err()
    );

    assert_branch_not_exists(&ws.repo_path("frontend"), "feat/to-delete");
    assert_branch_not_exists(&ws.repo_path("backend"), "feat/to-delete");
}

#[test]
fn test_branch_list() {
    let ws = WorkspaceBuilder::new().add_repo("app").build();

    let manifest = ws.load_manifest();

    // Create a couple branches
    gitgrip::cli::commands::branch::run_branch(
        &ws.workspace_root,
        &manifest,
        Some("feat/one"),
        false,
        false,
        None,
    )
    .unwrap();
    git_helpers::checkout(&ws.repo_path("app"), "main");
    gitgrip::cli::commands::branch::run_branch(
        &ws.workspace_root,
        &manifest,
        Some("feat/two"),
        false,
        false,
        None,
    )
    .unwrap();

    // List branches (no name passed)
    let result = gitgrip::cli::commands::branch::run_branch(
        &ws.workspace_root,
        &manifest,
        None,
        false,
        false,
        None,
    );
    assert!(
        result.is_ok(),
        "branch list should succeed: {:?}",
        result.err()
    );
}

#[test]
fn test_branch_filter_repos() {
    let ws = WorkspaceBuilder::new()
        .add_repo("frontend")
        .add_repo("backend")
        .add_repo("shared")
        .build();

    let manifest = ws.load_manifest();

    // Create branch only in frontend and backend
    let filter = vec!["frontend".to_string(), "backend".to_string()];
    let result = gitgrip::cli::commands::branch::run_branch(
        &ws.workspace_root,
        &manifest,
        Some("feat/filtered"),
        false,
        false,
        Some(&filter),
    );
    assert!(
        result.is_ok(),
        "filtered branch should succeed: {:?}",
        result.err()
    );

    assert_on_branch(&ws.repo_path("frontend"), "feat/filtered");
    assert_on_branch(&ws.repo_path("backend"), "feat/filtered");
    // shared should still be on main
    assert_on_branch(&ws.repo_path("shared"), "main");
}

#[test]
fn test_branch_skip_reference_repos() {
    let ws = WorkspaceBuilder::new()
        .add_repo("app")
        .add_reference_repo("docs")
        .build();

    let manifest = ws.load_manifest();

    let result = gitgrip::cli::commands::branch::run_branch(
        &ws.workspace_root,
        &manifest,
        Some("feat/skip-refs"),
        false,
        false,
        None,
    );
    assert!(result.is_ok(), "branch should succeed: {:?}", result.err());

    // app should be on the new branch
    assert_on_branch(&ws.repo_path("app"), "feat/skip-refs");
    // docs (reference) should still be on main
    assert_on_branch(&ws.repo_path("docs"), "main");
}

#[test]
fn test_branch_idempotent_creation() {
    let ws = WorkspaceBuilder::new().add_repo("app").build();

    let manifest = ws.load_manifest();

    // Create branch
    gitgrip::cli::commands::branch::run_branch(
        &ws.workspace_root,
        &manifest,
        Some("feat/existing"),
        false,
        false,
        None,
    )
    .unwrap();

    // Create same branch again -- should not error (prints "already exists")
    let result = gitgrip::cli::commands::branch::run_branch(
        &ws.workspace_root,
        &manifest,
        Some("feat/existing"),
        false,
        false,
        None,
    );
    assert!(
        result.is_ok(),
        "creating an existing branch should not fail: {:?}",
        result.err()
    );
}

#[test]
fn test_branch_not_cloned_repo() {
    let ws = WorkspaceBuilder::new().add_repo("app").build();

    // Manually remove the cloned repo to simulate "not cloned"
    std::fs::remove_dir_all(ws.repo_path("app")).unwrap();

    let manifest = ws.load_manifest();

    // Should succeed (prints warning for not-cloned repo)
    let result = gitgrip::cli::commands::branch::run_branch(
        &ws.workspace_root,
        &manifest,
        Some("feat/no-repo"),
        false,
        false,
        None,
    );
    assert!(
        result.is_ok(),
        "branch on missing repo should not fail: {:?}",
        result.err()
    );
}

#[test]
fn test_branch_create_then_verify_branches_exist() {
    let ws = WorkspaceBuilder::new()
        .add_repo("alpha")
        .add_repo("beta")
        .build();

    let manifest = ws.load_manifest();

    gitgrip::cli::commands::branch::run_branch(
        &ws.workspace_root,
        &manifest,
        Some("feat/verify"),
        false,
        false,
        None,
    )
    .unwrap();

    assert_branch_exists(&ws.repo_path("alpha"), "feat/verify");
    assert_branch_exists(&ws.repo_path("beta"), "feat/verify");
    // main should still exist too
    assert_branch_exists(&ws.repo_path("alpha"), "main");
    assert_branch_exists(&ws.repo_path("beta"), "main");
}
