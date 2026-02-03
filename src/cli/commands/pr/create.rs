//! PR create command implementation

use crate::cli::output::Output;
use crate::core::manifest::{Manifest, PlatformType};
use crate::core::repo::RepoInfo;
use crate::core::state::StateFile;
use crate::git::{get_current_branch, open_repo, path_exists};
use crate::platform::{detect_platform, get_platform_adapter};
use git2::Repository;
use std::path::PathBuf;

/// Run the PR create command
pub async fn run_pr_create(
    workspace_root: &PathBuf,
    manifest: &Manifest,
    title: Option<&str>,
    body: Option<&str>,
    draft: bool,
    push_first: bool,
    dry_run: bool,
) -> anyhow::Result<()> {
    if dry_run {
        Output::header("PR Preview");
        println!();
    } else {
        Output::header("Creating pull requests...");
        println!();
    }

    let repos: Vec<RepoInfo> = manifest
        .repos
        .iter()
        .filter_map(|(name, config)| RepoInfo::from_config(name, config, workspace_root))
        .filter(|r| !r.reference) // Skip reference repos
        .collect();

    // Get current branch for all repos and verify consistency
    let mut branch_name: Option<String> = None;
    let mut repos_with_changes: Vec<RepoInfo> = Vec::new();

    for repo in &repos {
        if !path_exists(&repo.absolute_path) {
            continue;
        }

        match open_repo(&repo.absolute_path) {
            Ok(git_repo) => {
                let current = match get_current_branch(&git_repo) {
                    Ok(b) => b,
                    Err(_) => continue,
                };

                // Skip if on default branch
                if current == repo.default_branch {
                    continue;
                }

                // Check for changes ahead of default branch
                if has_commits_ahead(&git_repo, &current, &repo.default_branch)? {
                    if let Some(ref bn) = branch_name {
                        if bn != &current {
                            anyhow::bail!(
                                "Repositories are on different branches: {} vs {}",
                                bn,
                                current
                            );
                        }
                    } else {
                        branch_name = Some(current);
                    }
                    repos_with_changes.push(repo.clone());
                }
            }
            Err(e) => Output::error(&format!("{}: {}", repo.name, e)),
        }
    }

    // Also check the manifest repo for changes
    if let Some(manifest_config) = &manifest.manifest {
        let manifests_dir = workspace_root.join(".gitgrip").join("manifests");

        // Only process if manifest repo exists and has a git directory
        if !manifests_dir.join(".git").exists() || !path_exists(&manifests_dir) {
            // No manifest git repo found - skip
        } else if let Some(manifest_repo) =
            create_manifest_repo_info(manifest_config, &manifests_dir, workspace_root)
        {
            // Check if manifest repo has changes
            match check_repo_for_changes(&manifest_repo, &mut branch_name) {
                Ok(true) => {
                    repos_with_changes.push(manifest_repo);
                }
                Ok(false) => {
                    // No changes or on default branch - skip
                }
                Err(e) => {
                    Output::warning(&format!("Could not check manifest repo: {}", e));
                }
            }
        }
    }

    let branch = match branch_name {
        Some(b) => b,
        None => {
            println!("No repositories have changes to create PRs for.");
            return Ok(());
        }
    };

    // Get title from argument or use branch name as fallback
    let pr_title = title.map(|s| s.to_string()).unwrap_or_else(|| {
        // Convert branch name to title: feat/my-feature -> My feature
        let title = branch
            .trim_start_matches("feat/")
            .trim_start_matches("fix/")
            .trim_start_matches("chore/")
            .replace(['-', '_'], " ");
        let mut chars = title.chars();
        match chars.next() {
            None => title,
            Some(first) => first.to_uppercase().collect::<String>() + chars.as_str(),
        }
    });

    // Push if requested (skip for preview)
    if push_first && !dry_run {
        Output::info("Pushing branches first...");
        for repo in &repos_with_changes {
            if let Ok(git_repo) = open_repo(&repo.absolute_path) {
                let spinner = Output::spinner(&format!("Pushing {}...", repo.name));
                match crate::git::remote::push_branch(&git_repo, &branch, "origin", true) {
                    Ok(()) => spinner.finish_with_message(format!("{}: pushed", repo.name)),
                    Err(e) => {
                        spinner.finish_with_message(format!("{}: push failed - {}", repo.name, e))
                    }
                }
            }
        }
        println!();
    }

    // Preview mode: show what would be created
    if dry_run {
        Output::info(&format!("Branch: {}", branch));
        Output::info(&format!("Title: {}", pr_title));
        if let Some(pr_body) = body {
            Output::info(&format!("Body: {}", pr_body));
        }
        if draft {
            Output::info("Type: Draft PR");
        }
        println!();

        Output::subheader("Repositories that would create PRs:");
        for repo in &repos_with_changes {
            println!("  - {} ({}/{})", repo.name, repo.owner, repo.repo);
        }
        println!();
        Output::warning("Run without --dry-run to actually create the PRs.");
        return Ok(());
    }

    // Create PRs for each repo
    let mut created_prs: Vec<(String, u64, String)> = Vec::new(); // (repo_name, pr_number, url)

    for repo in &repos_with_changes {
        let platform_type = detect_platform(&repo.url);
        let platform = get_platform_adapter(platform_type, None);

        let spinner = Output::spinner(&format!("Creating PR for {}...", repo.name));

        match platform
            .create_pull_request(
                &repo.owner,
                &repo.repo,
                &branch,
                &repo.default_branch,
                &pr_title,
                body,
                draft,
            )
            .await
        {
            Ok(pr) => {
                spinner.finish_with_message(format!(
                    "{}: created PR #{} - {}",
                    repo.name, pr.number, pr.url
                ));
                created_prs.push((repo.name.clone(), pr.number, pr.url.clone()));
            }
            Err(e) => {
                spinner.finish_with_message(format!("{}: failed - {}", repo.name, e));
            }
        }
    }

    // Save state
    if !created_prs.is_empty() {
        let state_path = workspace_root.join(".gitgrip").join("state.json");
        let mut state = if state_path.exists() {
            let content = std::fs::read_to_string(&state_path)?;
            StateFile::parse(&content).unwrap_or_default()
        } else {
            StateFile::default()
        };

        // Use the first PR number for branch mapping
        if let Some((_, first_pr_number, _)) = created_prs.first() {
            state.set_pr_for_branch(&branch, *first_pr_number);
        }

        let state_json = serde_json::to_string_pretty(&state)?;
        std::fs::write(&state_path, state_json)?;
    }

    // Summary
    println!();
    if created_prs.is_empty() {
        Output::warning("No PRs were created.");
    } else {
        Output::success(&format!("Created {} PR(s):", created_prs.len()));
        for (repo_name, pr_number, url) in &created_prs {
            println!("  {}: #{} - {}", repo_name, pr_number, url);
        }
    }

    Ok(())
}

