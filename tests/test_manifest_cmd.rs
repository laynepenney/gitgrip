//! Integration tests for manifest import and sync commands (Phase 6).

mod common;

use std::fs;
use tempfile::TempDir;

// ── manifest import ──────────────────────────────────────────────

#[test]
fn test_manifest_import_simple() {
    let tmp = TempDir::new().unwrap();
    let xml_path = tmp.path().join("default.xml");
    let output_path = tmp.path().join("manifest.yaml");

    fs::write(
        &xml_path,
        r#"<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="github" fetch="https://github.com/org/" />
  <default remote="github" revision="main" />
  <project name="frontend" path="frontend" />
  <project name="backend" path="backend" />
</manifest>"#,
    )
    .unwrap();

    let result = gitgrip::cli::commands::manifest::run_manifest_import(
        xml_path.to_str().unwrap(),
        Some(output_path.to_str().unwrap()),
    );
    assert!(result.is_ok(), "import should succeed: {:?}", result.err());
    assert!(output_path.exists(), "output YAML should be written");

    let yaml = fs::read_to_string(&output_path).unwrap();
    assert!(
        yaml.contains("frontend"),
        "YAML should contain frontend repo"
    );
    assert!(yaml.contains("backend"), "YAML should contain backend repo");
}

#[test]
fn test_manifest_import_skips_gerrit() {
    let tmp = TempDir::new().unwrap();
    let xml_path = tmp.path().join("default.xml");
    let output_path = tmp.path().join("manifest.yaml");

    fs::write(
        &xml_path,
        r#"<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="github" fetch="https://github.com/org/" />
  <remote name="gerrit" fetch="https://android.googlesource.com/" review="https://android-review.googlesource.com/" />
  <default remote="github" revision="main" />
  <project name="app" path="app" />
  <project name="platform/build" path="build" remote="gerrit" />
</manifest>"#,
    )
    .unwrap();

    let result = gitgrip::cli::commands::manifest::run_manifest_import(
        xml_path.to_str().unwrap(),
        Some(output_path.to_str().unwrap()),
    );
    assert!(result.is_ok(), "import should succeed: {:?}", result.err());

    let yaml = fs::read_to_string(&output_path).unwrap();
    assert!(yaml.contains("app"), "YAML should contain non-Gerrit repo");
}

#[test]
fn test_manifest_import_custom_output() {
    let tmp = TempDir::new().unwrap();
    let xml_path = tmp.path().join("default.xml");
    let custom_output = tmp.path().join("custom").join("out.yaml");

    fs::write(
        &xml_path,
        r#"<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://github.com/test/" />
  <default remote="origin" revision="main" />
  <project name="myrepo" path="myrepo" />
</manifest>"#,
    )
    .unwrap();

    // Create parent dir
    fs::create_dir_all(custom_output.parent().unwrap()).unwrap();

    let result = gitgrip::cli::commands::manifest::run_manifest_import(
        xml_path.to_str().unwrap(),
        Some(custom_output.to_str().unwrap()),
    );
    assert!(
        result.is_ok(),
        "import with custom output should succeed: {:?}",
        result.err()
    );
    assert!(custom_output.exists(), "custom output path should exist");
}

#[test]
fn test_manifest_import_nonexistent() {
    let result = gitgrip::cli::commands::manifest::run_manifest_import(
        "/nonexistent/path/default.xml",
        None,
    );
    assert!(result.is_err(), "import of nonexistent file should fail");
    let err_msg = result.unwrap_err().to_string();
    assert!(
        err_msg.contains("not found"),
        "error should mention not found: {}",
        err_msg
    );
}

// ── manifest sync ──────────────────────────────────────────────

#[test]
fn test_manifest_sync_repo_workspace() {
    let tmp = TempDir::new().unwrap();
    let workspace = tmp.path().join("workspace");
    fs::create_dir_all(&workspace).unwrap();

    // Create .repo/ structure
    let repo_dir = workspace.join(".repo");
    let manifests_dir = repo_dir.join("manifests");
    fs::create_dir_all(&manifests_dir).unwrap();

    // Write XML manifest
    fs::write(
        repo_dir.join("manifest.xml"),
        r#"<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://github.com/org/" />
  <default remote="origin" revision="main" />
  <project name="core" path="core" />
</manifest>"#,
    )
    .unwrap();

    let workspace_path = workspace.to_path_buf();
    let result = gitgrip::cli::commands::manifest::run_manifest_sync(&workspace_path);
    assert!(
        result.is_ok(),
        "manifest sync should succeed: {:?}",
        result.err()
    );

    let yaml_path = manifests_dir.join("manifest.yaml");
    assert!(yaml_path.exists(), "synced YAML should be written");
}

#[test]
fn test_manifest_sync_no_repo_dir() {
    let tmp = TempDir::new().unwrap();
    let workspace = tmp.path().join("workspace");
    fs::create_dir_all(&workspace).unwrap();

    let workspace_path = workspace.to_path_buf();
    let result = gitgrip::cli::commands::manifest::run_manifest_sync(&workspace_path);
    assert!(result.is_err(), "sync without .repo/ should fail");
    let err_msg = result.unwrap_err().to_string();
    assert!(
        err_msg.contains(".repo"),
        "error should mention .repo: {}",
        err_msg
    );
}
