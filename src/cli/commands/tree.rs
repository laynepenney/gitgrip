//! Tree command implementation
//!
//! Manages griptrees (worktree-based parallel workspaces).

use crate::cli::commands::link::run_link;
use crate::cli::output::Output;
use crate::core::griptree::{GriptreeConfig, GriptreePointer, GriptreeRepoInfo};
use crate::core::manifest::Manifest;
use crate::core::repo::RepoInfo;
use crate::git::remote::get_upstream_branch;
use crate::git::{get_current_branch, open_repo, path_exists};
use chrono::Utc;
use std::collections::{HashMap, HashSet};
use std::path::{Path, PathBuf};

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

/// Context for tracking griptree creation progress (for rollback on failure)
struct GriptreeCreationContext {
    /// List of (main_repo_path, worktree_name) for created worktrees
    created_worktrees: Vec<(PathBuf, String)>,
    /// The griptree directory being created
    tree_path: PathBuf,
}

impl GriptreeCreationContext {
    fn new(tree_path: PathBuf) -> Self {
        Self {
            created_worktrees: Vec::new(),
            tree_path,
        }
    }

    fn record_worktree(&mut self, main_repo_path: PathBuf, worktree_name: String) {
        self.created_worktrees.push((main_repo_path, worktree_name));
    }

    fn rollback(&self) {
        // Remove worktrees in reverse order
        for (repo_path, wt_name) in self.created_worktrees.iter().rev() {
            if let Ok(repo) = open_repo(repo_path) {
                if let Ok(wt) = repo.find_worktree(wt_name) {
                    let mut opts = git2::WorktreePruneOptions::new();
                    opts.valid(true);
                    let _ = wt.prune(Some(&mut opts));
                }
            }
        }
        // Remove griptree directory
        let _ = std::fs::remove_dir_all(&self.tree_path);
    }
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

    // Initialize rollback context
    let mut ctx = GriptreeCreationContext::new(tree_path.clone());

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
                Output::error(&format!(
                    "{}: not cloned, skipping - this repo is required",
                    repo.name
                ));
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

        let worktree_path = tree_path.join(&repo.path);
        let spinner = Output::spinner(&format!("{}...", repo.name));

        // For reference repos: try to sync with upstream before creating worktree
        // Sync failure is not fatal - we'll create the worktree with current state
        let sync_warning = if repo.reference {
            match sync_repo_with_upstream(&repo.absolute_path, &repo.default_branch) {
                Ok(_) => None,
                Err(e) => Some(format!("sync skipped: {}", e)),
            }
        } else {
            None
        };

