//! Tree command implementation
//!
//! Manages griptrees (worktree-based parallel workspaces).

use crate::cli::output::Output;
use crate::core::griptree::{GriptreeConfig, GriptreePointer, GriptreeRepoInfo};
use crate::core::manifest::Manifest;
use crate::core::repo::RepoInfo;
use crate::git::{get_current_branch, open_repo, path_exists};
use chrono::Utc;
use std::collections::HashMap;
use std::path::PathBuf;

/// Griptrees list file structure
#[derive(Debug, Clone, Default, serde::Serialize, serde::Deserialize)]
struct GriptreesList {
    griptrees: HashMap<String, GriptreeEntry>,
}

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
struct GriptreeEntry {
    path: String,
    branch: String,
    locked: bool,
    lock_reason: Option<String>,
}

/// Run tree add command
pub fn run_tree_add(
    workspace_root: &PathBuf,
    manifest: &Manifest,
    branch: &str,
) -> anyhow::Result<()> {
    Output::header(&format!("Creating griptree for branch '{}'", branch));
    println!();

    // Load or create griptrees list
    let config_path = workspace_root.join(".gitgrip").join("griptrees.json");
    let mut griptrees: GriptreesList = if config_path.exists() {
        let content = std::fs::read_to_string(&config_path)?;
        serde_json::from_str(&content)?
    } else {
        GriptreesList::default()
    };

    // Check if griptree already exists
    if griptrees.griptrees.contains_key(branch) {
        anyhow::bail!("Griptree for '{}' already exists", branch);
    }

    // Calculate griptree path (sibling to workspace)
    let tree_name = branch.replace('/', "-");
    let tree_path = workspace_root
        .parent()
        .ok_or_else(|| anyhow::anyhow!("Cannot determine parent directory"))?
        .join(&tree_name);

    if tree_path.exists() {
        anyhow::bail!("Directory already exists: {:?}", tree_path);
    }

    // Create griptree directory
    std::fs::create_dir_all(&tree_path)?;

    // Get all repos
    let repos: Vec<RepoInfo> = manifest
        .repos
        .iter()
        .filter_map(|(name, config)| RepoInfo::from_config(name, config, workspace_root))
        .collect();

    let mut success_count = 0;
    let mut error_count = 0;

    // Track original branches for each repo
    let mut repo_branches: Vec<GriptreeRepoInfo> = Vec::new();

    for repo in &repos {
        if !path_exists(&repo.absolute_path) {
            if repo.name == "opencode" {
                Output::error(&format!("{}: not cloned, skipping - this repo is required", repo.name));
            } else {
                Output::warning(&format!("{}: not cloned, skipping", repo.name));
            }
            continue;
        }

        // Get current branch from main workspace
        let git_repo = match open_repo(&repo.absolute_path) {
            Ok(r) => r,
            Err(e) => {
                Output::warning(&format!("{}: failed to open - {}", repo.name, e));
                continue;
            }
        };

        let current_branch = match get_current_branch(&git_repo) {
            Ok(b) => b,
            Err(e) => {
                Output::warning(&format!("{}: failed to get branch - {}", repo.name, e));
                continue;
            }
        };

        // Track original branch for this repo
        repo_branches.push(GriptreeRepoInfo {
            name: repo.name.clone(),
            original_branch: current_branch.clone(),
            is_reference: repo.reference,
        });

        let worktree_path = tree_path.join(&repo.path);
        let spinner = Output::spinner(&format!("{}...", repo.name));

        // For reference repos: sync with upstream before creating worktree
        if repo.reference {
            if let Err(e) = sync_repo_with_upstream(&repo.absolute_path, &repo.default_branch) {
                spinner.finish_with_message(format!("{}: sync failed - {}", repo.name, e));
                error_count += 1;
                continue;
            }
        }

        // Create worktree on current branch (not griptree branch)
        match create_worktree(&repo.absolute_path, &worktree_path, &current_branch) {
            Ok(_) => {
                let status_msg = if repo.reference {
                    format!("{}: synced & created", repo.name)
                } else {
                    format!("{}: created on {}", repo.name, current_branch)
                };
                spinner.finish_with_message(status_msg);
                success_count += 1;
            }
            Err(e) => {
                spinner.finish_with_message(format!("{}: failed - {}", repo.name, e));
                error_count += 1;
            }
        }
    }



    // Create .griptree structure in griptree
    let tree_gitgrip = tree_path.join(".gitgrip");
    std::fs::create_dir_all(&tree_gitgrip)?;

    // Create manifest worktree if main workspace has a manifest repo
    let main_manifests_dir = workspace_root.join(".gitgrip").join("manifests");
    let manifest_branch_option: Option<String> = if main_manifests_dir.exists() {
        let main_manifest_git_dir = main_manifests_dir.join(".git");
        if main_manifest_git_dir.exists() {
            // Main workspace has a manifest git repo - create worktree in griptree
            let tree_manifests_dir = tree_gitgrip.join("manifests");
            let manifest_spinner = Output::spinner("manifest");

            match create_manifest_worktree(
                &main_manifests_dir,
                &tree_manifests_dir,
                branch,
            ) {
                Ok(manifest_branch) => {
                    manifest_spinner.finish_with_message(format!(
                        "manifest: created on {}",
                        manifest_branch
                    ));
                    success_count += 1;
                    Some(manifest_branch)
                }
                Err(e) => {
                    manifest_spinner.finish_with_message(format!("manifest: failed - {}", e));
                    error_count += 1;
                    None
                }
            }
        } else {
            None
        }
    } else {
        None
    };

    // Save griptree config in the griptree directory
    let griptree_config = GriptreeConfig::new(branch, &tree_path.to_string_lossy());
    let griptree_config_path = tree_gitgrip.join("griptree.json");
    griptree_config.save(&griptree_config_path)?;

    // Create .griptree pointer file at root of griptree
    // This allows `gr status` to detect when running from within a griptree
    let pointer = GriptreePointer {
        main_workspace: workspace_root.to_string_lossy().to_string(),
        branch: branch.to_string(),
        locked: false,
        created_at: Some(Utc::now()),
        repos: repo_branches,
        manifest_branch: manifest_branch_option,
    };
    let pointer_path = tree_path.join(".griptree");
    let pointer_json = serde_json::to_string_pretty(&pointer)?;
    std::fs::write(&pointer_path, pointer_json)?;

    // Add to griptrees list
    griptrees.griptrees.insert(
        branch.to_string(),
        GriptreeEntry {
            path: tree_path.to_string_lossy().to_string(),
            branch: branch.to_string(),
            locked: false,
            lock_reason: None,
        },
    );

    // Save griptrees list
    let config_json = serde_json::to_string_pretty(&griptrees)?;
    std::fs::write(&config_path, config_json)?;

    println!();
    if error_count == 0 {
        Output::success(&format!(
            "Griptree created at {:?} with {} repo(s)",
            tree_path, success_count
        ));
    } else {
        Output::warning(&format!(
            "Griptree created with {} success, {} errors",
            success_count, error_count
        ));
    }

    println!();
    println!("To use the griptree:");
    println!("  cd {:?}", tree_path);

    Ok(())
}

