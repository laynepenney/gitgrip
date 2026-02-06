//! Sync command implementation

use crate::cli::output::Output;
use crate::core::manifest::Manifest;
use crate::core::repo::{filter_repos, get_manifest_repo_info, RepoInfo};
use crate::git::remote::safe_pull_latest;
use crate::git::{clone_repo, get_current_branch, open_repo, path_exists};
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
) -> anyhow::Result<()> {
    let mut repos: Vec<RepoInfo> = filter_repos(manifest, workspace_root, None, group_filter, true);

    // Include manifest repo at the beginning (sync it first)
    if let Some(manifest_repo) = get_manifest_repo_info(manifest, workspace_root) {
        repos.insert(0, manifest_repo);
    }

    Output::header(&format!("Syncing {} repositories...", repos.len()));
    println!();

    let results = if sequential {
        sync_sequential(&repos, force, quiet)?
    } else {
        sync_parallel(&repos, force, quiet).await?
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
) -> anyhow::Result<Vec<SyncResult>> {
    let mut results = Vec::new();

    for repo in repos {
        let result = sync_single_repo(repo, force, quiet, true)?;
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
) -> anyhow::Result<Vec<SyncResult>> {
    let results: Arc<Mutex<Vec<SyncResult>>> = Arc::new(Mutex::new(Vec::new()));
    let mut join_set: JoinSet<anyhow::Result<()>> = JoinSet::new();

    // Show a single spinner for all repos
    let spinner = Output::spinner(&format!("Syncing {} repos in parallel...", repos.len()));

    for repo in repos.to_vec() {
        let results = Arc::clone(&results);

        join_set.spawn_blocking(move || {
            let result = sync_single_repo(&repo, force, quiet, false)?;
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

/// Sync a single repository
fn sync_single_repo(
    repo: &RepoInfo,
    force: bool,
    quiet: bool,
    show_spinner: bool,
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
