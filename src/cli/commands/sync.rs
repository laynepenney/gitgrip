//! Sync command implementation

use crate::cli::output::Output;
use crate::core::griptree::GriptreeConfig;
use crate::core::manifest::Manifest;
use crate::core::repo::{filter_repos, RepoInfo};
use crate::git::remote::{pull_latest_from_upstream, safe_pull_latest};
use crate::git::{clone_repo, get_current_branch, open_repo, path_exists};
use std::path::PathBuf;

/// Run the sync command
pub fn run_sync(
    workspace_root: &PathBuf,
    manifest: &Manifest,
    force: bool,
    quiet: bool,
    group_filter: Option<&[String]>,
) -> anyhow::Result<()> {
    let repos: Vec<RepoInfo> = filter_repos(manifest, workspace_root, None, group_filter, true);
    let griptree_config = GriptreeConfig::load_from_workspace(workspace_root)?;
    let griptree_branch = griptree_config.as_ref().map(|cfg| cfg.branch.as_str());

    let griptree_config = GriptreeConfig::load_from_workspace(workspace_root)?;
    let griptree_branch = griptree_config.as_ref().map(|cfg| cfg.branch.clone());

    Output::header(&format!("Syncing {} repositories...", repos.len()));
    println!();

    let mut success_count = 0;
    let mut error_count = 0;
    let mut failed_repos: Vec<(String, String)> = Vec::new(); // (repo_name, error_message)

    for repo in &repos {
        let spinner = Output::spinner(&format!("Pulling {}...", repo.name));

        if !path_exists(&repo.absolute_path) {
            // Clone the repo
            spinner.set_message(format!("Cloning {}...", repo.name));

            match clone_repo(&repo.url, &repo.absolute_path, Some(&repo.default_branch)) {
                Ok(_) => {
                    // Check actual branch after clone - it may differ if manifest's default_branch
                    // doesn't exist on remote
                    let clone_msg = if let Ok(git_repo) = open_repo(&repo.absolute_path) {
                        if let Ok(actual_branch) = get_current_branch(&git_repo) {
                            if actual_branch != repo.default_branch {
                                format!(
                                    "{}: cloned (on '{}', manifest specifies '{}')",
                                    repo.name, actual_branch, repo.default_branch
                                )
                            } else {
                                format!("{}: cloned", repo.name)
                            }
                        } else {
                            format!("{}: cloned", repo.name)
                        }
                    } else {
                        format!("{}: cloned", repo.name)
                    };
                    spinner.finish_with_message(clone_msg);
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
                let current_branch = get_current_branch(&git_repo).ok();
                let use_griptree_upstream = match (griptree_branch, current_branch.as_deref()) {
                    (Some(base), Some(current)) => current == base,
                    _ => false,
                };

                if use_griptree_upstream {
                    let upstream = griptree_config
                        .as_ref()
                        .map(|cfg| cfg.upstream_for_repo(&repo.name, &repo.default_branch))
                        .unwrap_or_else(|| format!("origin/{}", repo.default_branch));

                    match pull_latest_from_upstream(&git_repo, &upstream) {
                        Ok(()) => {
                            spinner.finish_with_message(format!(
                                "{}: pulled ({})",
                                repo.name, upstream
                            ));
                            success_count += 1;
                        }
                        Err(e) => {
                            spinner.finish_with_message(format!("{}: error - {}", repo.name, e));
                            error_count += 1;
                            failed_repos.push((repo.name.clone(), format!("Error: {}", e)));
                        }
                    }
                } else {
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
                                } else if !quiet {
                                    spinner.finish_with_message(format!("{}: {}", repo.name, msg));
                                } else {
                                    spinner.finish_and_clear();
                                }
                            } else {
                                if !quiet {
                                    spinner.finish_with_message(format!("{}: up to date", repo.name));
                                } else {
                                    spinner.finish_and_clear();
                                }
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
