//! Integration tests for the link command.

mod common;

use common::fixtures::WorkspaceBuilder;
use std::fs;

/// Helper: append copyfile/linkfile entries to a repo's manifest config.
fn write_link_manifest(ws: &common::fixtures::WorkspaceFixture, repo_name: &str, link_yaml: &str) {
    let manifest_path =
        gitgrip::core::manifest_paths::resolve_gripspace_manifest_path(&ws.workspace_root)
            .expect("workspace manifest path should resolve");
    let content = fs::read_to_string(&manifest_path).unwrap();

    // Insert link config under the specified repo entry
    let search = format!("  {}:", repo_name);
    let updated = content.replace(&search, &format!("  {}:\n{}", repo_name, link_yaml));
    fs::write(&manifest_path, updated).unwrap();
}

// ── link status ──────────────────────────────────────────────────────

#[test]
fn test_link_status_no_links() {
    let ws = WorkspaceBuilder::new().add_repo("app").build();

    let manifest = ws.load_manifest();

    let result = gitgrip::cli::commands::link::run_link(
        &ws.workspace_root,
        &manifest,
        true,  // status
        false, // not apply
        false,
    );
    assert!(
        result.is_ok(),
        "link status with no links should succeed: {:?}",
        result.err()
    );
}

#[test]
fn test_link_status_with_copyfile() {
    let ws = WorkspaceBuilder::new()
        .add_repo_with_files("config-repo", vec![("shared.config", "key=value")])
        .build();

    write_link_manifest(
        &ws,
        "config-repo",
        "    copyfile:\n      - src: shared.config\n        dest: .shared.config",
    );

    let manifest = ws.load_manifest();

    let result = gitgrip::cli::commands::link::run_link(
        &ws.workspace_root,
        &manifest,
        true, // status
        false,
        false,
    );
    assert!(
        result.is_ok(),
        "link status with copyfile should succeed: {:?}",
        result.err()
    );
}

#[test]
fn test_link_status_with_linkfile() {
    let ws = WorkspaceBuilder::new()
        .add_repo_with_files("config-repo", vec![("env.template", "ENV=dev")])
        .build();

    write_link_manifest(
        &ws,
        "config-repo",
        "    linkfile:\n      - src: env.template\n        dest: .env.template",
    );

    let manifest = ws.load_manifest();

    let result = gitgrip::cli::commands::link::run_link(
        &ws.workspace_root,
        &manifest,
        true, // status
        false,
        false,
    );
    assert!(
        result.is_ok(),
        "link status with linkfile should succeed: {:?}",
        result.err()
    );
}

// ── link apply ──────────────────────────────────────────────────────

#[test]
fn test_link_apply_copyfile() {
    let ws = WorkspaceBuilder::new()
        .add_repo_with_files("config-repo", vec![("shared.config", "key=value")])
        .build();

    write_link_manifest(
        &ws,
        "config-repo",
        "    copyfile:\n      - src: shared.config\n        dest: .shared.config",
    );

    let manifest = ws.load_manifest();

    let result = gitgrip::cli::commands::link::run_link(
        &ws.workspace_root,
        &manifest,
        false,
        true, // apply
        false,
    );
    assert!(
        result.is_ok(),
        "link apply copyfile should succeed: {:?}",
        result.err()
    );

    let dest = ws.workspace_root.join(".shared.config");
    assert!(dest.exists(), "copied file should exist at destination");

    let content = fs::read_to_string(&dest).unwrap();
    assert_eq!(
        content, "key=value",
        "copied file should have correct content"
    );
}

#[test]
fn test_link_apply_linkfile() {
    let ws = WorkspaceBuilder::new()
        .add_repo_with_files("config-repo", vec![("env.template", "ENV=dev")])
        .build();

    write_link_manifest(
        &ws,
        "config-repo",
        "    linkfile:\n      - src: env.template\n        dest: .env.template",
    );

    let manifest = ws.load_manifest();

    let result = gitgrip::cli::commands::link::run_link(
        &ws.workspace_root,
        &manifest,
        false,
        true, // apply
        false,
    );
    assert!(
        result.is_ok(),
        "link apply linkfile should succeed: {:?}",
        result.err()
    );

    let dest = ws.workspace_root.join(".env.template");
    assert!(dest.exists(), "symlink should exist at destination");
    assert!(
        dest.is_symlink(),
        "destination should be a symlink, not a copy"
    );
}

#[test]
fn test_link_apply_missing_repo() {
    let ws = WorkspaceBuilder::new().add_repo("app").build();

    // Remove the repo to simulate not-cloned
    fs::remove_dir_all(ws.repo_path("app")).unwrap();

    write_link_manifest(
        &ws,
        "app",
        "    copyfile:\n      - src: config.json\n        dest: .config.json",
    );

    let manifest = ws.load_manifest();

    // Should succeed (skip missing repos gracefully)
    let result = gitgrip::cli::commands::link::run_link(
        &ws.workspace_root,
        &manifest,
        false,
        true, // apply
        false,
    );
    assert!(
        result.is_ok(),
        "link apply with missing repo should succeed: {:?}",
        result.err()
    );
}

// ── link default (no flags = status) ──────────────────────────────

#[test]
fn test_link_default_shows_status() {
    let ws = WorkspaceBuilder::new().add_repo("app").build();

    let manifest = ws.load_manifest();

    // No flags → defaults to status
    let result =
        gitgrip::cli::commands::link::run_link(&ws.workspace_root, &manifest, false, false, false);
    assert!(
        result.is_ok(),
        "link default should succeed: {:?}",
        result.err()
    );
}
