//! Integration tests for the gc command.

mod common;

use common::fixtures::WorkspaceBuilder;

#[test]
fn test_gc_dry_run_reports_sizes() {
    let ws = WorkspaceBuilder::new()
        .add_repo("frontend")
        .add_repo("backend")
        .build();

    let manifest = ws.load_manifest();

    let result = gitgrip::cli::commands::gc::run_gc(
        &ws.workspace_root,
        &manifest,
        false,
        true, // dry_run
        None,
        None,
    );
    assert!(
        result.is_ok(),
        "gc dry run should succeed: {:?}",
        result.err()
    );
}

#[test]
fn test_gc_runs_successfully() {
    let ws = WorkspaceBuilder::new()
        .add_repo("frontend")
        .add_repo("backend")
        .build();

    let manifest = ws.load_manifest();

    let result = gitgrip::cli::commands::gc::run_gc(
        &ws.workspace_root,
        &manifest,
        false, // not aggressive
        false, // not dry_run
        None,
        None,
    );
    assert!(result.is_ok(), "gc should succeed: {:?}", result.err());
}

#[test]
fn test_gc_aggressive() {
    let ws = WorkspaceBuilder::new().add_repo("app").build();

    let manifest = ws.load_manifest();

    let result = gitgrip::cli::commands::gc::run_gc(
        &ws.workspace_root,
        &manifest,
        true,  // aggressive
        false, // not dry_run
        None,
        None,
    );
    assert!(
        result.is_ok(),
        "gc --aggressive should succeed: {:?}",
        result.err()
    );
}

#[test]
fn test_gc_skips_missing_repos() {
    let ws = WorkspaceBuilder::new().add_repo("app").build();

    // Remove the repo to simulate it not being cloned
    std::fs::remove_dir_all(ws.repo_path("app")).unwrap();

    let manifest = ws.load_manifest();

    let result =
        gitgrip::cli::commands::gc::run_gc(&ws.workspace_root, &manifest, false, false, None, None);
    assert!(
        result.is_ok(),
        "gc should handle missing repos gracefully: {:?}",
        result.err()
    );
}
