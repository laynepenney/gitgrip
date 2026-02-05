//! Integration tests for the cherry-pick command.

mod common;

use common::fixtures::WorkspaceBuilder;
use common::git_helpers;

#[test]
fn test_cherry_pick_applies_commit() {
    let ws = WorkspaceBuilder::new().add_repo("app").build();

    let manifest = ws.load_manifest();

    // Create a branch, make a commit, then switch back to main
    git_helpers::create_branch(&ws.repo_path("app"), "feat/source");
    let sha = git_helpers::commit_file(
        &ws.repo_path("app"),
        "new-feature.txt",
        "feature content",
        "Add new feature",
    );
    git_helpers::checkout(&ws.repo_path("app"), "main");

    // Cherry-pick the commit onto main
    let result = gitgrip::cli::commands::cherry_pick::run_cherry_pick(
        &ws.workspace_root,
        &manifest,
        Some(&sha),
        false,
        false,
        None,
        None,
    );
    assert!(
        result.is_ok(),
        "cherry-pick should succeed: {:?}",
        result.err()
    );

    // Verify the file exists on main
    assert!(ws.repo_path("app").join("new-feature.txt").exists());
}

#[test]
fn test_cherry_pick_skips_repos_without_commit() {
    let ws = WorkspaceBuilder::new()
        .add_repo("frontend")
        .add_repo("backend")
        .build();

    let manifest = ws.load_manifest();

    // Create commit only in frontend
    git_helpers::create_branch(&ws.repo_path("frontend"), "feat/source");
    let sha = git_helpers::commit_file(
        &ws.repo_path("frontend"),
        "frontend-only.txt",
        "content",
        "Frontend-only change",
    );
    git_helpers::checkout(&ws.repo_path("frontend"), "main");

    // Cherry-pick — backend should be silently skipped
    let result = gitgrip::cli::commands::cherry_pick::run_cherry_pick(
        &ws.workspace_root,
        &manifest,
        Some(&sha),
        false,
        false,
        None,
        None,
    );
    assert!(
        result.is_ok(),
        "cherry-pick should succeed: {:?}",
        result.err()
    );

    // frontend has the file, backend does not
    assert!(ws.repo_path("frontend").join("frontend-only.txt").exists());
    assert!(!ws.repo_path("backend").join("frontend-only.txt").exists());
}

#[test]
fn test_cherry_pick_conflict_reports_error() {
    let ws = WorkspaceBuilder::new().add_repo("app").build();

    let manifest = ws.load_manifest();

    // Create conflicting changes
    git_helpers::create_branch(&ws.repo_path("app"), "feat/conflict");
    let sha = git_helpers::commit_file(
        &ws.repo_path("app"),
        "README.md",
        "conflict branch content",
        "Change README on branch",
    );
    git_helpers::checkout(&ws.repo_path("app"), "main");
    git_helpers::commit_file(
        &ws.repo_path("app"),
        "README.md",
        "main branch content",
        "Change README on main",
    );

    // Cherry-pick should report conflict
    let result = gitgrip::cli::commands::cherry_pick::run_cherry_pick(
        &ws.workspace_root,
        &manifest,
        Some(&sha),
        false,
        false,
        None,
        None,
    );
    // Should succeed (doesn't return error, just reports conflict)
    assert!(
        result.is_ok(),
        "cherry-pick with conflict should not return error: {:?}",
        result.err()
    );

    // Clean up: abort the cherry-pick
    let abort_result = gitgrip::cli::commands::cherry_pick::run_cherry_pick(
        &ws.workspace_root,
        &manifest,
        None,
        true, // abort
        false,
        None,
        None,
    );
    assert!(abort_result.is_ok());
}

#[test]
fn test_cherry_pick_abort() {
    let ws = WorkspaceBuilder::new().add_repo("app").build();

    let manifest = ws.load_manifest();

    // Create conflicting changes
    git_helpers::create_branch(&ws.repo_path("app"), "feat/conflict");
    let sha = git_helpers::commit_file(
        &ws.repo_path("app"),
        "README.md",
        "conflict content",
        "Conflict change",
    );
    git_helpers::checkout(&ws.repo_path("app"), "main");
    git_helpers::commit_file(
        &ws.repo_path("app"),
        "README.md",
        "main content",
        "Main change",
    );

    // Cherry-pick (will conflict)
    gitgrip::cli::commands::cherry_pick::run_cherry_pick(
        &ws.workspace_root,
        &manifest,
        Some(&sha),
        false,
        false,
        None,
        None,
    )
    .unwrap();

    // Abort
    let result = gitgrip::cli::commands::cherry_pick::run_cherry_pick(
        &ws.workspace_root,
        &manifest,
        None,
        true, // abort
        false,
        None,
        None,
    );
    assert!(
        result.is_ok(),
        "cherry-pick abort should succeed: {:?}",
        result.err()
    );
}

#[test]
fn test_cherry_pick_nonexistent_sha() {
    let ws = WorkspaceBuilder::new().add_repo("app").build();

    let manifest = ws.load_manifest();

    // Cherry-pick a non-existent SHA
    let result = gitgrip::cli::commands::cherry_pick::run_cherry_pick(
        &ws.workspace_root,
        &manifest,
        Some("deadbeef1234567890abcdef1234567890abcdef"),
        false,
        false,
        None,
        None,
    );
    assert!(
        result.is_ok(),
        "cherry-pick with bad SHA should succeed gracefully: {:?}",
        result.err()
    );
}