/// Run tree list command
pub fn run_tree_list(workspace_root: &PathBuf) -> anyhow::Result<()> {
    Output::header("Griptrees");
    println!();

    let config_path = workspace_root.join(".gitgrip").join("griptrees.json");
    if !config_path.exists() {
        println!("No griptrees configured.");
        return Ok(());
    }

    let content = std::fs::read_to_string(&config_path)?;
    let griptrees: GriptreesList = serde_json::from_str(&content)?;

    if griptrees.griptrees.is_empty() {
        println!("No griptrees configured.");
        return Ok(());
    }

    for (branch, entry) in &griptrees.griptrees {
        let exists = PathBuf::from(&entry.path).exists();
        let status = if !exists {
            " (missing)"
        } else if entry.locked {
            " (locked)"
        } else {
            ""
        };

        println!("  {} -> {}{}", branch, entry.path, status);
        if let Some(ref reason) = entry.lock_reason {
            println!("    Lock reason: {}", reason);
        }
    }

    Ok(())
}

/// Run tree remove command
pub fn run_tree_remove(workspace_root: &PathBuf, branch: &str, force: bool) -> anyhow::Result<()> {
    Output::header(&format!("Removing griptree for '{}'", branch));
    println!();

    let config_path = workspace_root.join(".gitgrip").join("griptrees.json");
    if !config_path.exists() {
        anyhow::bail!("No griptrees configured");
    }

    let content = std::fs::read_to_string(&config_path)?;
    let mut griptrees: GriptreesList = serde_json::from_str(&content)?;

    let entry = griptrees
        .griptrees
        .get(branch)
        .ok_or_else(|| anyhow::anyhow!("Griptree '{}' not found", branch))?;

    if entry.locked && !force {
        anyhow::bail!(
            "Griptree '{}' is locked{}. Use --force to remove anyway.",
            branch,
            entry
                .lock_reason
                .as_ref()
                .map(|r| format!(": {}", r))
                .unwrap_or_default()
        );
    }

    let tree_path = PathBuf::from(&entry.path);

    // Remove directory
    if tree_path.exists() {
        let spinner = Output::spinner("Removing griptree directory...");
        std::fs::remove_dir_all(&tree_path)?;
        spinner.finish_with_message("Directory removed");
    }

    // Update griptrees list
    griptrees.griptrees.remove(branch);
    let config_json = serde_json::to_string_pretty(&griptrees)?;
    std::fs::write(&config_path, config_json)?;

    Output::success(&format!("Griptree '{}' removed", branch));
    Ok(())
}