/// Check if a branch has commits ahead of another branch
fn has_commits_ahead(repo: &Repository, branch: &str, base: &str) -> anyhow::Result<bool> {
    let local_ref = format!("refs/heads/{}", branch);
    let base_ref = format!("refs/remotes/origin/{}", base);

    let local = match repo.find_reference(&local_ref) {
        Ok(r) => r,
        Err(_) => return Ok(false),
    };

    let base_branch = match repo.find_reference(&base_ref) {
        Ok(r) => r,
        Err(_) => {
            // Try local base branch
            match repo.find_reference(&format!("refs/heads/{}", base)) {
                Ok(r) => r,
                Err(_) => return Ok(false),
            }
        }
    };

    let local_oid = local
        .target()
        .ok_or_else(|| anyhow::anyhow!("No local target"))?;
    let base_oid = base_branch
        .target()
        .ok_or_else(|| anyhow::anyhow!("No base target"))?;

    let (ahead, _behind) = repo.graph_ahead_behind(local_oid, base_oid)?;
    Ok(ahead > 0)
}

/// Create RepoInfo for the manifest repository
fn create_manifest_repo_info(
    config: &crate::core::manifest::ManifestRepoConfig,
    _manifests_dir: &PathBuf,
    workspace_root: &PathBuf,
) -> Option<RepoInfo> {
    let path = ".gitgrip/manifests".to_string();

    crate::core::repo::RepoInfo::from_config(
        "manifest",
        &crate::core::manifest::RepoConfig {
            url: config.url.clone(),
            path,
            default_branch: config.default_branch.clone(),
            copyfile: config.copyfile.clone(),
            linkfile: config.linkfile.clone(),
            platform: config.platform.clone(),
            reference: false,
        },
        workspace_root,
    )
}

/// Check if a repo has changes ahead of its default branch
/// Returns Ok(true) if there are changes, Ok(false) if no changes or on default branch
fn check_repo_for_changes(
    repo: &RepoInfo,
    branch_name: &mut Option<String>,
) -> anyhow::Result<bool> {
    let git_repo = open_repo(&repo.absolute_path)
        .map_err(|e| anyhow::anyhow!("Failed to open repo: {}", e))?;

    let current = get_current_branch(&git_repo)
        .map_err(|e| anyhow::anyhow!("Failed to get current branch: {}", e))?;

    // Skip if on default branch
    if current == repo.default_branch {
        return Ok(false);
    }

    // Check for changes ahead of default branch
    let has_changes = has_commits_ahead(&git_repo, &current, &repo.default_branch)
        .map_err(|e| anyhow::anyhow!("Failed to check commits: {}", e))?;

    if has_changes {
        // Update branch_name for consistency checking
        if branch_name.is_none() {
            *branch_name = Some(current);
        }
        Ok(true)
    } else {
        Ok(false)
    }
}

/// Get authentication token for platform
#[allow(dead_code)]
pub fn get_token_for_platform(platform: &PlatformType) -> Option<String> {
    match platform {
        PlatformType::GitHub => std::env::var("GITHUB_TOKEN")
            .ok()
            .or_else(|| std::env::var("GH_TOKEN").ok()),
        PlatformType::GitLab => std::env::var("GITLAB_TOKEN").ok(),
        PlatformType::AzureDevOps => std::env::var("AZURE_DEVOPS_TOKEN").ok(),
    }
}
