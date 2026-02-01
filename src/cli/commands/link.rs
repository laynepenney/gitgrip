//! Link command implementation
//!
//! Manages copyfile and linkfile entries.

use crate::cli::output::Output;
use crate::core::manifest::Manifest;
use crate::core::repo::RepoInfo;
use crate::git::path_exists;
use std::path::PathBuf;

/// Run the link command
pub fn run_link(
    workspace_root: &PathBuf,
    manifest: &Manifest,
    status: bool,
    apply: bool,
) -> anyhow::Result<()> {
    if status {
        show_link_status(workspace_root, manifest)?;
    } else if apply {
        apply_links(workspace_root, manifest)?;
    } else {
        // Default: show status
        show_link_status(workspace_root, manifest)?;
    }

    Ok(())
}

fn show_link_status(workspace_root: &PathBuf, manifest: &Manifest) -> anyhow::Result<()> {
    Output::header("File Link Status");
    println!();

    let repos: Vec<RepoInfo> = manifest
        .repos
        .iter()
        .filter_map(|(name, config)| RepoInfo::from_config(name, config, workspace_root))
        .collect();

    let mut total_links = 0;
    let mut valid_links = 0;
    let mut broken_links = 0;

    for (name, config) in &manifest.repos {
        let repo = repos.iter().find(|r| &r.name == name);

        // Check copyfiles
        if let Some(ref copyfiles) = config.copyfile {
            for copyfile in copyfiles {
                total_links += 1;
                let source = repo
                    .map(|r| r.absolute_path.join(&copyfile.src))
                    .unwrap_or_else(|| workspace_root.join(&config.path).join(&copyfile.src));
                let dest = workspace_root.join(&copyfile.dest);

                let status = if source.exists() && dest.exists() {
                    valid_links += 1;
                    "✓"
                } else if !source.exists() {
                    broken_links += 1;
                    "✗ (source missing)"
                } else {
                    broken_links += 1;
                    "✗ (dest missing)"
                };

                println!("  [copy] {} -> {} {}", copyfile.src, copyfile.dest, status);
            }
        }

        // Check linkfiles
        if let Some(ref linkfiles) = config.linkfile {
            for linkfile in linkfiles {
                total_links += 1;
                let source = repo
                    .map(|r| r.absolute_path.join(&linkfile.src))
                    .unwrap_or_else(|| workspace_root.join(&config.path).join(&linkfile.src));
                let dest = workspace_root.join(&linkfile.dest);

                let status = if source.exists() && dest.exists() && dest.is_symlink() {
                    valid_links += 1;
                    "✓"
                } else if !source.exists() {
                    broken_links += 1;
                    "✗ (source missing)"
                } else if !dest.exists() {
                    broken_links += 1;
                    "✗ (link missing)"
                } else {
                    broken_links += 1;
                    "✗ (not a symlink)"
                };

                println!("  [link] {} -> {} {}", linkfile.src, linkfile.dest, status);
            }
        }
    }

    println!();
    if total_links == 0 {
        println!("No file links defined in manifest.");
    } else if broken_links == 0 {
        Output::success(&format!("All {} link(s) valid", valid_links));
    } else {
        Output::warning(&format!(
            "{} valid, {} broken out of {} total",
            valid_links, broken_links, total_links
        ));
        println!();
        println!("Run 'gr link --apply' to fix broken links.");
    }

    Ok(())
}

