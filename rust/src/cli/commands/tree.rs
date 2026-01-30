//! Tree command implementation
//!
//! Manages griptrees (worktree-based parallel workspaces).

use crate::cli::output::Output;
use crate::core::griptree::GriptreeConfig;
use crate::core::manifest::Manifest;
use crate::core::repo::RepoInfo;
use crate::git::{open_repo, path_exists};
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

    for repo in &repos {
        if !path_exists(&repo.absolute_path) {
            Output::warning(&format!("{}: not cloned, skipping", repo.name));
            continue;
        }

        let worktree_path = tree_path.join(&repo.path);
        let spinner = Output::spinner(&format!("Creating worktree for {}...", repo.name));

        match create_worktree(&repo.absolute_path, &worktree_path, branch) {
            Ok(_) => {
                spinner.finish_with_message(format!("{}: created", repo.name));
                success_count += 1;
            }
            Err(e) => {
                spinner.finish_with_message(format!("{}: failed - {}", repo.name, e));
                error_count += 1;
            }
        }
    }

    // Create .gitgrip structure in griptree
    let tree_gitgrip = tree_path.join(".gitgrip");
    std::fs::create_dir_all(&tree_gitgrip)?;

    // Save griptree config in the griptree directory
    let griptree_config = GriptreeConfig::new(branch, &tree_path.to_string_lossy());
    let griptree_config_path = tree_gitgrip.join("griptree.json");
    griptree_config.save(&griptree_config_path)?;

    // Add to griptrees list
    griptrees.griptrees.insert(branch.to_string(), GriptreeEntry {
        path: tree_path.to_string_lossy().to_string(),
        branch: branch.to_string(),
        locked: false,
        lock_reason: None,
    });

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
pub fn run_tree_remove(
    workspace_root: &PathBuf,
    branch: &str,
    force: bool,
) -> anyhow::Result<()> {
    Output::header(&format!("Removing griptree for '{}'", branch));
    println!();

    let config_path = workspace_root.join(".gitgrip").join("griptrees.json");
    if !config_path.exists() {
        anyhow::bail!("No griptrees configured");
    }

    let content = std::fs::read_to_string(&config_path)?;
    let mut griptrees: GriptreesList = serde_json::from_str(&content)?;

    let entry = griptrees.griptrees.get(branch)
        .ok_or_else(|| anyhow::anyhow!("Griptree '{}' not found", branch))?;

    if entry.locked && !force {
        anyhow::bail!(
            "Griptree '{}' is locked{}. Use --force to remove anyway.",
            branch,
            entry.lock_reason.as_ref().map(|r| format!(": {}", r)).unwrap_or_default()
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

    let entry = griptrees.griptrees.get_mut(branch)
        .ok_or_else(|| anyhow::anyhow!("Griptree '{}' not found", branch))?;

    entry.locked = true;
    entry.lock_reason = reason.map(|s| s.to_string());

    let config_json = serde_json::to_string_pretty(&griptrees)?;
    std::fs::write(&config_path, config_json)?;

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

    let entry = griptrees.griptrees.get_mut(branch)
        .ok_or_else(|| anyhow::anyhow!("Griptree '{}' not found", branch))?;

    entry.locked = false;
    entry.lock_reason = None;

    let config_json = serde_json::to_string_pretty(&griptrees)?;
    std::fs::write(&config_path, config_json)?;

    Output::success(&format!("Griptree '{}' unlocked", branch));
    Ok(())
}

/// Create a git worktree
fn create_worktree(repo_path: &PathBuf, worktree_path: &PathBuf, branch: &str) -> anyhow::Result<()> {
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
            Some(git2::WorktreeAddOptions::new().reference(
                Some(&repo.find_branch(branch, git2::BranchType::Local)?.into_reference())
            )),
        )?;
    } else {
        // Create branch and worktree
        let head = repo.head()?;
        let commit = head.peel_to_commit()?;
        repo.branch(branch, &commit, false)?;

        repo.worktree(
            branch,
            worktree_path,
            Some(git2::WorktreeAddOptions::new().reference(
                Some(&repo.find_branch(branch, git2::BranchType::Local)?.into_reference())
            )),
        )?;
    }

    Ok(())
}
