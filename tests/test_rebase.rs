//! Integration tests for the rebase command.

mod common;

use common::fixtures::WorkspaceBuilder;
use common::git_helpers;

#[test]
fn test_rebase_on_default_branch_skips() {
    let ws = WorkspaceBuilder::new()
        .add_repo("app")
        .add_repo("lib")
        .build();

    let manifest = ws.load_manifest();

    // All repos are on main (default branch) → rebase should skip all and succeed
    let result = gitgrip::cli::commands::rebase::run_rebase(
        &ws.workspace_root,
        &manifest,
        None,
        false,
        false,
    );
    assert!(
        result.is_ok(),
        "rebase on default branch should succeed: {:?}",
        result.err()
    );
}

#[test]
fn test_rebase_on_feature_branch() {
    let ws = WorkspaceBuilder::new().add_repo("app").build();

    let manifest = ws.load_manifest();

    // Create a feature branch
    git_helpers::create_branch(&ws.repo_path("app"), "feat/rebase-test");

    // Add a commit on the feature branch
    git_helpers::commit_file(
        &ws.repo_path("app"),
        "feature.txt",
        "feature content",
        "Add feature",
    );

    let result = gitgrip::cli::commands::rebase::run_rebase(
        &ws.workspace_root,
        &manifest,
        Some("origin/main"),
        false,
        false,
    );
    assert!(
        result.is_ok(),
        "rebase on feature branch should succeed: {:?}",
        result.err()
    );
}

#[test]
fn test_rebase_abort_no_rebase() {
    let ws = WorkspaceBuilder::new().add_repo("app").build();

    let manifest = ws.load_manifest();

    // Abort with no rebase in progress → should succeed (no-op)
    let result = gitgrip::cli::commands::rebase::run_rebase(
        &ws.workspace_root,
        &manifest,
        None,
        true, // abort
        false,
    );
    assert!(
        result.is_ok(),
        "abort with no rebase should succeed: {:?}",
        result.err()
    );
}

#[test]
fn test_rebase_missing_repo() {
    let ws = WorkspaceBuilder::new().add_repo("app").build();

    // Remove the repo directory to simulate a missing repo
    std::fs::remove_dir_all(ws.repo_path("app")).unwrap();

    let manifest = ws.load_manifest();

    // Should gracefully skip missing repos
    let result = gitgrip::cli::commands::rebase::run_rebase(
        &ws.workspace_root,
        &manifest,
        None,
        false,
        false,
    );
    assert!(
        result.is_ok(),
        "rebase with missing repo should succeed: {:?}",
        result.err()
    );
}
