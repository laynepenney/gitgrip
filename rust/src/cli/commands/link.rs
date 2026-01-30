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
                let source = repo.map(|r| r.absolute_path.join(&copyfile.src))
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
                let source = repo.map(|r| r.absolute_path.join(&linkfile.src))
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
                let source = repo.map(|r| r.absolute_path.join(&copyfile.src))
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
                let source = repo.map(|r| r.absolute_path.join(&linkfile.src))
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
                            Output::success(&format!("[link] {} -> {}", linkfile.src, linkfile.dest));
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
                                Output::success(&format!("[link] {} -> {}", linkfile.src, linkfile.dest));
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
                                Output::success(&format!("[link] {} -> {}", linkfile.src, linkfile.dest));
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
