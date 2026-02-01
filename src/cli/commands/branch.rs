//! Branch command implementation

use crate::cli::output::Output;
use crate::core::manifest::Manifest;
use crate::core::repo::RepoInfo;
use crate::git::{
    branch::{branch_exists, create_and_checkout_branch, delete_local_branch, list_local_branches},
    get_current_branch, open_repo,
};
use std::path::PathBuf;

/// Run the branch command
pub fn run_branch(
    workspace_root: &PathBuf,
    manifest: &Manifest,
    name: Option<&str>,
    delete: bool,
    repos_filter: Option<&[String]>,
) -> anyhow::Result<()> {
    let repos: Vec<RepoInfo> = manifest
        .repos
        .iter()
        .filter_map(|(name, config)| RepoInfo::from_config(name, config, workspace_root))
        .filter(|r| !r.reference) // Skip reference repos
        .filter(|r| {
            repos_filter
                .map(|filter| filter.iter().any(|f| f == &r.name))
                .unwrap_or(true)
        })
        .collect();

    match name {
        Some(branch_name) if delete => {
            // Delete branch
            Output::header(&format!("Deleting branch '{}'", branch_name));
            println!();

            for repo in &repos {
                if !repo.exists() {
                    Output::warning(&format!("{}: not cloned", repo.name));
                    continue;
                }

                match open_repo(&repo.absolute_path) {
                    Ok(git_repo) => {
                        if !branch_exists(&git_repo, branch_name) {
                            Output::info(&format!("{}: branch doesn't exist", repo.name));
                            continue;
                        }

                        match delete_local_branch(&git_repo, branch_name, false) {
                            Ok(()) => Output::success(&format!("{}: deleted", repo.name)),
                            Err(e) => Output::error(&format!("{}: {}", repo.name, e)),
                        }
                    }
                    Err(e) => Output::error(&format!("{}: {}", repo.name, e)),
                }
            }
        }
        Some(branch_name) => {
            // Create branch
            Output::header(&format!(
                "Creating branch '{}' in {} repos...",
                branch_name,
                repos.len()
            ));
            println!();

            for repo in &repos {
                if !repo.exists() {
                    Output::warning(&format!("{}: not cloned", repo.name));
                    continue;
                }

                match open_repo(&repo.absolute_path) {
                    Ok(git_repo) => {
                        if branch_exists(&git_repo, branch_name) {
                            Output::info(&format!("{}: already exists", repo.name));
                            continue;
                        }

                        match create_and_checkout_branch(&git_repo, branch_name) {
                            Ok(()) => Output::success(&format!("{}: created", repo.name)),
                            Err(e) => Output::error(&format!("{}: {}", repo.name, e)),
                        }
                    }
                    Err(e) => Output::error(&format!("{}: {}", repo.name, e)),
                }
            }

            println!();
            println!(
                "All repos now on branch: {}",
                Output::branch_name(branch_name)
            );
        }
        None => {
            // List branches
            Output::header("Branches");
            println!();

            for repo in &repos {
                if !repo.exists() {
                    continue;
                }

                match open_repo(&repo.absolute_path) {
                    Ok(git_repo) => {
                        let current = get_current_branch(&git_repo).unwrap_or_default();
                        let branches = list_local_branches(&git_repo).unwrap_or_default();

                        println!("  {}:", Output::repo_name(&repo.name));
                        for branch in branches {
                            let marker = if branch == current { "* " } else { "  " };
                            let formatted = if branch == current {
                                Output::branch_name(&branch)
                            } else {
                                branch
                            };
                            println!("    {}{}", marker, formatted);
                        }
                    }
                    Err(_) => continue,
                }
            }
        }
    }

    Ok(())
}