/// Run tree lock command
pub fn run_tree_lock(
    workspace_root: &PathBuf,
    branch: &str,
    reason: Option<&str>,
) -> anyhow::Result<()> {
    let config_path = workspace_root.join(".gitgrip").join("griptrees.json");
    if !config_path.exists() {
        anyhow::bail!("No griptrees configured");
    }

    let content = std::fs::read_to_string(&config_path)?;
    let mut griptrees: GriptreesList = serde_json::from_str(&content)?;

    let entry = griptrees
        .griptrees
        .get_mut(branch)
        .ok_or_else(|| anyhow::anyhow!("Griptree '{}' not found", branch))?;

    entry.locked = true;
    entry.lock_reason = reason.map(|s| s.to_string());
    let entry_path = entry.path.clone();

    let config_json = serde_json::to_string_pretty(&griptrees)?;
    std::fs::write(&config_path, config_json)?;

    // Update .griptree pointer file if it exists
    let pointer_path = PathBuf::from(&entry_path).join(".griptree");
    if pointer_path.exists() {
        if let Ok(mut pointer) = GriptreePointer::load(&pointer_path) {
            pointer.locked = true;
            let pointer_json = serde_json::to_string_pretty(&pointer)?;
            std::fs::write(&pointer_path, pointer_json)?;
        }
    }

    Output::success(&format!("Griptree '{}' locked", branch));
    Ok(())
}

