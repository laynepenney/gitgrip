//! Release command tests for gitgrip.
//!
//! Tests focus on the file manipulation aspects (version bump, changelog)
//! and validation. Full PR/merge/release workflows require real remotes
//! and are tested manually.

mod common;

use std::fs;
use std::path::Path;

use common::fixtures::WorkspaceBuilder;

/// Helper to append workspace-level release config to the manifest.
fn add_release_config(workspace_root: &Path, release_yaml: &str) {
    let manifest_path = workspace_root
        .join(".gitgrip")
        .join("spaces")
        .join("main")
        .join("gripspace.yml");
    let mut content = fs::read_to_string(&manifest_path).unwrap();
    content.push_str(release_yaml);
    fs::write(&manifest_path, content).unwrap();
}

// ── Version Bump Tests ──────────────────────────────────────────

#[test]
fn test_release_bumps_cargo_toml() {
    let ws = WorkspaceBuilder::new().add_repo("myapp").build();

    // Create a Cargo.toml in the repo
    let cargo_path = ws.repo_path("myapp").join("Cargo.toml");
    fs::write(
        &cargo_path,
        r#"[package]
name = "myapp"
version = "0.1.0"
edition = "2021"
"#,
    )
    .unwrap();

    // Use the internal bump function directly
    let changed = gitgrip::cli::commands::release::bump_cargo_toml(&cargo_path, "0.2.0", false);
    assert!(changed.is_ok());
    assert!(changed.unwrap());

    let content = fs::read_to_string(&cargo_path).unwrap();
    assert!(content.contains(r#"version = "0.2.0""#));
    assert!(!content.contains(r#"version = "0.1.0""#));
}

#[test]
fn test_release_bumps_package_json() {
    let ws = WorkspaceBuilder::new().add_repo("webapp").build();

    let pkg_path = ws.repo_path("webapp").join("package.json");
    fs::write(
        &pkg_path,
        r#"{
  "name": "webapp",
  "version": "1.0.0",
  "description": "A web app"
}"#,
    )
    .unwrap();

    let changed = gitgrip::cli::commands::release::bump_package_json(&pkg_path, "1.1.0", false);
    assert!(changed.is_ok());
    assert!(changed.unwrap());

    let content = fs::read_to_string(&pkg_path).unwrap();
    assert!(content.contains(r#""version": "1.1.0""#));
}

#[test]
fn test_release_updates_changelog() {
    let ws = WorkspaceBuilder::new().add_repo("app").build();

    let changelog_path = ws.workspace_root.join("CHANGELOG.md");
    fs::write(
        &changelog_path,
        "# Changelog\n\n## [v0.1.0] - 2025-01-01\n\n- Initial release\n",
    )
    .unwrap();

    let updated = gitgrip::cli::commands::release::update_changelog(
        &changelog_path,
        "v0.2.0",
        Some("Added new features"),
        false,
    );
    assert!(updated.is_ok());
    assert!(updated.unwrap());

    let content = fs::read_to_string(&changelog_path).unwrap();
    assert!(content.contains("## [v0.2.0]"));
    assert!(content.contains("Added new features"));
    // Old section should still be there
    assert!(content.contains("## [v0.1.0]"));
    // New section should come before old section
    let new_pos = content.find("## [v0.2.0]").unwrap();
    let old_pos = content.find("## [v0.1.0]").unwrap();
    assert!(
        new_pos < old_pos,
        "New version should appear before old version"
    );
}

#[test]
fn test_release_changelog_no_file() {
    let ws = WorkspaceBuilder::new().add_repo("app").build();

    let changelog_path = ws.workspace_root.join("CHANGELOG.md");
    // Don't create the file

    let updated =
        gitgrip::cli::commands::release::update_changelog(&changelog_path, "v0.1.0", None, false);
    assert!(updated.is_ok());
    assert!(!updated.unwrap()); // Should return false (no file to update)
}

// ── Version Validation Tests ────────────────────────────────────

#[test]
fn test_release_normalize_version_valid() {
    let (bare, tag) = gitgrip::cli::commands::release::normalize_version("v1.2.3").unwrap();
    assert_eq!(bare, "1.2.3");
    assert_eq!(tag, "v1.2.3");

    let (bare, tag) = gitgrip::cli::commands::release::normalize_version("0.12.4").unwrap();
    assert_eq!(bare, "0.12.4");
    assert_eq!(tag, "v0.12.4");
}

#[test]
fn test_release_normalize_version_invalid() {
    assert!(gitgrip::cli::commands::release::normalize_version("abc").is_err());
    assert!(gitgrip::cli::commands::release::normalize_version("x.y").is_err());
}

// ── Custom Version File Config Tests ────────────────────────────

#[test]
fn test_release_bump_custom_version_file() {
    let ws = WorkspaceBuilder::new().add_repo("app").build();

    let version_file = ws.repo_path("app").join("VERSION");
    fs::write(&version_file, "APP_VERSION=1.0.0\n").unwrap();

    let changed = gitgrip::cli::commands::release::bump_custom_file(
        &version_file,
        "APP_VERSION={version}",
        "2.0.0",
        false,
    );
    assert!(changed.is_ok());
    assert!(changed.unwrap());

    let content = fs::read_to_string(&version_file).unwrap();
    assert!(content.contains("APP_VERSION=2.0.0"));
    assert!(!content.contains("APP_VERSION=1.0.0"));
}

#[test]
fn test_release_version_file_config_in_manifest() {
    let ws = WorkspaceBuilder::new().add_repo("app").build();

    // Create a version file
    let version_file = ws.repo_path("app").join("version.txt");
    fs::write(&version_file, "version=1.0.0\n").unwrap();

    add_release_config(
        &ws.workspace_root,
        r#"workspace:
  release:
    version_files:
      - path: app/version.txt
        pattern: "version={version}"
"#,
    );

    let manifest = ws.load_manifest();
    let release_config = manifest.workspace.as_ref().and_then(|w| w.release.as_ref());
    assert!(release_config.is_some());

    let version_files = release_config.unwrap().version_files.as_ref().unwrap();
    assert_eq!(version_files.len(), 1);
    assert_eq!(version_files[0].path, "app/version.txt");
    assert_eq!(version_files[0].pattern, "version={version}");
}

#[test]
fn test_release_post_release_hooks_in_manifest() {
    let ws = WorkspaceBuilder::new().add_repo("app").build();

    add_release_config(
        &ws.workspace_root,
        r#"workspace:
  release:
    post_release:
      - command: echo "released {version}"
        name: announce
"#,
    );

    let manifest = ws.load_manifest();
    let release_config = manifest.workspace.as_ref().and_then(|w| w.release.as_ref());
    assert!(release_config.is_some());

    let hooks = release_config.unwrap().post_release.as_ref().unwrap();
    assert_eq!(hooks.len(), 1);
    assert_eq!(hooks[0].command, r#"echo "released {version}""#);
    assert_eq!(hooks[0].name.as_deref(), Some("announce"));
}

// ── Auto-Detection Tests ────────────────────────────────────────

#[test]
fn test_release_auto_detects_cargo_toml() {
    let ws = WorkspaceBuilder::new().add_repo("rustapp").build();
    let manifest = ws.load_manifest();

    // Create a Cargo.toml
    fs::write(
        ws.repo_path("rustapp").join("Cargo.toml"),
        r#"[package]
name = "rustapp"
version = "0.1.0"
"#,
    )
    .unwrap();

    let repos = gitgrip::core::repo::filter_repos(&manifest, &ws.workspace_root, None, None, false);
    let files = gitgrip::cli::commands::release::detect_version_files(&ws.workspace_root, &repos);

    assert!(!files.is_empty());
    assert!(files
        .iter()
        .any(|(name, path)| { name == "rustapp" && path.file_name().unwrap() == "Cargo.toml" }));
}

#[test]
fn test_release_auto_detects_package_json() {
    let ws = WorkspaceBuilder::new().add_repo("jsapp").build();
    let manifest = ws.load_manifest();

    // Create a package.json
    fs::write(
        ws.repo_path("jsapp").join("package.json"),
        r#"{"name":"jsapp","version":"1.0.0"}"#,
    )
    .unwrap();

    let repos = gitgrip::core::repo::filter_repos(&manifest, &ws.workspace_root, None, None, false);
    let files = gitgrip::cli::commands::release::detect_version_files(&ws.workspace_root, &repos);

    assert!(!files.is_empty());
    assert!(files
        .iter()
        .any(|(name, path)| { name == "jsapp" && path.file_name().unwrap() == "package.json" }));
}
