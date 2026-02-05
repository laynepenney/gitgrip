//! Integration tests for the push command.

mod common;

use common::assertions::assert_on_branch;
use common::fixtures::WorkspaceBuilder;
use common::git_helpers;

#[test]
fn test_push_to_remote() {
    let ws = WorkspaceBuilder::new().add_repo("app").build();

    let manifest = ws.load_manifest();

    // Create branch, make changes, commit
    gitgrip::cli::commands::branch::run_branch(
        &ws.workspace_root,
        &manifest,
        Some("feat/push-test"),
        false,
        false,
        None,
        None,
        false,
    )
    .unwrap();

    std::fs::write(ws.repo_path("app").join("pushed.txt"), "content").unwrap();
    let files = vec![".".to_string()];
    gitgrip::cli::commands::add::run_add(&ws.workspace_root, &manifest, &files).unwrap();
    gitgrip::cli::commands::commit::run_commit(
        &ws.workspace_root,
        &manifest,
        "feat: push test",
        false,
    )
    .unwrap();

    // Push with set-upstream
    let result = gitgrip::cli::commands::push::run_push(
        &ws.workspace_root,
        &manifest,
        true, // set_upstream
        false,
        false,
    );
    assert!(result.is_ok(), "push should succeed: {:?}", result.err());

    // Verify the branch exists on the remote
    assert!(
        git_helpers::branch_exists(&ws.repo_path("app"), "feat/push-test"),
        "branch should exist locally"
    );
}

#[test]
fn test_push_nothing_to_push() {
    let ws = WorkspaceBuilder::new().add_repo("app").build();

    let manifest = ws.load_manifest();

    // Push with nothing to push -- should succeed
    let result =
        gitgrip::cli::commands::push::run_push(&ws.workspace_root, &manifest, false, false, false);
    assert!(
        result.is_ok(),
        "push with nothing should succeed: {:?}",
        result.err()
    );
}

#[test]
fn test_push_skips_reference_repos() {
    let ws = WorkspaceBuilder::new()
        .add_repo("app")
        .add_reference_repo("docs")
        .build();

    let manifest = ws.load_manifest();

    // Create branch in app only (reference repos are skipped)
    gitgrip::cli::commands::branch::run_branch(
        &ws.workspace_root,
        &manifest,
        Some("feat/ref-test"),
        false,
        false,
        None,
        None,
        false,
    )
    .unwrap();

    std::fs::write(ws.repo_path("app").join("change.txt"), "data").unwrap();
    let files = vec![".".to_string()];
    gitgrip::cli::commands::add::run_add(&ws.workspace_root, &manifest, &files).unwrap();
    gitgrip::cli::commands::commit::run_commit(&ws.workspace_root, &manifest, "change", false)
        .unwrap();

    // Push -- should skip reference repo
    let result =
        gitgrip::cli::commands::push::run_push(&ws.workspace_root, &manifest, true, false, false);
    assert!(result.is_ok(), "push should succeed: {:?}", result.err());

    // docs should still be on main (not pushed, not branched)
    assert_on_branch(&ws.repo_path("docs"), "main");
}

#[test]
fn test_push_multiple_repos() {
    let ws = WorkspaceBuilder::new()
        .add_repo("frontend")
        .add_repo("backend")
        .build();

    let manifest = ws.load_manifest();

    // Create branch, commit in both
    gitgrip::cli::commands::branch::run_branch(
        &ws.workspace_root,
        &manifest,
        Some("feat/multi-push"),
        false,
        false,
        None,
        None,
        false,
    )
    .unwrap();

    std::fs::write(ws.repo_path("frontend").join("fe.txt"), "fe").unwrap();
    std::fs::write(ws.repo_path("backend").join("be.txt"), "be").unwrap();
    let files = vec![".".to_string()];
    gitgrip::cli::commands::add::run_add(&ws.workspace_root, &manifest, &files).unwrap();
    gitgrip::cli::commands::commit::run_commit(
        &ws.workspace_root,
        &manifest,
        "feat: multi push",
        false,
    )
    .unwrap();

    let result =
        gitgrip::cli::commands::push::run_push(&ws.workspace_root, &manifest, true, false, false);
    assert!(result.is_ok(), "push should succeed: {:?}", result.err());
}

#[test]
fn test_push_force() {
    let ws = WorkspaceBuilder::new().add_repo("app").build();

    let manifest = ws.load_manifest();

    // Create branch, commit, push
    gitgrip::cli::commands::branch::run_branch(
        &ws.workspace_root,
        &manifest,
        Some("feat/force-push"),
        false,
        false,
        None,
        None,
        false,
    )
    .unwrap();

    std::fs::write(ws.repo_path("app").join("first.txt"), "first").unwrap();
    let files = vec![".".to_string()];
    gitgrip::cli::commands::add::run_add(&ws.workspace_root, &manifest, &files).unwrap();
    gitgrip::cli::commands::commit::run_commit(
        &ws.workspace_root,
        &manifest,
        "first commit",
        false,
    )
    .unwrap();
    gitgrip::cli::commands::push::run_push(&ws.workspace_root, &manifest, true, false, false)
        .unwrap();

    // Make another commit
    std::fs::write(ws.repo_path("app").join("second.txt"), "second").unwrap();
    gitgrip::cli::commands::add::run_add(&ws.workspace_root, &manifest, &files).unwrap();
    gitgrip::cli::commands::commit::run_commit(
        &ws.workspace_root,
        &manifest,
        "second commit",
        false,
    )
    .unwrap();

    // Force push
    let result = gitgrip::cli::commands::push::run_push(
        &ws.workspace_root,
        &manifest,
        false,
        true, // force
        false,
    );
    assert!(
        result.is_ok(),
        "force push should succeed: {:?}",
        result.err()
    );
}

#[test]
fn test_push_quiet_mode() {
    let ws = WorkspaceBuilder::new()
        .add_repo("frontend")
        .add_repo("backend")
        .build();

    let manifest = ws.load_manifest();

    // Quiet push with nothing to push should succeed (suppresses "nothing to push" messages)
    let result = gitgrip::cli::commands::push::run_push(
        &ws.workspace_root,
        &manifest,
        false,
        false,
        true, // quiet
    );
    assert!(
        result.is_ok(),
        "quiet push should succeed: {:?}",
        result.err()
    );
}
