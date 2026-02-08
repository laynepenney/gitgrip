//! PR merge command implementation

use super::create::has_commits_ahead;
use crate::cli::output::Output;
use crate::core::manifest::Manifest;
use crate::core::repo::{get_manifest_repo_info, RepoInfo};
use crate::git::{get_current_branch, open_repo, path_exists};
use crate::platform::traits::PlatformError;
use crate::platform::{get_platform_adapter, CheckState, MergeMethod};
use std::path::PathBuf;
use std::sync::Arc;

/// Run the PR merge command
pub async fn run_pr_merge(
    workspace_root: &PathBuf,
    manifest: &Manifest,
    method: Option<&str>,
    force: bool,
    update: bool,
    auto: bool,
) -> anyhow::Result<()> {
    Output::header("Merging pull requests...");
    println!();

    let repos: Vec<RepoInfo> = manifest
        .repos
        .iter()
        .filter_map(|(name, config)| RepoInfo::from_config(name, config, workspace_root))
        .filter(|r| !r.reference) // Skip reference repos
        .collect();

    let merge_method = match method {
        Some("squash") => MergeMethod::Squash,
        Some("rebase") => MergeMethod::Rebase,
        _ => MergeMethod::Merge,
    };

    // Collect PRs to merge and track per-repo outcomes
    #[derive(Debug, Clone, Copy)]
    enum CheckStatus {
        Passing,
        Failing,
        Pending,
        Unknown,
    }

    #[derive(Debug)]
    enum RepoOutcome {
        Skipped { reason: String },
        Merged { pr_number: u64 },
        AlreadyMerged { pr_number: u64 },
        NotMerged { pr_number: u64, reason: String },
        Failed { pr_number: u64, reason: String },
        AutoEnabled { pr_number: u64 },
        AutoFailed { pr_number: u64, reason: String },
    }

    struct RepoReport {
        repo_name: String,
        outcome: RepoOutcome,
    }

    struct PRToMerge {
        repo_name: String,
        owner: String,
        repo: String,
        pr_number: u64,
        platform: Arc<dyn crate::platform::HostingPlatform>,
        approved: bool,
        check_status: CheckStatus,
        mergeable: bool,
    }

    let mut prs_to_merge: Vec<PRToMerge> = Vec::new();
    let mut reports: Vec<RepoReport> = Vec::new();

    // Also check manifest repo if configured
    let mut all_repos = repos.clone();
    if let Some(manifest_repo) = get_manifest_repo_info(manifest, workspace_root) {
        let manifest_name = manifest_repo.name.clone();
        // Only add manifest repo if it has changes
        match check_repo_for_changes(&manifest_repo) {
            Ok(true) => {
                all_repos.push(manifest_repo);
            }
            Ok(false) => {
                reports.push(RepoReport {
                    repo_name: manifest_name.clone(),
                    outcome: RepoOutcome::Skipped {
                        reason: "no changes".to_string(),
                    },
                });
            }
            Err(e) => {
                reports.push(RepoReport {
                    repo_name: manifest_name,
                    outcome: RepoOutcome::Skipped {
                        reason: format!("could not check for changes: {}", e),
                    },
                });
            }
        }
    }

    for repo in &all_repos {
        if !path_exists(&repo.absolute_path) {
            reports.push(RepoReport {
                repo_name: repo.name.clone(),
                outcome: RepoOutcome::Skipped {
                    reason: "not cloned".to_string(),
                },
            });
            continue;
        }

        let git_repo = match open_repo(&repo.absolute_path) {
            Ok(r) => r,
            Err(e) => {
                reports.push(RepoReport {
                    repo_name: repo.name.clone(),
                    outcome: RepoOutcome::Skipped {
                        reason: format!("not a git repo - {}", e),
                    },
                });
                continue;
            }
        };

        let branch = match get_current_branch(&git_repo) {
            Ok(b) => b,
            Err(e) => {
                reports.push(RepoReport {
                    repo_name: repo.name.clone(),
                    outcome: RepoOutcome::Skipped {
                        reason: format!("failed to get current branch - {}", e),
                    },
                });
                continue;
            }
        };

        // Skip if on default branch
        if branch == repo.default_branch {
            reports.push(RepoReport {
                repo_name: repo.name.clone(),
                outcome: RepoOutcome::Skipped {
                    reason: "on default branch".to_string(),
                },
            });
            continue;
        }

        let platform = get_platform_adapter(repo.platform_type, repo.platform_base_url.as_deref());

        match platform
            .find_pr_by_branch(&repo.owner, &repo.repo, &branch)
            .await
        {
            Ok(Some(pr)) => {
                // Get PR details
                let (approved, mergeable, already_merged) = match platform
                    .get_pull_request(&repo.owner, &repo.repo, pr.number)
                    .await
                {
                    Ok(full_pr) => {
                        let is_approved = platform
                            .is_pull_request_approved(&repo.owner, &repo.repo, pr.number)
                            .await
                            .unwrap_or(false);
                        (
                            is_approved,
                            full_pr.mergeable.unwrap_or(false),
                            full_pr.merged,
                        )
                    }
                    Err(_) => (false, false, false),
                };

                // Get status checks
                let check_status = match platform
                    .get_status_checks(&repo.owner, &repo.repo, &branch)
                    .await
                {
                    Ok(status) => {
                        // Successfully got check status
                        if status.state == CheckState::Failure {
                            // Checks are actually failing
                            CheckStatus::Failing
                        } else if status.state == CheckState::Pending {
                            // Checks still running - don't block but warn
                            CheckStatus::Pending
                        } else {
                            CheckStatus::Passing
                        }
                    }
                    Err(e) => {
                        // Could not determine check status
                        // Don't block merge due to API issues
                        Output::warning(&format!(
                            "{}: Could not check CI status for PR #{}: {}",
                            repo.name, pr.number, e
                        ));
                        CheckStatus::Unknown
                    }
                };

                if already_merged {
                    reports.push(RepoReport {
                        repo_name: repo.name.clone(),
                        outcome: RepoOutcome::AlreadyMerged {
                            pr_number: pr.number,
                        },
                    });
                    continue;
                }

                prs_to_merge.push(PRToMerge {
                    repo_name: repo.name.clone(),
                    owner: repo.owner.clone(),
                    repo: repo.repo.clone(),
                    pr_number: pr.number,
                    platform,
                    approved,
                    check_status,
                    mergeable,
                });
            }
            Ok(None) => {
                reports.push(RepoReport {
                    repo_name: repo.name.clone(),
                    outcome: RepoOutcome::Skipped {
                        reason: format!("no open PR for branch '{}'", branch),
                    },
                });
            }
            Err(e) => {
                reports.push(RepoReport {
                    repo_name: repo.name.clone(),
                    outcome: RepoOutcome::Skipped {
                        reason: format!("failed to find PR - {}", e),
                    },
                });
            }
        }
    }

    if prs_to_merge.is_empty() {
        println!("No open PRs found for any repository.");
        println!("Repositories checked: {}", all_repos.len());
        if !reports.is_empty() {
            println!();
            Output::header("Repository summary");
            for report in &reports {
                match &report.outcome {
                    RepoOutcome::Skipped { reason } => {
                        Output::info(&format!("{}: skipped — {}", report.repo_name, reason));
                    }
                    RepoOutcome::AlreadyMerged { pr_number } => {
                        Output::info(&format!(
                            "{}: already merged PR #{}",
                            report.repo_name, pr_number
                        ));
                    }
                    _ => {}
                }
            }
        }
        return Ok(());
    }

    if !reports.is_empty() {
        Output::info(&format!(
            "Merging {} repo(s) with open PRs. {} repo(s) will be skipped.",
            prs_to_merge.len(),
            reports
                .iter()
                .filter(|r| matches!(r.outcome, RepoOutcome::Skipped { .. }))
                .count()
        ));
        for report in &reports {
            if let RepoOutcome::Skipped { reason } = &report.outcome {
                Output::info(&format!("  - {}: skipped — {}", report.repo_name, reason));
            }
        }
        println!();
    }

    // Check readiness if not forcing
    if !force {
        let mut issues = Vec::new();
        for pr in &prs_to_merge {
            if !pr.approved {
                issues.push(format!(
                    "{} PR #{}: not approved",
                    pr.repo_name, pr.pr_number
                ));
            }
            match pr.check_status {
                CheckStatus::Failing => {
                    issues.push(format!(
                        "{} PR #{}: checks failing",
                        pr.repo_name, pr.pr_number
                    ));
                }
                CheckStatus::Pending => {
                    issues.push(format!(
                        "{} PR #{}: checks still running",
                        pr.repo_name, pr.pr_number
                    ));
                }
                CheckStatus::Unknown => {
                    // Don't block on unknown - warn but allow merge
                    Output::warning(&format!(
                        "{} PR #{}: check status unknown - proceeding with caution",
                        pr.repo_name, pr.pr_number
                    ));
                }
                CheckStatus::Passing => {} // All good
            }
            if !pr.mergeable {
                issues.push(format!(
                    "{} PR #{}: not mergeable (branch may be behind base — try --update)",
                    pr.repo_name, pr.pr_number
                ));
            }
        }

        if !issues.is_empty() {
            Output::warning("Some PRs have issues:");
            for issue in &issues {
                println!("  - {}", issue);
            }
            println!();
            println!("Use --force to merge anyway.");
            return Ok(());
        }
    }

    // Auto-merge flow: enable auto-merge and return early
    if auto {
        let mut auto_enabled = 0;
        let mut auto_failed = 0;

        for pr in prs_to_merge {
            let spinner = Output::spinner(&format!(
                "Enabling auto-merge for {} PR #{}...",
                pr.repo_name, pr.pr_number
            ));

            match pr
                .platform
                .enable_auto_merge(&pr.owner, &pr.repo, pr.pr_number, Some(merge_method))
                .await
            {
                Ok(true) => {
                    spinner.finish_with_message(format!(
                        "{}: PR #{} will auto-merge when checks pass",
                        pr.repo_name, pr.pr_number
                    ));
                    auto_enabled += 1;
                    reports.push(RepoReport {
                        repo_name: pr.repo_name.clone(),
                        outcome: RepoOutcome::AutoEnabled {
                            pr_number: pr.pr_number,
                        },
                    });
                }
                Ok(false) => {
                    spinner.finish_with_message(format!(
                        "{}: PR #{} auto-merge could not be enabled",
                        pr.repo_name, pr.pr_number
                    ));
                    auto_failed += 1;
                    reports.push(RepoReport {
                        repo_name: pr.repo_name.clone(),
                        outcome: RepoOutcome::AutoFailed {
                            pr_number: pr.pr_number,
                            reason: "auto-merge not enabled".to_string(),
                        },
                    });
                }
                Err(e) => {
                    spinner.finish_with_message(format!("{}: failed - {}", pr.repo_name, e));
                    auto_failed += 1;
                    reports.push(RepoReport {
                        repo_name: pr.repo_name.clone(),
                        outcome: RepoOutcome::AutoFailed {
                            pr_number: pr.pr_number,
                            reason: e.to_string(),
                        },
                    });
                }
            }
        }

        println!();
        if auto_failed == 0 {
            Output::success(&format!(
                "Auto-merge enabled for {} PR(s). They will merge when all checks pass.",
                auto_enabled
            ));
        } else {
            Output::warning(&format!(
                "{} auto-merge enabled, {} failed",
                auto_enabled, auto_failed
            ));
        }

        let auto_show_summary = reports.iter().any(|report| {
            matches!(
                report.outcome,
                RepoOutcome::AutoFailed { .. }
                    | RepoOutcome::Skipped { .. }
                    | RepoOutcome::AlreadyMerged { .. }
            )
        });
        if auto_show_summary {
            println!();
            Output::header("Repository summary");
            for report in &reports {
                match &report.outcome {
                    RepoOutcome::AutoEnabled { pr_number } => {
                        Output::success(&format!(
                            "{}: auto-merge enabled for PR #{}",
                            report.repo_name, pr_number
                        ));
                    }
                    RepoOutcome::AutoFailed { pr_number, reason } => {
                        Output::warning(&format!(
                            "{}: auto-merge failed for PR #{} — {}",
                            report.repo_name, pr_number, reason
                        ));
                    }
                    RepoOutcome::Skipped { reason } => {
                        Output::info(&format!("{}: skipped — {}", report.repo_name, reason));
                    }
                    RepoOutcome::AlreadyMerged { pr_number } => {
                        Output::info(&format!(
                            "{}: already merged PR #{}",
                            report.repo_name, pr_number
                        ));
                    }
                    _ => {}
                }
            }
        }

        return Ok(());
    }

    // Merge PRs
    let mut merged_count = 0;
    let mut not_merged_count = 0;
    let mut failed_count = 0;

    for pr in prs_to_merge {
        let spinner = Output::spinner(&format!("Merging {} PR #{}...", pr.repo_name, pr.pr_number));

        let merge_result = pr
            .platform
            .merge_pull_request(
                &pr.owner,
                &pr.repo,
                pr.pr_number,
                Some(merge_method),
                true, // delete branch
            )
            .await;

        // Handle BranchBehind with --update retry (single attempt — if another
        // commit lands between update and retry, the user can re-run the command).
        let merge_result = match merge_result {
            Err(PlatformError::BranchBehind(ref msg)) if update => {
                spinner.finish_with_message(format!(
                    "{}: branch behind base, updating...",
                    pr.repo_name
                ));
                let update_spinner = Output::spinner(&format!(
                    "Updating {} PR #{} branch...",
                    pr.repo_name, pr.pr_number
                ));

                match pr
                    .platform
                    .update_branch(&pr.owner, &pr.repo, pr.pr_number)
                    .await
                {
                    Ok(true) => {
                        update_spinner.finish_with_message(format!(
                            "{}: branch updated, retrying merge...",
                            pr.repo_name
                        ));
                        // Wait for GitHub to process the update
                        tokio::time::sleep(std::time::Duration::from_secs(3)).await;

                        let retry_spinner = Output::spinner(&format!(
                            "Merging {} PR #{}...",
                            pr.repo_name, pr.pr_number
                        ));

                        // Retry merge once
                        match pr
                            .platform
                            .merge_pull_request(
                                &pr.owner,
                                &pr.repo,
                                pr.pr_number,
                                Some(merge_method),
                                true,
                            )
                            .await
                        {
                            Ok(true) => {
                                retry_spinner.finish_with_message(format!(
                                    "{}: merged PR #{}",
                                    pr.repo_name, pr.pr_number
                                ));
                                merged_count += 1;
                                reports.push(RepoReport {
                                    repo_name: pr.repo_name.clone(),
                                    outcome: RepoOutcome::Merged {
                                        pr_number: pr.pr_number,
                                    },
                                });
                                continue;
                            }
                            Ok(false) => {
                                retry_spinner.finish_with_message(format!(
                                    "{}: PR #{} not merged (platform reported merged=false)",
                                    pr.repo_name, pr.pr_number
                                ));
                                not_merged_count += 1;
                                reports.push(RepoReport {
                                    repo_name: pr.repo_name.clone(),
                                    outcome: RepoOutcome::NotMerged {
                                        pr_number: pr.pr_number,
                                        reason: "platform returned merged=false".to_string(),
                                    },
                                });
                                continue;
                            }
                            Err(e) => Err(e),
                        }
                    }
                    Ok(false) => {
                        update_spinner.finish_with_message(format!(
                            "{}: branch already up to date",
                            pr.repo_name
                        ));
                        Err(PlatformError::BranchBehind(msg.clone()))
                    }
                    Err(update_err) => {
                        update_spinner.finish_with_message(format!(
                            "{}: branch update failed - {}",
                            pr.repo_name, update_err
                        ));
                        Err(PlatformError::BranchBehind(msg.clone()))
                    }
                }
            }
            other => other,
        };

        // Original spinner is still active for non-update paths
        match merge_result {
            Ok(merged) => {
                if merged {
                    spinner.finish_with_message(format!(
                        "{}: merged PR #{}",
                        pr.repo_name, pr.pr_number
                    ));
                    merged_count += 1;
                    reports.push(RepoReport {
                        repo_name: pr.repo_name.clone(),
                        outcome: RepoOutcome::Merged {
                            pr_number: pr.pr_number,
                        },
                    });
                } else {
                    spinner.finish_with_message(format!(
                        "{}: PR #{} not merged (platform reported merged=false)",
                        pr.repo_name, pr.pr_number
                    ));
                    not_merged_count += 1;
                    reports.push(RepoReport {
                        repo_name: pr.repo_name.clone(),
                        outcome: RepoOutcome::NotMerged {
                            pr_number: pr.pr_number,
                            reason: "platform returned merged=false".to_string(),
                        },
                    });
                }
            }
            Err(PlatformError::BranchBehind(_)) => {
                spinner.finish_with_message(format!(
                    "{}: PR #{} branch is behind base branch",
                    pr.repo_name, pr.pr_number
                ));
                Output::info("  Hint: use 'gr pr merge --update' to update the branch and retry");
                failed_count += 1;
                reports.push(RepoReport {
                    repo_name: pr.repo_name.clone(),
                    outcome: RepoOutcome::Failed {
                        pr_number: pr.pr_number,
                        reason: "branch behind base".to_string(),
                    },
                });
            }
            Err(PlatformError::BranchProtected(ref msg)) => {
                spinner.finish_with_message(format!("{}: {}", pr.repo_name, msg));
                Output::info(
                    "  Hint: use 'gr pr merge --auto' to enable auto-merge when checks pass",
                );
                Output::info(&format!(
                    "  Or:   gh pr merge {} --admin --repo {}/{}",
                    pr.pr_number, pr.owner, pr.repo
                ));
                failed_count += 1;
                reports.push(RepoReport {
                    repo_name: pr.repo_name.clone(),
                    outcome: RepoOutcome::Failed {
                        pr_number: pr.pr_number,
                        reason: msg.clone(),
                    },
                });
            }
            Err(e) => {
                spinner.finish_with_message(format!("{}: failed - {}", pr.repo_name, e));
                failed_count += 1;
                reports.push(RepoReport {
                    repo_name: pr.repo_name.clone(),
                    outcome: RepoOutcome::Failed {
                        pr_number: pr.pr_number,
                        reason: e.to_string(),
                    },
                });

                // Check for all-or-nothing merge strategy (unless forcing)
                if !force
                    && manifest.settings.merge_strategy
                        == crate::core::manifest::MergeStrategy::AllOrNothing
                {
                    Output::error(
                        "Stopping due to all-or-nothing merge strategy. Use --force to bypass.",
                    );
                    return Err(e.into());
                }
                // If forcing with AllOrNothing, just log and continue
                if force
                    && manifest.settings.merge_strategy
                        == crate::core::manifest::MergeStrategy::AllOrNothing
                {
                    Output::warning(&format!(
                        "{}: merge failed but continuing due to --force flag",
                        pr.repo_name
                    ));
                }
            }
        }
    }

    // Summary
    println!();
    let skipped_count = reports
        .iter()
        .filter(|r| matches!(r.outcome, RepoOutcome::Skipped { .. }))
        .count();
    let already_merged_count = reports
        .iter()
        .filter(|r| matches!(r.outcome, RepoOutcome::AlreadyMerged { .. }))
        .count();
    let mut summary_parts: Vec<String> = Vec::new();
    if merged_count > 0 {
        summary_parts.push(format!("Merged {} PR(s)", merged_count));
    }
    if already_merged_count > 0 {
        summary_parts.push(format!("{} already merged", already_merged_count));
    }
    if not_merged_count > 0 {
        summary_parts.push(format!("{} not merged", not_merged_count));
    }
    if failed_count > 0 {
        summary_parts.push(format!("{} failed", failed_count));
    }
    if skipped_count > 0 {
        summary_parts.push(format!("{} skipped", skipped_count));
    }

    if failed_count == 0 && not_merged_count == 0 {
        if summary_parts.is_empty() {
            Output::success("No PRs merged.");
        } else if summary_parts.len() == 1 {
            Output::success(&format!("{}.", summary_parts.join("")));
        } else {
            Output::success(&format!("{}.", summary_parts.join(". ")));
        }
    } else if summary_parts.is_empty() {
        Output::warning("No PRs merged.");
    } else {
        Output::warning(&format!("{}.", summary_parts.join(", ")));
    }

    let show_summary =
        skipped_count > 0 || failed_count > 0 || not_merged_count > 0 || already_merged_count > 0;
    if show_summary {
        println!();
        Output::header("Repository summary");
        for report in &reports {
            match &report.outcome {
                RepoOutcome::Skipped { reason } => {
                    Output::info(&format!("{}: skipped — {}", report.repo_name, reason));
                }
                RepoOutcome::Merged { pr_number } => {
                    Output::success(&format!("{}: merged PR #{}", report.repo_name, pr_number));
                }
                RepoOutcome::AlreadyMerged { pr_number } => {
                    Output::info(&format!(
                        "{}: already merged PR #{}",
                        report.repo_name, pr_number
                    ));
                }
                RepoOutcome::NotMerged { pr_number, reason } => {
                    Output::warning(&format!(
                        "{}: PR #{} not merged — {}",
                        report.repo_name, pr_number, reason
                    ));
                }
                RepoOutcome::Failed { pr_number, reason } => {
                    Output::error(&format!(
                        "{}: PR #{} failed — {}",
                        report.repo_name, pr_number, reason
                    ));
                }
                RepoOutcome::AutoEnabled { pr_number } => {
                    Output::success(&format!(
                        "{}: auto-merge enabled for PR #{}",
                        report.repo_name, pr_number
                    ));
                }
                RepoOutcome::AutoFailed { pr_number, reason } => {
                    Output::warning(&format!(
                        "{}: auto-merge failed for PR #{} — {}",
                        report.repo_name, pr_number, reason
                    ));
                }
            }
        }
    }

    Ok(())
}

/// Check if a repo has changes ahead of its default branch
/// Returns Ok(true) if there are changes, Ok(false) if no changes or on default branch
fn check_repo_for_changes(repo: &RepoInfo) -> anyhow::Result<bool> {
    let git_repo = open_repo(&repo.absolute_path)
        .map_err(|e| anyhow::anyhow!("Failed to open repo: {}", e))?;

    let current = get_current_branch(&git_repo)
        .map_err(|e| anyhow::anyhow!("Failed to get current branch: {}", e))?;

    // Skip if on default branch
    if current == repo.default_branch {
        return Ok(false);
    }

    // Check for commits ahead of default branch using shared helper
    has_commits_ahead(&git_repo, &current, &repo.default_branch)
}