/// Run tree unlock command
pub fn run_tree_unlock(workspace_root: &PathBuf, branch: &str) -> anyhow::Result<()> {
    let config_path = workspace_root.join(".gitgrip").join("griptrees.json");
    if !config_path.exists() {
        anyhow::bail!("No griptrees configured");
    }

    let content = std::fs::read_to_string(&config_path)?;
    let mut griptrees: GriptreesList = serde_json::from_str(&content)?;

    let entry = griptrees
        .griptrees
        .get_mut(branch)
        .ok_or_else(|| anyhow::anyhow!("Griptree '{}' not found", branch))?;

    entry.locked = false;
    entry.lock_reason = None;
    let entry_path = entry.path.clone();

    let config_json = serde_json::to_string_pretty(&griptrees)?;
    std::fs::write(&config_path, config_json)?;

    // Update .griptree pointer file if it exists
    let pointer_path = PathBuf::from(&entry_path).join(".griptree");
    if pointer_path.exists() {
        if let Ok(mut pointer) = GriptreePointer::load(&pointer_path) {
            pointer.locked = false;
            let pointer_json = serde_json::to_string_pretty(&pointer)?;
            std::fs::write(&pointer_path, pointer_json)?;
        }
    }

    Output::success(&format!("Griptree '{}' unlocked", branch));
    Ok(())
}

/// Create manifest worktree for a griptree
fn create_manifest_worktree(
    main_manifests_dir: &PathBuf,
    tree_manifests_dir: &PathBuf,
    branch: &str,
) -> anyhow::Result<String> {
    let repo = open_repo(main_manifests_dir)?;

    // Get current branch from main manifests (unused but kept for context)
    let _current_branch = get_current_branch(&repo)?;

    // Create worktree at griptree's .gitgrip/manifests/
    // Use the griptree branch name for the manifest worktree
    let worktree_name = format!("griptree-{}", branch.replace('/', "-"));
    create_worktree(main_manifests_dir, tree_manifests_dir, &worktree_name)?;

    // Check if manifest.yaml exists in the new worktree
    let manifest_yaml = tree_manifests_dir.join("manifest.yaml");
    if !manifest_yaml.exists() {
        // Copy manifest.yaml from main if it doesn't exist
        let main_manifest = main_manifests_dir.join("manifest.yaml");
        if main_manifest.exists() {
            std::fs::copy(&main_manifest, &manifest_yaml)?;
        }
    }

    Ok(worktree_name)
}
/// Create a git worktree using git2
fn create_worktree(
    repo_path: &PathBuf,
    worktree_path: &PathBuf,
    branch: &str,
) -> anyhow::Result<()> {
    let repo = open_repo(repo_path)?;

    // Create parent directory if needed
    if let Some(parent) = worktree_path.parent() {
        std::fs::create_dir_all(parent)?;
    }

    // Check if branch exists, create if not
    let branch_exists = repo.find_branch(branch, git2::BranchType::Local).is_ok();

    if branch_exists {
        // Add worktree with existing branch
        repo.worktree(
            branch,
            worktree_path,
            Some(
                git2::WorktreeAddOptions::new().reference(Some(
                    &repo
                        .find_branch(branch, git2::BranchType::Local)?
                        .into_reference(),
                )),
            ),
        )?;
    } else {
        // Create branch and worktree
        let head = repo.head()?;
        let commit = head.peel_to_commit()?;
        repo.branch(branch, &commit, false)?;

        repo.worktree(
            branch,
            worktree_path,
            Some(
                git2::WorktreeAddOptions::new().reference(Some(
                    &repo
                        .find_branch(branch, git2::BranchType::Local)?
                        .into_reference(),
                )),
            ),
        )?;
    }

    Ok(())
}

/// Sync reference repo with upstream default branch
fn sync_repo_with_upstream(
    repo_path: &PathBuf,
    default_branch: &str,
) -> anyhow::Result<()> {
    let repo = open_repo(repo_path)?;
    
    // Fetch from origin main to ensure up-to-date
    let mut remote = repo.find_remote("origin")?;
    remote.fetch(&[default_branch], None, None)?;
    
    // Reset main worktree HEAD to upstream default branch
    let upstream_ref = format!("refs/remotes/origin/{}", default_branch);
    let upstream_commit = repo.revparse_single(&upstream_ref)?.peel_to_commit()?;
    repo.reset(&upstream_commit.as_object(), git2::ResetType::Hard, None)?;
    
    Ok(())
}