fn apply_links(workspace_root: &PathBuf, manifest: &Manifest) -> anyhow::Result<()> {
    Output::header("Applying File Links");
    println!();

    let repos: Vec<RepoInfo> = manifest
        .repos
        .iter()
        .filter_map(|(name, config)| RepoInfo::from_config(name, config, workspace_root))
        .collect();

    let mut applied = 0;
    let mut errors = 0;

    for (name, config) in &manifest.repos {
        let repo = repos.iter().find(|r| &r.name == name);

        if !repo.map(|r| path_exists(&r.absolute_path)).unwrap_or(false) {
            continue;
        }

        // Apply copyfiles
        if let Some(ref copyfiles) = config.copyfile {
            for copyfile in copyfiles {
                let source = repo
                    .map(|r| r.absolute_path.join(&copyfile.src))
                    .unwrap_or_else(|| workspace_root.join(&config.path).join(&copyfile.src));
                let dest = workspace_root.join(&copyfile.dest);

                if !source.exists() {
                    Output::warning(&format!("Source not found: {:?}", source));
                    errors += 1;
                    continue;
                }

                // Create parent directory if needed
                if let Some(parent) = dest.parent() {
                    std::fs::create_dir_all(parent)?;
                }

                match std::fs::copy(&source, &dest) {
                    Ok(_) => {
                        Output::success(&format!("[copy] {} -> {}", copyfile.src, copyfile.dest));
                        applied += 1;
                    }
                    Err(e) => {
                        Output::error(&format!("Failed to copy: {}", e));
                        errors += 1;
                    }
                }
            }
        }

        // Apply linkfiles
        if let Some(ref linkfiles) = config.linkfile {
            for linkfile in linkfiles {
                let source = repo
                    .map(|r| r.absolute_path.join(&linkfile.src))
                    .unwrap_or_else(|| workspace_root.join(&config.path).join(&linkfile.src));
                let dest = workspace_root.join(&linkfile.dest);

                if !source.exists() {
                    Output::warning(&format!("Source not found: {:?}", source));
                    errors += 1;
                    continue;
                }

                // Create parent directory if needed
                if let Some(parent) = dest.parent() {
                    std::fs::create_dir_all(parent)?;
                }

                // Remove existing link/file if present
                if dest.exists() || dest.is_symlink() {
                    let _ = std::fs::remove_file(&dest);
                }

                #[cfg(unix)]
                {
                    match std::os::unix::fs::symlink(&source, &dest) {
                        Ok(_) => {
                            Output::success(&format!(
                                "[link] {} -> {}",
                                linkfile.src, linkfile.dest
                            ));
                            applied += 1;
                        }
                        Err(e) => {
                            Output::error(&format!("Failed to create symlink: {}", e));
                            errors += 1;
                        }
                    }
                }

                #[cfg(windows)]
                {
                    // On Windows, use junction for directories, symlink for files
                    if source.is_dir() {
                        match std::os::windows::fs::symlink_dir(&source, &dest) {
                            Ok(_) => {
                                Output::success(&format!(
                                    "[link] {} -> {}",
                                    linkfile.src, linkfile.dest
                                ));
                                applied += 1;
                            }
                            Err(e) => {
                                Output::error(&format!("Failed to create symlink: {}", e));
                                errors += 1;
                            }
                        }
                    } else {
                        match std::os::windows::fs::symlink_file(&source, &dest) {
                            Ok(_) => {
                                Output::success(&format!(
                                    "[link] {} -> {}",
                                    linkfile.src, linkfile.dest
                                ));
                                applied += 1;
                            }
                            Err(e) => {
                                Output::error(&format!("Failed to create symlink: {}", e));
                                errors += 1;
                            }
                        }
                    }
                }
            }
        }
    }

    println!();
    if errors == 0 {
        Output::success(&format!("Applied {} link(s)", applied));
    } else {
        Output::warning(&format!("{} applied, {} errors", applied, errors));
    }

    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::core::manifest::{
        CopyFileConfig, LinkFileConfig, ManifestSettings, MergeStrategy, RepoConfig,
    };
    use std::collections::HashMap;
    use tempfile::TempDir;

    fn create_test_manifest(
        copyfiles: Option<Vec<CopyFileConfig>>,
        linkfiles: Option<Vec<LinkFileConfig>>,
    ) -> Manifest {
        let mut repos = HashMap::new();
        repos.insert(
            "test-repo".to_string(),
            RepoConfig {
                url: "git@github.com:user/test-repo.git".to_string(),
                path: "test-repo".to_string(),
                default_branch: "main".to_string(),
                copyfile: copyfiles,
                linkfile: linkfiles,
                platform: None,
                reference: false,
            },
        );

        Manifest {
            version: 1,
            manifest: None,
            repos,
            settings: ManifestSettings {
                pr_prefix: "[cross-repo]".to_string(),
                merge_strategy: MergeStrategy::default(),
            },
            workspace: None,
        }
    }

    #[test]
    fn test_show_link_status_no_links() {
        let temp = TempDir::new().unwrap();
        let manifest = create_test_manifest(None, None);

        // Should not error even with no links
        let result = show_link_status(&temp.path().to_path_buf(), &manifest);
        assert!(result.is_ok());
    }

    #[test]
    fn test_apply_copyfile() {
        let temp = TempDir::new().unwrap();
        let workspace = temp.path().to_path_buf();

        // Create repo directory and source file
        let repo_dir = workspace.join("test-repo");
        std::fs::create_dir_all(&repo_dir).unwrap();
        std::fs::write(repo_dir.join("README.md"), "# Test").unwrap();

        let copyfiles = vec![CopyFileConfig {
            src: "README.md".to_string(),
            dest: "REPO_README.md".to_string(),
        }];

        let manifest = create_test_manifest(Some(copyfiles), None);

        let result = apply_links(&workspace, &manifest);
        assert!(result.is_ok());

        // Verify the file was copied
        let dest_path = workspace.join("REPO_README.md");
        assert!(dest_path.exists());
        let content = std::fs::read_to_string(&dest_path).unwrap();
        assert_eq!(content, "# Test");
    }

    #[test]
    #[cfg(unix)]
    fn test_apply_linkfile() {
        let temp = TempDir::new().unwrap();
        let workspace = temp.path().to_path_buf();

        // Create repo directory and source file
        let repo_dir = workspace.join("test-repo");
        std::fs::create_dir_all(&repo_dir).unwrap();
        std::fs::write(repo_dir.join("config.yaml"), "key: value").unwrap();

        let linkfiles = vec![LinkFileConfig {
            src: "config.yaml".to_string(),
            dest: "linked-config.yaml".to_string(),
        }];

        let manifest = create_test_manifest(None, Some(linkfiles));

        let result = apply_links(&workspace, &manifest);
        assert!(result.is_ok());

        // Verify the symlink was created
        let dest_path = workspace.join("linked-config.yaml");
        assert!(dest_path.exists());
        assert!(dest_path.is_symlink());

        // Verify we can read through the symlink
        let content = std::fs::read_to_string(&dest_path).unwrap();
        assert_eq!(content, "key: value");
    }

    #[test]
    fn test_apply_links_missing_source() {
        let temp = TempDir::new().unwrap();
        let workspace = temp.path().to_path_buf();

        // Create repo directory but NOT the source file
        let repo_dir = workspace.join("test-repo");
        std::fs::create_dir_all(&repo_dir).unwrap();

        let copyfiles = vec![CopyFileConfig {
            src: "nonexistent.txt".to_string(),
            dest: "dest.txt".to_string(),
        }];

        let manifest = create_test_manifest(Some(copyfiles), None);

        // Should succeed but skip the missing file
        let result = apply_links(&workspace, &manifest);
        assert!(result.is_ok());

        // Dest should not exist
        assert!(!workspace.join("dest.txt").exists());
    }

    #[test]
    fn test_apply_links_creates_parent_dirs() {
        let temp = TempDir::new().unwrap();
        let workspace = temp.path().to_path_buf();

        // Create repo directory and source file
        let repo_dir = workspace.join("test-repo");
        std::fs::create_dir_all(&repo_dir).unwrap();
        std::fs::write(repo_dir.join("file.txt"), "content").unwrap();

        let copyfiles = vec![CopyFileConfig {
            src: "file.txt".to_string(),
            dest: "nested/dir/file.txt".to_string(),
        }];

        let manifest = create_test_manifest(Some(copyfiles), None);

        let result = apply_links(&workspace, &manifest);
        assert!(result.is_ok());

        // Verify nested directory was created
        let dest_path = workspace.join("nested/dir/file.txt");
        assert!(dest_path.exists());
    }
}
