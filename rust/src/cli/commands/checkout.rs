//! Checkout command implementation

use crate::cli::output::Output;
use crate::core::manifest::Manifest;
use crate::core::repo::RepoInfo;
use crate::git::{
    branch::{branch_exists, checkout_branch},
    open_repo,
};
use std::path::PathBuf;

/// Run the checkout command
pub fn run_checkout(
    workspace_root: &PathBuf,
    manifest: &Manifest,
    branch_name: &str,
) -> anyhow::Result<()> {
    Output::header(&format!("Checking out '{}' in {} repos...", branch_name, manifest.repos.len()));
    println!();

    let repos: Vec<RepoInfo> = manifest
        .repos
        .iter()
        .filter_map(|(name, config)| RepoInfo::from_config(name, config, workspace_root))
        .collect();

    let mut success_count = 0;
    let mut _skip_count = 0;

    for repo in &repos {
        if !repo.exists() {
            Output::warning(&format!("{}: not cloned", repo.name));
            _skip_count += 1;
            continue;
        }

        match open_repo(&repo.absolute_path) {
            Ok(git_repo) => {
                if !branch_exists(&git_repo, branch_name) {
                    Output::info(&format!("{}: branch doesn't exist, skipping", repo.name));
                    _skip_count += 1;
                    continue;
                }

                match checkout_branch(&git_repo, branch_name) {
                    Ok(()) => {
                        Output::success(&repo.name);
                        success_count += 1;
                    }
                    Err(e) => Output::error(&format!("{}: {}", repo.name, e)),
                }
            }
            Err(e) => Output::error(&format!("{}: {}", repo.name, e)),
        }
    }

    println!();
    println!(
        "Switched {}/{} repos to {}",
        success_count,
        repos.len(),
        Output::branch_name(branch_name)
    );

    Ok(())
}
