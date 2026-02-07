//! Integration tests for the sync command.

mod common;

use common::assertions::{assert_file_exists, assert_on_branch};
use common::fixtures::WorkspaceBuilder;
use common::git_helpers;
use gitgrip::core::griptree::GriptreeConfig;
use std::path::Path;

fn write_griptree_config(workspace_root: &Path, branch: &str, repo: &str, upstream: &str) {
    let mut config = GriptreeConfig::new(branch, &workspace_root.to_string_lossy());
    config
        .repo_upstreams
        .insert(repo.to_string(), upstream.to_string());
    let config_path = workspace_root.join(".gitgrip").join("griptree.json");
    config.save(&config_path).unwrap();
}

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
        gitgrip::cli::commands::sync::run_sync(&ws.workspace_root, &manifest, false, false, None);
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
        gitgrip::cli::commands::sync::run_sync(&ws.workspace_root, &manifest, false, false, None);
    assert!(result.is_ok(), "sync should succeed: {:?}", result.err());

    // The new file should now exist in the workspace repo
    assert_file_exists(&ws.repo_path("app").join("new-file.txt"));
}

#[test]
fn test_sync_uses_griptree_upstream_mapping() {
    let ws = WorkspaceBuilder::new().add_repo("app").build();

    let staging = ws._temp.path().join("sync-upstream-staging");
    git_helpers::clone_repo(&ws.remote_url("app"), &staging);
    git_helpers::create_branch(&staging, "dev");
    git_helpers::commit_file(&staging, "dev-only.txt", "dev", "Add dev file");
    git_helpers::push_branch(&staging, "origin", "dev");

    git_helpers::create_branch(&ws.repo_path("app"), "feat/griptree");

    write_griptree_config(&ws.workspace_root, "feat/griptree", "app", "origin/dev");
    let manifest = ws.load_manifest();

    let result =
        gitgrip::cli::commands::sync::run_sync(&ws.workspace_root, &manifest, false, false, None);
    assert!(result.is_ok(), "sync should succeed: {:?}", result.err());

    assert_file_exists(&ws.repo_path("app").join("dev-only.txt"));
}

#[test]
fn test_sync_handles_up_to_date() {
    let ws = WorkspaceBuilder::new().add_repo("app").build();

    let manifest = ws.load_manifest();

    // Sync when already up to date
    let result =
        gitgrip::cli::commands::sync::run_sync(&ws.workspace_root, &manifest, false, false, None);
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
        gitgrip::cli::commands::sync::run_sync(&ws.workspace_root, &manifest, false, false, None);
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
    let result =
        gitgrip::cli::commands::sync::run_sync(&ws.workspace_root, &manifest, false, true, None);
    assert!(
        result.is_ok(),
        "quiet sync should succeed: {:?}",
        result.err()
    );
}
