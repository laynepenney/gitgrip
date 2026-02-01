//! Sync command implementation

use crate::cli::output::Output;
use crate::core::manifest::Manifest;
use crate::core::repo::RepoInfo;
use crate::git::remote::safe_pull_latest;
use crate::git::{clone_repo, open_repo, path_exists};
use std::path::PathBuf;

/// Run the sync command
pub fn run_sync(workspace_root: &PathBuf, manifest: &Manifest, force: bool) -> anyhow::Result<()> {
    Output::header(&format!("Syncing {} repositories...", manifest.repos.len()));
    println!();

    let repos: Vec<RepoInfo> = manifest
        .repos
        .iter()
        .filter_map(|(name, config)| RepoInfo::from_config(name, config, workspace_root))
        .collect();

    let mut success_count = 0;
    let mut error_count = 0;
    let mut failed_repos: Vec<(String, String)> = Vec::new();  // (repo_name, error_message)

    for repo in &repos {
        let spinner = Output::spinner(&format!("Pulling {}...", repo.name));

        if !path_exists(&repo.absolute_path) {
            // Clone the repo
            spinner.set_message(format!("Cloning {}...", repo.name));

            match clone_repo(&repo.url, &repo.absolute_path, Some(&repo.default_branch)) {
                Ok(_) => {
                    spinner.finish_with_message(format!("{}: cloned", repo.name));
                    success_count += 1;
                }
                Err(e) => {
                    spinner.finish_with_message(format!("{}: clone failed - {}", repo.name, e));
                    failed_repos.push((repo.name.clone(), format!("Clone failed: {}", e)));
                    error_count += 1;
                }
            }
            continue;
        }

        // Pull existing repo
        match open_repo(&repo.absolute_path) {
            Ok(git_repo) => {
                let result = safe_pull_latest(&git_repo, &repo.default_branch, "origin");

                match result {
                    Ok(pull_result) => {
                        if pull_result.pulled {
                            if pull_result.recovered {
                                spinner.finish_with_message(format!(
                                    "{}: {} (recovered)",
                                    repo.name,
                                    pull_result.message.unwrap_or_else(|| "pulled".to_string())
                                ));
                            } else if let Some(msg) = &pull_result.message {
                                spinner.finish_with_message(format!("{}: {}", repo.name, msg));
                            } else {
                                spinner.finish_with_message(format!("{}: pulled", repo.name));
                            }
                            success_count += 1;
                        } else if let Some(msg) = pull_result.message {
                            if force {
                                spinner.finish_with_message(format!(
                                    "{}: skipped - {}",
                                    repo.name, msg
                                ));
                            } else {
                                spinner.finish_with_message(format!("{}: {}", repo.name, msg));
                            }
                            error_count += 1;
                            failed_repos.push((repo.name.clone(), format!("Error: {}", e)));
                        } else {
                            spinner.finish_with_message(format!("{}: up to date", repo.name));
                            success_count += 1;
                        }
                    }
                    Err(e) => {
                        spinner.finish_with_message(format!("{}: error - {}", repo.name, e));
                        error_count += 1;
                        failed_repos.push((repo.name.clone(), format!("Error: {}", e)));
                    }
                }
            }
            Err(e) => {
                spinner.finish_with_message(format!("{}: error - {}", repo.name, e));
                error_count += 1;
                failed_repos.push((repo.name.clone(), format!("Error: {}", e)));
            }
        }
    }

    println!();
    if error_count == 0 {
        Output::success(&format!(
            "All {} repositories synced successfully.",
            success_count
        ));
    } else {
        Output::warning(&format!("{} synced, {} failed", success_count, error_count));
        
        // Show which repos failed and why
        if !failed_repos.is_empty() {
            println!();
            for (repo_name, error_msg) in &failed_repos {
                println!("  ✗ {}: {}", repo_name, error_msg);
            }
        }
    }

    Ok(())
}
