//! PR merge command implementation

use crate::cli::output::Output;
use crate::core::manifest::Manifest;
use crate::core::repo::RepoInfo;
use crate::git::{get_current_branch, open_repo, path_exists};
use crate::platform::{detect_platform, get_platform_adapter, CheckState, MergeMethod};
use std::path::PathBuf;
use std::sync::Arc;

/// Run the PR merge command
pub async fn run_pr_merge(
    workspace_root: &PathBuf,
    manifest: &Manifest,
    method: Option<&str>,
    force: bool,
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

    // Collect PRs to merge
    struct PRToMerge {
        repo_name: String,
        owner: String,
        repo: String,
        pr_number: u64,
        platform: Arc<dyn crate::platform::HostingPlatform>,
        approved: bool,
        checks_pass: bool,
        mergeable: bool,
    }

    let mut prs_to_merge: Vec<PRToMerge> = Vec::new();

    for repo in &repos {
        if !path_exists(&repo.absolute_path) {
            continue;
        }

        let git_repo = match open_repo(&repo.absolute_path) {
            Ok(r) => r,
            Err(_) => continue,
        };

        let branch = match get_current_branch(&git_repo) {
            Ok(b) => b,
            Err(_) => continue,
        };

        // Skip if on default branch
        if branch == repo.default_branch {
            continue;
        }

        let platform_type = detect_platform(&repo.url);
        let platform = get_platform_adapter(platform_type, None);

        match platform
            .find_pr_by_branch(&repo.owner, &repo.repo, &branch)
            .await
        {
            Ok(Some(pr)) => {
                // Get PR details
                let (approved, mergeable) = match platform
                    .get_pull_request(&repo.owner, &repo.repo, pr.number)
                    .await
                {
                    Ok(full_pr) => {
                        let is_approved = platform
                            .is_pull_request_approved(&repo.owner, &repo.repo, pr.number)
                            .await
                            .unwrap_or(false);
                        (is_approved, full_pr.mergeable.unwrap_or(false))
                    }
                    Err(_) => (false, false),
                };

                // Get status checks
                let checks_pass = match platform
                    .get_status_checks(&repo.owner, &repo.repo, &branch)
                    .await
                {
                    Ok(status) => status.state == CheckState::Success,
                    Err(_) => false,
                };

                prs_to_merge.push(PRToMerge {
                    repo_name: repo.name.clone(),
                    owner: repo.owner.clone(),
                    repo: repo.repo.clone(),
                    pr_number: pr.number,
                    platform,
                    approved,
                    checks_pass,
                    mergeable,
                });
            }
            Ok(None) => {
                Output::info(&format!("{}: no open PR for this branch", repo.name));
            }
            Err(e) => {
                Output::error(&format!("{}: {}", repo.name, e));
            }
        }
    }

    if prs_to_merge.is_empty() {
        println!("No PRs to merge.");
        return Ok(());
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
            if !pr.checks_pass {
                issues.push(format!(
                    "{} PR #{}: checks failing",
                    pr.repo_name, pr.pr_number
                ));
            }
            if !pr.mergeable {
                issues.push(format!(
                    "{} PR #{}: not mergeable (conflicts?)",
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

    // Merge PRs
    let mut success_count = 0;
    let mut error_count = 0;

    for pr in prs_to_merge {
        let spinner = Output::spinner(&format!("Merging {} PR #{}...", pr.repo_name, pr.pr_number));

        match pr
            .platform
            .merge_pull_request(
                &pr.owner,
                &pr.repo,
                pr.pr_number,
                Some(merge_method),
                true, // delete branch
            )
            .await
        {
            Ok(merged) => {
                if merged {
                    spinner.finish_with_message(format!(
                        "{}: merged PR #{}",
                        pr.repo_name, pr.pr_number
                    ));
                    success_count += 1;
                } else {
                    spinner.finish_with_message(format!(
                        "{}: PR #{} was already merged",
                        pr.repo_name, pr.pr_number
                    ));
                    success_count += 1;
                }
            }
            Err(e) => {
                spinner.finish_with_message(format!("{}: failed - {}", pr.repo_name, e));
                error_count += 1;

                // Check for all-or-nothing merge strategy
                if manifest.settings.merge_strategy
                    == crate::core::manifest::MergeStrategy::AllOrNothing
                {
                    Output::error("Stopping due to all-or-nothing merge strategy.");
                    return Err(e.into());
                }
            }
        }
    }

    // Summary
    println!();
    if error_count == 0 {
        Output::success(&format!("Successfully merged {} PR(s).", success_count));
    } else {
        Output::warning(&format!("{} merged, {} failed", success_count, error_count));
    }

    Ok(())
}
