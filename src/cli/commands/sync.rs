//! Sync command implementation

use crate::cli::output::Output;
use crate::core::griptree::GriptreeConfig;
use crate::core::manifest::Manifest;
use crate::core::repo::{filter_repos, get_manifest_repo_info, RepoInfo};
use crate::git::branch::{checkout_branch_at_upstream, has_commits_ahead};
use crate::git::remote::{fetch_remote, pull_latest_from_upstream, reset_hard, safe_pull_latest};
use crate::git::status::has_uncommitted_changes;
use crate::git::{clone_repo, get_current_branch, open_repo, path_exists};
use git2::Repository;
use indicatif::ProgressBar;
use std::path::PathBuf;
use std::sync::{Arc, Mutex};
use tokio::task::JoinSet;

/// Result of syncing a single repo
#[derive(Debug)]
struct SyncResult {
    name: String,
    success: bool,
    message: String,
    was_cloned: bool,
}

/// Run the sync command
pub async fn run_sync(
    workspace_root: &PathBuf,
    manifest: &Manifest,
    force: bool,
    quiet: bool,
    group_filter: Option<&[String]>,
    sequential: bool,
    reset_refs: bool,
) -> anyhow::Result<()> {
    let mut repos: Vec<RepoInfo> = filter_repos(manifest, workspace_root, None, group_filter, true);

    // Include manifest repo at the beginning (sync it first)
    if let Some(manifest_repo) = get_manifest_repo_info(manifest, workspace_root) {
        repos.insert(0, manifest_repo);
    }
    let griptree_config = GriptreeConfig::load_from_workspace(workspace_root)?;
    let griptree_branch = griptree_config.as_ref().map(|cfg| cfg.branch.clone());

    Output::header(&format!("Syncing {} repositories...", repos.len()));
    println!();

    let results = if sequential {
        sync_sequential(
            &repos,
            force,
            quiet,
            griptree_config.as_ref(),
            griptree_branch.as_deref(),
            reset_refs,
        )?
    } else {
        sync_parallel(
            &repos,
            force,
            quiet,
            griptree_config.clone(),
            griptree_branch.clone(),
            reset_refs,
        )
        .await?
    };

    // Display results
    let mut success_count = 0;
    let mut error_count = 0;
    let mut failed_repos: Vec<(String, String)> = Vec::new();

    for result in results {
        if result.success {
            success_count += 1;
        } else {
            error_count += 1;
            failed_repos.push((result.name.clone(), result.message.clone()));
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

        if !failed_repos.is_empty() {
            println!();
            for (repo_name, error_msg) in &failed_repos {
                println!("  ✗ {}: {}", repo_name, error_msg);
            }
        }
    }

    Ok(())
}

/// Sync repos sequentially (original behavior)
fn sync_sequential(
    repos: &[RepoInfo],
    force: bool,
    quiet: bool,
    griptree_config: Option<&GriptreeConfig>,
    griptree_branch: Option<&str>,
    reset_refs: bool,
) -> anyhow::Result<Vec<SyncResult>> {
    let mut results = Vec::new();

    for repo in repos {
        let result = sync_single_repo(
            repo,
            force,
            quiet,
            true,
            griptree_config,
            griptree_branch,
            reset_refs,
        )?;
        results.push(result);
    }

    Ok(results)
}

/// Sync repos in parallel using tokio
#[allow(clippy::unnecessary_to_owned)] // We need to clone for move into spawn_blocking
async fn sync_parallel(
    repos: &[RepoInfo],
    force: bool,
    quiet: bool,
    griptree_config: Option<GriptreeConfig>,
    griptree_branch: Option<String>,
    reset_refs: bool,
) -> anyhow::Result<Vec<SyncResult>> {
    let results: Arc<Mutex<Vec<SyncResult>>> = Arc::new(Mutex::new(Vec::new()));
    let mut join_set: JoinSet<anyhow::Result<()>> = JoinSet::new();

    // Show a single spinner for all repos
    let spinner = Output::spinner(&format!("Syncing {} repos in parallel...", repos.len()));

    for repo in repos.to_vec() {
        let results = Arc::clone(&results);
        let griptree_config = griptree_config.clone();
        let griptree_branch = griptree_branch.clone();

        join_set.spawn_blocking(move || {
            let result = sync_single_repo(
                &repo,
                force,
                quiet,
                false,
                griptree_config.as_ref(),
                griptree_branch.as_deref(),
                reset_refs,
            )?;
            results.lock().unwrap().push(result);
            Ok(())
        });
    }

    // Wait for all tasks to complete
    while let Some(res) = join_set.join_next().await {
        res??;
    }

    spinner.finish_and_clear();

    // Extract results from Arc<Mutex<>>
    let results = match Arc::try_unwrap(results) {
        Ok(mutex) => mutex.into_inner().unwrap(),
        Err(arc) => arc.lock().unwrap().clone(),
    };

    // Print results in order
    for result in &results {
        if result.success {
            if !quiet || result.was_cloned {
                Output::success(&format!("{}: {}", result.name, result.message));
            }
        } else {
            Output::error(&format!("{}: {}", result.name, result.message));
        }
    }

    Ok(results)
}

fn sync_griptree_upstream(
    repo: &RepoInfo,
    git_repo: &Repository,
    current_branch: Option<&str>,
    griptree_config: Option<&GriptreeConfig>,
    spinner: Option<&ProgressBar>,
    quiet: bool,
) -> SyncResult {
    let upstream = match griptree_config {
        Some(cfg) => match cfg.upstream_for_repo(&repo.name, &repo.default_branch) {
            Ok(upstream) => upstream,
            Err(e) => {
                let msg = format!("error - {}", e);
                if let Some(s) = spinner {
                    s.finish_with_message(format!("{}: {}", repo.name, msg));
                }
                return SyncResult {
                    name: repo.name.clone(),
                    success: false,
                    message: msg,
                    was_cloned: false,
                };
            }
        },
        None => format!("origin/{}", repo.default_branch),
    };

    let remote = upstream.split('/').next().unwrap_or("origin");

    if let Err(e) = fetch_remote(git_repo, remote) {
        let msg = format!("error - {}", e);
        if let Some(s) = spinner {
            s.finish_with_message(format!("{}: {}", repo.name, msg));
        }
        return SyncResult {
            name: repo.name.clone(),
            success: false,
            message: msg,
            was_cloned: false,
        };
    }

    if let Some(current) = current_branch {
        match has_commits_ahead(git_repo, &upstream) {
            Ok(true) => {
                let msg = format!(
                    "skipped - branch '{}' has local commits not in '{}'",
                    current, upstream
                );
                if let Some(s) = spinner {
                    s.finish_with_message(format!("{}: {}", repo.name, msg));
                }
                return SyncResult {
                    name: repo.name.clone(),
                    success: true,
                    message: msg,
                    was_cloned: false,
                };
            }
            Ok(false) => {}
            Err(e) => {
                let msg = format!("error - {}", e);
                if let Some(s) = spinner {
                    s.finish_with_message(format!("{}: {}", repo.name, msg));
                }
                return SyncResult {
                    name: repo.name.clone(),
                    success: false,
                    message: msg,
                    was_cloned: false,
                };
            }
        }
    }

    match pull_latest_from_upstream(git_repo, &upstream) {
        Ok(()) => {
            let msg = format!("pulled ({})", upstream);
            if let Some(s) = spinner {
                if !quiet {
                    s.finish_with_message(format!("{}: {}", repo.name, msg));
                } else {
                    s.finish_and_clear();
                }
            }

            SyncResult {
                name: repo.name.clone(),
                success: true,
                message: msg,
                was_cloned: false,
            }
        }
        Err(e) => {
            let msg = format!("error - {}", e);
            if let Some(s) = spinner {
                s.finish_with_message(format!("{}: {}", repo.name, msg));
            }
            SyncResult {
                name: repo.name.clone(),
                success: false,
                message: msg,
                was_cloned: false,
            }
        }
    }
}

fn sync_reference_reset(
    repo: &RepoInfo,
    git_repo: &Repository,
    griptree_config: Option<&GriptreeConfig>,
    spinner: Option<&ProgressBar>,
    quiet: bool,
) -> SyncResult {
    let upstream = match griptree_config {
        Some(cfg) => match cfg.upstream_for_repo(&repo.name, &repo.default_branch) {
            Ok(upstream) => upstream,
            Err(e) => {
                let msg = format!("error - {}", e);
                if let Some(s) = spinner {
                    s.finish_with_message(format!("{}: {}", repo.name, msg));
                }
                return SyncResult {
                    name: repo.name.clone(),
                    success: false,
                    message: msg,
                    was_cloned: false,
                };
            }
        },
        None => format!("origin/{}", repo.default_branch),
    };

    let mut upstream_parts = upstream.splitn(2, '/');
    let remote = upstream_parts.next().unwrap_or("origin");
    let upstream_branch = upstream_parts.next().unwrap_or(&repo.default_branch);

    if let Ok(is_dirty) = has_uncommitted_changes(git_repo) {
        if is_dirty {
            Output::warning(&format!(
                "{}: --reset-refs will discard local changes",
                repo.name
            ));
        }
    }
    if let Ok(true) = has_commits_ahead(git_repo, &upstream) {
        Output::warning(&format!(
            "{}: --reset-refs will discard local commits not in {}",
            repo.name, upstream
        ));
    }
    if let Err(e) = fetch_remote(git_repo, remote) {
        let msg = format!("error - {}", e);
        if let Some(s) = spinner {
            s.finish_with_message(format!("{}: {}", repo.name, msg));
        }
        return SyncResult {
            name: repo.name.clone(),
            success: false,
            message: msg,
            was_cloned: false,
        };
    }

    if let Err(e) = checkout_branch_at_upstream(git_repo, upstream_branch, &upstream) {
        let msg = format!("error - {}", e);
        if let Some(s) = spinner {
            s.finish_with_message(format!("{}: {}", repo.name, msg));
        }
        return SyncResult {
            name: repo.name.clone(),
            success: false,
            message: msg,
            was_cloned: false,
        };
    }

    match reset_hard(git_repo, &upstream) {
        Ok(()) => {
            let msg = format!("reset ({})", upstream);
            if let Some(s) = spinner {
                if !quiet {
                    s.finish_with_message(format!("{}: {}", repo.name, msg));
                } else {
                    s.finish_and_clear();
                }
            }

            SyncResult {
                name: repo.name.clone(),
                success: true,
                message: msg,
                was_cloned: false,
            }
        }
        Err(e) => {
            let msg = format!("error - {}", e);
            if let Some(s) = spinner {
                s.finish_with_message(format!("{}: {}", repo.name, msg));
            }
            SyncResult {
                name: repo.name.clone(),
                success: false,
                message: msg,
                was_cloned: false,
            }
        }
    }
}

/// Sync a single repository
fn sync_single_repo(
    repo: &RepoInfo,
    force: bool,
    quiet: bool,
    show_spinner: bool,
    griptree_config: Option<&GriptreeConfig>,
    griptree_branch: Option<&str>,
    reset_refs: bool,
) -> anyhow::Result<SyncResult> {
    let spinner = if show_spinner {
        Some(Output::spinner(&format!("Pulling {}...", repo.name)))
    } else {
        None
    };

    if !path_exists(&repo.absolute_path) {
        // Clone the repo
        if let Some(ref s) = spinner {
            s.set_message(format!("Cloning {}...", repo.name));
        }

        match clone_repo(&repo.url, &repo.absolute_path, Some(&repo.default_branch)) {
            Ok(_) => {
                // Check actual branch after clone
                let clone_msg = if let Ok(git_repo) = open_repo(&repo.absolute_path) {
                    if let Ok(actual_branch) = get_current_branch(&git_repo) {
                        if actual_branch != repo.default_branch {
                            format!(
                                "cloned (on '{}', manifest specifies '{}')",
                                actual_branch, repo.default_branch
                            )
                        } else {
                            "cloned".to_string()
                        }
                    } else {
                        "cloned".to_string()
                    }
                } else {
                    "cloned".to_string()
                };

                if let Some(s) = spinner {
                    s.finish_with_message(format!("{}: {}", repo.name, clone_msg));
                }

                return Ok(SyncResult {
                    name: repo.name.clone(),
                    success: true,
                    message: clone_msg,
                    was_cloned: true,
                });
            }
            Err(e) => {
                let msg = format!("clone failed - {}", e);
                if let Some(s) = spinner {
                    s.finish_with_message(format!("{}: {}", repo.name, msg));
                }
                return Ok(SyncResult {
                    name: repo.name.clone(),
                    success: false,
                    message: msg,
                    was_cloned: false,
                });
            }
        }
    }

    // Pull existing repo
    match open_repo(&repo.absolute_path) {
        Ok(git_repo) => {
            if repo.reference && reset_refs {
                let result =
                    sync_reference_reset(repo, &git_repo, griptree_config, spinner.as_ref(), quiet);
                return Ok(result);
            }

            let current_branch = get_current_branch(&git_repo).ok();
            let use_griptree_upstream = match (griptree_branch, current_branch.as_deref()) {
                (Some(base), Some(current)) => current == base,
                _ => false,
            };

            if use_griptree_upstream {
                let result = sync_griptree_upstream(
                    repo,
                    &git_repo,
                    current_branch.as_deref(),
                    griptree_config,
                    spinner.as_ref(),
                    quiet,
                );
                Ok(result)
            } else {
                let result = safe_pull_latest(&git_repo, &repo.default_branch, "origin");

                match result {
                    Ok(pull_result) => {
                        let (success, message) = if pull_result.pulled {
                            if pull_result.recovered {
                                (
                                    true,
                                    pull_result
                                        .message
                                        .unwrap_or_else(|| "pulled (recovered)".to_string()),
                                )
                            } else {
                                (
                                    true,
                                    pull_result.message.unwrap_or_else(|| "pulled".to_string()),
                                )
                            }
                        } else if let Some(msg) = pull_result.message {
                            if force {
                                (true, format!("skipped - {}", msg))
                            } else {
                                (true, msg)
                            }
                        } else {
                            (true, "up to date".to_string())
                        };

                        if let Some(s) = spinner {
                            if !quiet || !success {
                                s.finish_with_message(format!("{}: {}", repo.name, message));
                            } else {
                                s.finish_and_clear();
                            }
                        }

                        Ok(SyncResult {
                            name: repo.name.clone(),
                            success,
                            message,
                            was_cloned: false,
                        })
                    }
                    Err(e) => {
                        let msg = format!("error - {}", e);
                        if let Some(s) = spinner {
                            s.finish_with_message(format!("{}: {}", repo.name, msg));
                        }
                        Ok(SyncResult {
                            name: repo.name.clone(),
                            success: false,
                            message: msg,
                            was_cloned: false,
                        })
                    }
                }
            }
        }
        Err(e) => {
            let msg = format!("error - {}", e);
            if let Some(s) = spinner {
                s.finish_with_message(format!("{}: {}", repo.name, msg));
            }
            Ok(SyncResult {
                name: repo.name.clone(),
                success: false,
                message: msg,
                was_cloned: false,
            })
        }
    }
}

// Make SyncResult cloneable for parallel sync
impl Clone for SyncResult {
    fn clone(&self) -> Self {
        SyncResult {
            name: self.name.clone(),
            success: self.success,
            message: self.message.clone(),
            was_cloned: self.was_cloned,
        }
    }
}