        // Create worktree on the griptree branch (creates branch if needed)
        // Base the new branch off the repo's default branch, not current HEAD
        match create_worktree(
            &repo.absolute_path,
            &worktree_path,
            branch,
            Some(&repo.default_branch),
        ) {
            Ok(_) => {
                // Record for rollback (use sanitized name matching create_worktree)
                let worktree_name = branch.replace('/', "-");
                ctx.record_worktree(repo.absolute_path.clone(), worktree_name.clone());

                // Track original branch for this repo (for merging back later)
                repo_branches.push(GriptreeRepoInfo {
                    name: repo.name.clone(),
                    original_branch: current_branch.clone(),
                    is_reference: repo.reference,
                    worktree_name: Some(worktree_name),
                    worktree_path: Some(worktree_path.to_string_lossy().to_string()),
                    main_repo_path: Some(repo.absolute_path.to_string_lossy().to_string()),
                });

                let status_msg = if repo.reference {
                    if let Some(ref warning) = sync_warning {
                        format!("{}: created on {} ({})", repo.name, branch, warning)
                    } else {
                        format!("{}: synced & created on {}", repo.name, branch)
                    }
                } else {
                    format!(
                        "{}: created on {} (from {})",
                        repo.name, branch, repo.default_branch
                    )
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

    // Initialize state.json for this griptree
    let state_path = tree_gitgrip.join("state.json");
    std::fs::write(&state_path, "{}")?;

    // Create manifest worktree if main workspace has a manifest repo
    let main_manifests_dir = workspace_root.join(".gitgrip").join("manifests");
    let (manifest_branch_option, manifest_worktree_name): (Option<String>, Option<String>) =
        if main_manifests_dir.exists() {
            let main_manifest_git_dir = main_manifests_dir.join(".git");
            if main_manifest_git_dir.exists() {
                // Main workspace has a manifest git repo - create worktree in griptree
                let tree_manifests_dir = tree_gitgrip.join("manifests");
                let manifest_spinner = Output::spinner("manifest");

                match create_manifest_worktree(&main_manifests_dir, &tree_manifests_dir, branch) {
                    Ok(manifest_branch) => {
                        manifest_spinner.finish_with_message(format!(
                            "manifest: created on {}",
                            manifest_branch
                        ));
                        success_count += 1;
                        (Some(manifest_branch.clone()), Some(manifest_branch))
                    }
                    Err(e) => {
                        manifest_spinner.finish_with_message(format!("manifest: failed - {}", e));
                        error_count += 1;
                        (None, None)
                    }
                }
            } else {
                (None, None)
            }
        } else {
            (None, None)
        };

    // Save griptree config in the griptree directory (include upstream mapping)
    let mut repo_upstreams: HashMap<String, String> = HashMap::new();
    for repo in &repos {
        let worktree_path = tree_path.join(&repo.path);
        if !worktree_path.exists() {
            continue;
        }

        let upstream = match open_repo(&worktree_path) {
            Ok(repo_handle) => match get_upstream_branch(&repo_handle, Some(branch)) {
                Ok(Some(name)) => name,
                _ => format!("origin/{}", repo.default_branch),
            },
            Err(_) => format!("origin/{}", repo.default_branch),
        };

        repo_upstreams.insert(repo.name.clone(), upstream);
    }

    let mut griptree_config = GriptreeConfig::new(branch, &tree_path.to_string_lossy());
    griptree_config.repo_upstreams = repo_upstreams;
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
        manifest_worktree_name,
    };
    let pointer_path = tree_path.join(".griptree");
    let pointer_json = serde_json::to_string_pretty(&pointer)?;
    std::fs::write(&pointer_path, pointer_json)?;

    // Add to griptrees list
    // Check if we should rollback due to too many failures BEFORE saving config
    if success_count == 0 && error_count > 0 {
        Output::error("Griptree creation failed - no worktrees were created successfully");
        ctx.rollback();
        anyhow::bail!("Griptree creation failed, rolled back");
    }

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

    // Apply links in the new griptree
    let tree_manifest_path = tree_path
        .join(".gitgrip")
        .join("manifests")
        .join("manifest.yaml");
    if tree_manifest_path.exists() {
        println!();
        if let Ok(tree_manifest) = Manifest::load(&tree_manifest_path) {
            if let Err(e) = run_link(&tree_path, &tree_manifest, false, true) {
                Output::warning(&format!("Failed to apply links: {}", e));
            }
        }
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
    let griptrees: GriptreesList = if config_path.exists() {
        let content = std::fs::read_to_string(&config_path)?;
        serde_json::from_str(&content)?
    } else {
        GriptreesList::default()
    };

    if griptrees.griptrees.is_empty() {
        println!("No griptrees configured.");
    } else {
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
    }

    // Discover unregistered griptrees
    let discovered = discover_legacy_griptrees(workspace_root, &griptrees)?;
    if !discovered.is_empty() {
        println!();
        Output::warning("Found unregistered griptrees:");
        for (path, branch) in &discovered {
            println!("  {} -> {} (unregistered)", branch, path.display());
        }
        println!();
        println!("These griptrees point to this workspace but are not in griptrees.json.");
        println!("You can manually add them to griptrees.json if needed.");
    }

    Ok(())
}

/// Discover legacy/unregistered griptrees that point to this workspace
fn discover_legacy_griptrees(
    workspace_root: &Path,
    registered: &GriptreesList,
) -> anyhow::Result<Vec<(PathBuf, String)>> {
    let mut discovered = Vec::new();

    let parent = match workspace_root.parent() {
        Some(p) => p,
        None => return Ok(discovered),
    };

    // Build set of registered paths for quick lookup
    let registered_paths: HashSet<String> = registered
        .griptrees
        .values()
        .map(|e| e.path.clone())
        .collect();

    // Scan sibling directories
    let entries = match std::fs::read_dir(parent) {
        Ok(e) => e,
        Err(_) => return Ok(discovered),
    };

    for entry in entries.flatten() {
        let path = entry.path();

        if !path.is_dir() {
            continue;
        }
        if path == workspace_root {
            continue;
        }
        if registered_paths.contains(&path.to_string_lossy().to_string()) {
            continue;
        }

        // Check for .griptree pointer file
        let pointer_path = path.join(".griptree");
        if pointer_path.exists() {
            if let Ok(pointer) = GriptreePointer::load(&pointer_path) {
                // Check if it points to this workspace
                if pointer.main_workspace == workspace_root.to_string_lossy() {
                    discovered.push((path, pointer.branch));
                }
            }
        }
    }

    Ok(discovered)
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

    // Load griptree pointer to get worktree info for cleanup
    let pointer_path = tree_path.join(".griptree");
    let pointer = if pointer_path.exists() {
        GriptreePointer::load(&pointer_path).ok()
    } else {
        None
    };

    // Prune each repo's worktree properly before removing directory
    if let Some(ref ptr) = pointer {
        let cleanup_spinner = Output::spinner("Cleaning up worktrees...");

        for repo_info in &ptr.repos {
            // Use stored main_repo_path if available, otherwise fall back to workspace/name
            let main_repo_path = repo_info
                .main_repo_path
                .as_ref()
                .map(PathBuf::from)
                .unwrap_or_else(|| PathBuf::from(&ptr.main_workspace).join(&repo_info.name));

            if let Ok(repo) = open_repo(&main_repo_path) {
                // Use stored worktree name if available, otherwise fall back to original branch
                let wt_name = repo_info
                    .worktree_name
                    .as_deref()
                    .unwrap_or(&repo_info.original_branch);
                prune_worktree(&repo, wt_name);
            }
        }

        // Remove manifest worktree
        if let Some(ref manifest_wt_name) = ptr.manifest_worktree_name {
            let main_manifest_path = PathBuf::from(&ptr.main_workspace)
                .join(".gitgrip")
                .join("manifests");
            if let Ok(repo) = open_repo(&main_manifest_path) {
                prune_worktree(&repo, manifest_wt_name);
            }
        }

        cleanup_spinner.finish_with_message("Worktrees cleaned up");
    }

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

/// Prune a worktree from a repository
fn prune_worktree(repo: &git2::Repository, worktree_name: &str) {
    if let Ok(wt) = repo.find_worktree(worktree_name) {
        let mut opts = git2::WorktreePruneOptions::new();
        opts.valid(true); // Prune even if valid
        let _ = wt.prune(Some(&mut opts));
    }
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
    // Manifest worktrees create from HEAD since there's no "default branch" concept
    let worktree_name = format!("griptree-{}", branch.replace('/', "-"));
    create_worktree(main_manifests_dir, tree_manifests_dir, &worktree_name, None)?;

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
///
/// When creating a new branch, bases it off `base_branch` (e.g., "main") instead of HEAD.
/// This ensures griptrees start from the default branch, not whatever branch the workspace is on.
fn create_worktree(
    repo_path: &PathBuf,
    worktree_path: &PathBuf,
    branch: &str,
    base_branch: Option<&str>,
) -> anyhow::Result<()> {
    let repo = open_repo(repo_path)?;

    // Create parent directory if needed
    if let Some(parent) = worktree_path.parent() {
        std::fs::create_dir_all(parent)?;
    }

    // Sanitize worktree name: git2 uses this as a directory name under
    // .git/worktrees/<name>, so slashes would create nested directories
    // that don't exist. Replace them with dashes.
    let worktree_name = branch.replace('/', "-");

    // Check if branch exists, create if not
    let branch_exists = repo.find_branch(branch, git2::BranchType::Local).is_ok();

    if branch_exists {
        // Add worktree with existing branch
        repo.worktree(
            &worktree_name,
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
        // Create branch from base_branch (default branch) rather than HEAD
        // This ensures griptrees start from a clean state, not from a feature branch
        let base_commit = if let Some(base) = base_branch {
            // Try local branch first, then remote tracking branch
            if let Ok(local_branch) = repo.find_branch(base, git2::BranchType::Local) {
                local_branch.get().peel_to_commit()?
            } else {
                // Try origin/<base>
                let remote_ref = format!("refs/remotes/origin/{}", base);
                repo.revparse_single(&remote_ref)?.peel_to_commit()?
            }
        } else {
            // Fall back to HEAD if no base branch specified
            repo.head()?.peel_to_commit()?
        };

        repo.branch(branch, &base_commit, false)?;

        repo.worktree(
            &worktree_name,
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
fn sync_repo_with_upstream(repo_path: &PathBuf, default_branch: &str) -> anyhow::Result<()> {
    let repo = open_repo(repo_path)?;

    // Fetch from origin main to ensure up-to-date
    let mut remote = repo.find_remote("origin")?;
    remote.fetch(&[default_branch], None, None)?;

    // Reset main worktree HEAD to upstream default branch
    let upstream_ref = format!("refs/remotes/origin/{}", default_branch);
    let upstream_commit = repo.revparse_single(&upstream_ref)?.peel_to_commit()?;
    repo.reset(upstream_commit.as_object(), git2::ResetType::Hard, None)?;

    Ok(())
}
