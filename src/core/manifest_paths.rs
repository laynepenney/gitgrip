//! Workspace manifest path/layout helpers.
//!
//! Supports both:
//! - New layout: `.gitgrip/spaces/main/gripspace.yml`
//! - Legacy layout: `.gitgrip/manifests/manifest.yaml`

use std::path::{Path, PathBuf};

pub const MAIN_SPACE_DIR: &str = ".gitgrip/spaces/main";
pub const LOCAL_SPACE_DIR: &str = ".gitgrip/spaces/local";
pub const LEGACY_MANIFEST_DIR: &str = ".gitgrip/manifests";
pub const PRIMARY_FILE_NAME: &str = "gripspace.yml";
pub const LEGACY_FILE_NAMES: [&str; 2] = ["manifest.yaml", "manifest.yml"];

pub fn main_space_dir(workspace_root: &Path) -> PathBuf {
    workspace_root.join(MAIN_SPACE_DIR)
}

pub fn local_space_dir(workspace_root: &Path) -> PathBuf {
    workspace_root.join(LOCAL_SPACE_DIR)
}

pub fn legacy_manifest_dir(workspace_root: &Path) -> PathBuf {
    workspace_root.join(LEGACY_MANIFEST_DIR)
}

pub fn default_workspace_manifest_path(workspace_root: &Path) -> PathBuf {
    main_space_dir(workspace_root).join(PRIMARY_FILE_NAME)
}

pub fn default_local_manifest_path(workspace_root: &Path) -> PathBuf {
    local_space_dir(workspace_root).join(PRIMARY_FILE_NAME)
}

pub fn resolve_manifest_file_in_dir(dir: &Path) -> Option<PathBuf> {
    let primary = dir.join(PRIMARY_FILE_NAME);
    if primary.exists() {
        return Some(primary);
    }

    for legacy in LEGACY_FILE_NAMES {
        let path = dir.join(legacy);
        if path.exists() {
            return Some(path);
        }
    }

    None
}

pub fn resolve_workspace_manifest_path(workspace_root: &Path) -> Option<PathBuf> {
    let new_dir = main_space_dir(workspace_root);
    if let Some(path) = resolve_manifest_file_in_dir(&new_dir) {
        return Some(path);
    }

    let legacy_dir = legacy_manifest_dir(workspace_root);
    resolve_manifest_file_in_dir(&legacy_dir)
}

pub fn resolve_repo_manifest_path(workspace_root: &Path) -> Option<PathBuf> {
    let repo_manifests_dir = workspace_root.join(".repo").join("manifests");
    resolve_manifest_file_in_dir(&repo_manifests_dir)
}

pub fn resolve_manifest_repo_dir(workspace_root: &Path) -> Option<PathBuf> {
    let new_dir = main_space_dir(workspace_root);
    if new_dir.join(".git").exists() {
        return Some(new_dir);
    }

    let legacy_dir = legacy_manifest_dir(workspace_root);
    if legacy_dir.join(".git").exists() {
        return Some(legacy_dir);
    }

    None
}

pub fn resolve_manifest_content_dir(workspace_root: &Path) -> PathBuf {
    if let Some(repo_dir) = resolve_manifest_repo_dir(workspace_root) {
        return repo_dir;
    }

    let new_dir = main_space_dir(workspace_root);
    if new_dir.exists() {
        return new_dir;
    }

    let legacy_dir = legacy_manifest_dir(workspace_root);
    if legacy_dir.exists() {
        return legacy_dir;
    }

    main_space_dir(workspace_root)
}

fn same_file_path(a: &Path, b: &Path) -> bool {
    if a == b {
        return true;
    }

    match (std::fs::canonicalize(a), std::fs::canonicalize(b)) {
        (Ok(a_canon), Ok(b_canon)) => a_canon == b_canon,
        _ => false,
    }
}

pub fn sync_legacy_mirror_if_present(
    workspace_root: &Path,
    updated_manifest_path: &Path,
    content: &str,
) -> std::io::Result<()> {
    let legacy_primary = legacy_manifest_dir(workspace_root).join(LEGACY_FILE_NAMES[0]);
    let legacy_alt = legacy_manifest_dir(workspace_root).join(LEGACY_FILE_NAMES[1]);

    if same_file_path(updated_manifest_path, &legacy_primary)
        || same_file_path(updated_manifest_path, &legacy_alt)
    {
        return Ok(());
    }

    if legacy_primary.exists() {
        std::fs::write(legacy_primary, content)?;
    } else if legacy_alt.exists() {
        std::fs::write(legacy_alt, content)?;
    }

    Ok(())
}

