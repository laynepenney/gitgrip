//! Integration tests for the sync command.

mod common;

use common::assertions::{assert_file_exists, assert_on_branch};
use common::fixtures::WorkspaceBuilder;
use common::git_helpers;

#[test]
fn test_sync_clones_missing_repos() {
    let ws = WorkspaceBuilder::new()
        .add_repo("frontend")
        .add_repo("backend")
        .build();

    // Remove one repo to simulate "not cloned"
    std::fs::remove_dir_all(ws.repo_path("backend")).unwrap();
    assert!(!ws.repo_path("backend").exists());

    let manifest = ws.load_manifest();

    let result =
        gitgrip::cli::commands::sync::run_sync(&ws.workspace_root, &manifest, false, false);
    assert!(result.is_ok(), "sync should succeed: {:?}", result.err());

    // backend should now be cloned
    assert!(ws.repo_path("backend").join(".git").exists());
    assert_on_branch(&ws.repo_path("backend"), "main");
}

#[test]
fn test_sync_pulls_existing_repos() {
    let ws = WorkspaceBuilder::new().add_repo("app").build();

    // Push a new commit to the bare remote (simulating upstream changes)
    let bare_path = ws.remote_path("app");
    let staging = ws._temp.path().join("sync-staging");
    git_helpers::clone_repo(&ws.remote_url("app"), &staging);
    git_helpers::commit_file(&staging, "new-file.txt", "content", "Add new file");
    git_helpers::push_branch(&staging, "origin", "main");

    let manifest = ws.load_manifest();

    let result =
        gitgrip::cli::commands::sync::run_sync(&ws.workspace_root, &manifest, false, false);
    assert!(result.is_ok(), "sync should succeed: {:?}", result.err());

    // The new file should now exist in the workspace repo
    assert_file_exists(&ws.repo_path("app").join("new-file.txt"));
}

#[test]
fn test_sync_handles_up_to_date() {
    let ws = WorkspaceBuilder::new().add_repo("app").build();

    let manifest = ws.load_manifest();

    // Sync when already up to date
    let result =
        gitgrip::cli::commands::sync::run_sync(&ws.workspace_root, &manifest, false, false);
    assert!(
        result.is_ok(),
        "sync should succeed when up to date: {:?}",
        result.err()
    );
}

#[test]
fn test_sync_multiple_repos() {
    let ws = WorkspaceBuilder::new()
        .add_repo("alpha")
        .add_repo("beta")
        .add_repo("gamma")
        .build();

    // Remove alpha and beta to test clone
    std::fs::remove_dir_all(ws.repo_path("alpha")).unwrap();
    std::fs::remove_dir_all(ws.repo_path("beta")).unwrap();

    let manifest = ws.load_manifest();

    let result =
        gitgrip::cli::commands::sync::run_sync(&ws.workspace_root, &manifest, false, false);
    assert!(result.is_ok(), "sync should succeed: {:?}", result.err());

    // All should now be cloned
    assert!(ws.repo_path("alpha").join(".git").exists());
    assert!(ws.repo_path("beta").join(".git").exists());
    assert!(ws.repo_path("gamma").join(".git").exists());
}

#[test]
fn test_sync_quiet_mode() {
    let ws = WorkspaceBuilder::new()
        .add_repo("frontend")
        .add_repo("backend")
        .build();

    let manifest = ws.load_manifest();

    // Quiet sync on already-synced repos should succeed (suppresses "up to date" messages)
    let result = gitgrip::cli::commands::sync::run_sync(&ws.workspace_root, &manifest, false, true);
    assert!(
        result.is_ok(),
        "quiet sync should succeed: {:?}",
        result.err()
    );
}
