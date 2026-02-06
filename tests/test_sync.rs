//! Integration tests for the sync command.

mod common;

use common::assertions::{assert_file_exists, assert_on_branch};
use common::fixtures::WorkspaceBuilder;
use common::git_helpers;
use std::fs;

#[tokio::test]
async fn test_sync_clones_missing_repos() {
    let ws = WorkspaceBuilder::new()
        .add_repo("frontend")
        .add_repo("backend")
        .build();

    // Remove one repo to simulate "not cloned"
    std::fs::remove_dir_all(ws.repo_path("backend")).unwrap();
    assert!(!ws.repo_path("backend").exists());

    let manifest = ws.load_manifest();

    let result = gitgrip::cli::commands::sync::run_sync(
        &ws.workspace_root,
        &manifest,
        false,
        false,
        None,
        false,
    )
    .await;
    assert!(result.is_ok(), "sync should succeed: {:?}", result.err());

    // backend should now be cloned
    assert!(ws.repo_path("backend").join(".git").exists());
    assert_on_branch(&ws.repo_path("backend"), "main");
}

#[tokio::test]
async fn test_sync_pulls_existing_repos() {
    let ws = WorkspaceBuilder::new().add_repo("app").build();

    // Push a new commit to the bare remote (simulating upstream changes)
    let bare_path = ws.remote_path("app");
    let staging = ws._temp.path().join("sync-staging");
    git_helpers::clone_repo(&ws.remote_url("app"), &staging);
    git_helpers::commit_file(&staging, "new-file.txt", "content", "Add new file");
    git_helpers::push_branch(&staging, "origin", "main");

    let manifest = ws.load_manifest();

    let result = gitgrip::cli::commands::sync::run_sync(
        &ws.workspace_root,
        &manifest,
        false,
        false,
        None,
        false,
    )
    .await;
    assert!(result.is_ok(), "sync should succeed: {:?}", result.err());

    // The new file should now exist in the workspace repo
    assert_file_exists(&ws.repo_path("app").join("new-file.txt"));
}

#[tokio::test]
async fn test_sync_handles_up_to_date() {
    let ws = WorkspaceBuilder::new().add_repo("app").build();

    let manifest = ws.load_manifest();

    // Sync when already up to date
    let result = gitgrip::cli::commands::sync::run_sync(
        &ws.workspace_root,
        &manifest,
        false,
        false,
        None,
        false,
    )
    .await;
    assert!(
        result.is_ok(),
        "sync should succeed when up to date: {:?}",
        result.err()
    );
}

#[tokio::test]
async fn test_sync_multiple_repos() {
    let ws = WorkspaceBuilder::new()
        .add_repo("alpha")
        .add_repo("beta")
        .add_repo("gamma")
        .build();

    // Remove alpha and beta to test clone
    std::fs::remove_dir_all(ws.repo_path("alpha")).unwrap();
    std::fs::remove_dir_all(ws.repo_path("beta")).unwrap();

    let manifest = ws.load_manifest();

    let result = gitgrip::cli::commands::sync::run_sync(
        &ws.workspace_root,
        &manifest,
        false,
        false,
        None,
        false,
    )
    .await;
    assert!(result.is_ok(), "sync should succeed: {:?}", result.err());

    // All should now be cloned
    assert!(ws.repo_path("alpha").join(".git").exists());
    assert!(ws.repo_path("beta").join(".git").exists());
    assert!(ws.repo_path("gamma").join(".git").exists());
}

#[tokio::test]
async fn test_sync_quiet_mode() {
    let ws = WorkspaceBuilder::new()
        .add_repo("frontend")
        .add_repo("backend")
        .build();

    let manifest = ws.load_manifest();

    // Quiet sync on already-synced repos should succeed (suppresses "up to date" messages)
    let result = gitgrip::cli::commands::sync::run_sync(
        &ws.workspace_root,
        &manifest,
        false,
        true,
        None,
        false,
    )
    .await;
    assert!(
        result.is_ok(),
        "quiet sync should succeed: {:?}",
        result.err()
    );
}

#[tokio::test]
async fn test_sync_sequential_mode() {
    let ws = WorkspaceBuilder::new()
        .add_repo("frontend")
        .add_repo("backend")
        .build();

    let manifest = ws.load_manifest();

    // Sequential sync (--sequential flag)
    let result = gitgrip::cli::commands::sync::run_sync(
        &ws.workspace_root,
        &manifest,
        false,
        false,
        None,
        true,
    )
    .await;
    assert!(
        result.is_ok(),
        "sequential sync should succeed: {:?}",
        result.err()
    );
}

#[tokio::test]
async fn test_sync_clone_failure_invalid_url() {
    let ws = WorkspaceBuilder::new().add_repo("app").build();
    let mut manifest = ws.load_manifest();

    // Force clone path: delete repo and replace URL with invalid path
    fs::remove_dir_all(ws.repo_path("app")).unwrap();
    assert!(!ws.repo_path("app").exists());
    manifest
        .repos
        .get_mut("app")
        .expect("app repo config")
        .url = "file:///does-not-exist/repo.git".to_string();

    let result = gitgrip::cli::commands::sync::run_sync(
        &ws.workspace_root,
        &manifest,
        false,
        false,
        None,
        false,
    )
    .await;
    assert!(result.is_ok(), "sync should not crash: {:?}", result.err());

    // Clone should fail, leaving no git metadata
    assert!(
        !ws.repo_path("app").join(".git").exists(),
        "expected clone to fail without .git"
    );
}

#[tokio::test]
async fn test_sync_existing_repo_missing_git_dir() {
    let ws = WorkspaceBuilder::new().add_repo("app").build();
    let manifest = ws.load_manifest();

    // Corrupt repo by removing .git
    fs::remove_dir_all(ws.repo_path("app").join(".git")).unwrap();
    assert!(!ws.repo_path("app").join(".git").exists());

    let result = gitgrip::cli::commands::sync::run_sync(
        &ws.workspace_root,
        &manifest,
        false,
        false,
        None,
        false,
    )
    .await;
    assert!(result.is_ok(), "sync should not crash: {:?}", result.err());

    // Sync should report error and leave repo unchanged (still missing .git)
    assert!(
        !ws.repo_path("app").join(".git").exists(),
        "expected sync to fail for non-git directory"
    );
}