pub fn resolve_manifest_path_for_update(workspace_root: &Path) -> Option<PathBuf> {
    if let Some(path) = resolve_workspace_manifest_path(workspace_root) {
        return Some(path);
    }

    if let Some(dir) = resolve_manifest_repo_dir(workspace_root) {
        return Some(dir.join(PRIMARY_FILE_NAME));
    }

    None
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    #[test]
    fn resolve_workspace_manifest_prefers_new_layout() {
        let tmp = TempDir::new().unwrap();
        let root = tmp.path();

        let new_dir = main_space_dir(root);
        let legacy_dir = legacy_manifest_dir(root);
        std::fs::create_dir_all(&new_dir).unwrap();
        std::fs::create_dir_all(&legacy_dir).unwrap();
        let new_path = new_dir.join(PRIMARY_FILE_NAME);
        let legacy_path = legacy_dir.join("manifest.yaml");
        std::fs::write(
            &new_path,
            "version: 1\nrepos:\n  a:\n    url: x\n    path: a\n",
        )
        .unwrap();
        std::fs::write(
            &legacy_path,
            "version: 1\nrepos:\n  b:\n    url: y\n    path: b\n",
        )
        .unwrap();

        assert_eq!(resolve_workspace_manifest_path(root), Some(new_path));
    }

    #[test]
    fn resolve_workspace_manifest_falls_back_to_legacy() {
        let tmp = TempDir::new().unwrap();
        let root = tmp.path();

        let legacy_dir = legacy_manifest_dir(root);
        std::fs::create_dir_all(&legacy_dir).unwrap();
        let legacy_path = legacy_dir.join("manifest.yaml");
        std::fs::write(
            &legacy_path,
            "version: 1\nrepos:\n  b:\n    url: y\n    path: b\n",
        )
        .unwrap();

        assert_eq!(resolve_workspace_manifest_path(root), Some(legacy_path));
    }

    #[test]
    fn resolve_manifest_repo_dir_prefers_new_git_repo() {
        let tmp = TempDir::new().unwrap();
        let root = tmp.path();

        let new_dir = main_space_dir(root);
        let legacy_dir = legacy_manifest_dir(root);
        std::fs::create_dir_all(new_dir.join(".git")).unwrap();
        std::fs::create_dir_all(legacy_dir.join(".git")).unwrap();

        assert_eq!(resolve_manifest_repo_dir(root), Some(new_dir));
    }

    #[test]
    fn resolve_manifest_content_dir_prefers_git_repo_dir() {
        let tmp = TempDir::new().unwrap();
        let root = tmp.path();
        let new_dir = main_space_dir(root);
        let legacy_dir = legacy_manifest_dir(root);
        std::fs::create_dir_all(&new_dir).unwrap();
        std::fs::create_dir_all(legacy_dir.join(".git")).unwrap();

        assert_eq!(resolve_manifest_content_dir(root), legacy_dir);
    }

    #[test]
    fn resolve_manifest_path_for_update_uses_existing_file() {
        let tmp = TempDir::new().unwrap();
        let root = tmp.path();
        let new_dir = main_space_dir(root);
        std::fs::create_dir_all(&new_dir).unwrap();
        let path = new_dir.join(PRIMARY_FILE_NAME);
        std::fs::write(&path, "version: 1\nrepos:\n  a:\n    url: x\n    path: a\n").unwrap();

        assert_eq!(resolve_manifest_path_for_update(root), Some(path));
    }

    #[test]
    fn sync_legacy_mirror_updates_existing_legacy_file() {
        let tmp = TempDir::new().unwrap();
        let root = tmp.path();
        let new_dir = main_space_dir(root);
        let legacy_dir = legacy_manifest_dir(root);
        std::fs::create_dir_all(&new_dir).unwrap();
        std::fs::create_dir_all(&legacy_dir).unwrap();
        let updated = new_dir.join(PRIMARY_FILE_NAME);
        let legacy = legacy_dir.join("manifest.yaml");
        std::fs::write(&updated, "new").unwrap();
        std::fs::write(&legacy, "old").unwrap();

        sync_legacy_mirror_if_present(root, &updated, "content").unwrap();
        assert_eq!(std::fs::read_to_string(legacy).unwrap(), "content");
    }

    #[test]
    fn sync_legacy_mirror_skips_same_file_when_path_lexically_differs() {
        let tmp = TempDir::new().unwrap();
        let root = tmp.path();
        let legacy_dir = legacy_manifest_dir(root);
        std::fs::create_dir_all(&legacy_dir).unwrap();
        let legacy = legacy_dir.join("manifest.yaml");
        std::fs::write(&legacy, "original").unwrap();

        let updated = legacy_dir.join(".").join("manifest.yaml");
        sync_legacy_mirror_if_present(root, &updated, "new-content").unwrap();

        // Should not rewrite when updated path points to the same file.
        assert_eq!(std::fs::read_to_string(legacy).unwrap(), "original");
    }
}
