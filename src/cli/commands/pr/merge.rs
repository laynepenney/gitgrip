//! PR merge command implementation

use super::create::has_commits_ahead;
use crate::cli::outcome::CliOutcomeError;
use crate::cli::output::Output;
use crate::core::manifest::Manifest;
use crate::core::repo::{
    get_manifest_repo_info, require_explicit_multi_repo_scope, validate_repo_filters_known,
    RepoInfo,
};
use crate::git::{get_current_branch, open_repo, path_exists};
use crate::platform::traits::{HostingPlatform, PlatformError};
use crate::platform::{get_platform_adapter, CheckState, MergeMethod, StatusCheckResult};
use std::io::Write;
use std::path::Path;
use std::sync::Arc;

/// This command's internal readiness classification for a PR's checks,
/// derived from a platform's [`StatusCheckResult`] via [`resolve_check_status`].
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum CheckStatus {
    Passing,
    Failing,
    Pending,
    Unknown,
}

/// Resolve a platform's status-check result into this command's internal
/// [`CheckStatus`]. Pure and synchronous so it can be pinned directly against
/// synthetic [`StatusCheckResult`] values, without exercising the HTTP or
/// sleep/retry machinery around either call site. Both the initial fetch and
/// the `--wait` re-poll loop call this exact function so the decision can
/// never diverge between them (grip#776 finding 3).
fn resolve_check_status(status: &StatusCheckResult) -> CheckStatus {
    if !status.checks_configured {
        // No CI is configured for this ref at all -- not a real
        // pending/passing signal, nothing to wait on (grip#772).
        CheckStatus::Passing
    } else {
        match status.state {
            CheckState::Failure => CheckStatus::Failing,
            CheckState::Pending => CheckStatus::Pending,
            CheckState::Success => CheckStatus::Passing,
        }
    }
}

/// After a `Merge`, assert the resulting commit actually has two parents.
///
/// Checked against the local repository, not the platform's response. The API
/// reports that a merge happened; it does not report WHICH strategy produced
/// the commit, and the incident behind this was a squash that reported success
/// exactly like a merge. Fetching and counting parents asks the repository what
/// is actually there.
///
/// Only meaningful for `Merge` -- squash and rebase produce single-parent
/// commits by design, so asserting two parents for them would be wrong rather
/// than strict.
///
/// A failure here is loud and it is NOT recoverable by this command: the merge
/// already happened. The point is that the operator finds out now, from the
/// tool, rather than days later from a broken ancestry -- which is how the
/// original incident was discovered.
fn verify_merge_commit_parents(
    local_path: &std::path::Path,
    base: &str,
    method: MergeMethod,
) -> Option<String> {
    if method != MergeMethod::Merge {
        return None;
    }
    let repo = open_repo(local_path).ok()?;
    // Fetch so the local ref reflects the merge that just happened remotely.
    let _ = crate::git::remote::fetch_remote(&repo, "origin");

    // A readable repository whose base ref we cannot read is NOT the same
    // state as an unreadable checkout, and must not share its silence. The
    // caller prints nothing for `None`, so returning `None` here would report
    // "could not look" in the exact shape of "looked, and it was fine".
    let ref_name = format!("refs/remotes/origin/{}", base);
    let commit = match repo
        .find_reference(&ref_name)
        .and_then(|reference| reference.peel_to_commit())
    {
        Ok(commit) => commit,
        Err(e) => {
            return Some(format!(
                "could not check the merge result: {} is not readable ({}). \
                 The merge was requested as {:?}, and a merge commit has two \
                 parents, but this check did not run -- so nothing here says \
                 the merge looks correct.",
                ref_name, e, method
            ));
        }
    };
    let parents = commit.parent_count();

    if parents >= 2 {
        None
    } else {
        Some(format!(
            "origin/{} is now {} with {} parent{} -- a merge commit has two. \
             The merge was requested as {:?} but the result does not look like \
             one, so the branch head may no longer be reachable from {}.",
            base,
            &commit.id().to_string()[..8],
            parents,
            if parents == 1 { "" } else { "s" },
            method,
            base
        ))
    }
}

/// Confirm the chosen merge method is one the host actually permits.
///
/// This REPLACED an auto-detector that queried the allowed methods and took the
/// first of squash > merge > rebase. That is how a workspace whose policy is
/// merge-commit-only got squashes from its own tooling: the tool actively
/// selected the one method the policy forbids, on every repo that permitted it.
///
/// Choosing is now the manifest's job, not the host's. What the host is asked is
/// only whether the choice is permitted -- and if it is not, this REFUSES rather
/// than substituting. Substitution is the original defect in a politer form: the
/// operator asked for one strategy, a different one happened, and the only way
/// to find out was to count parents afterwards.
///
/// An unreachable host is not treated as a refusal. Failing the merge because a
/// capability query timed out would be its own outage, so an errored query is
/// reported and the chosen method stands -- the post-merge parent assertion is
/// the backstop for that path.
async fn confirm_method_allowed(
    platform: &dyn HostingPlatform,
    owner: &str,
    repo: &str,
    method: MergeMethod,
) -> Result<(), String> {
    match platform.get_allowed_merge_methods(owner, repo).await {
        Ok(allowed) => {
            let permitted = match method {
                MergeMethod::Merge => allowed.merge,
                MergeMethod::Squash => allowed.squash,
                MergeMethod::Rebase => allowed.rebase,
            };
            if permitted {
                Ok(())
            } else {
                Err(format!(
                    "{}/{} does not permit {:?} merges. Refusing rather than \
                     silently using a different strategy -- pass --method \
                     explicitly if another one is intended.",
                    owner, repo, method
                ))
            }
        }
        Err(_) => Ok(()),
    }
}

/// A single pre-merge gate, nameable so it can be waived individually.
///
/// `--force` used to be one boolean that suppressed every check at once. On a
/// gripspace whose ratification convention is review COMMENTS rather than formal
/// GitHub approvals, the approval gate can never pass, so `--force` became
/// mandatory on every merge -- and with it went the checks, mergeability and
/// method assertions nobody intended to waive.
///
/// A gate that must always be bypassed does not gate; it trains the bypass. The
/// point of naming them is that waiving one says which one, out loud, at the
/// moment of the act.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum MergeGate {
    /// The PR carries a formal platform approval.
    Approval,
    /// Status checks are passing (not failing, not still running).
    Checks,
    /// The platform reports the PR as mergeable.
    Mergeable,
}

impl MergeGate {
    /// The name a caller passes to `--skip-gate`.
    pub fn as_str(self) -> &'static str {
        match self {
            MergeGate::Approval => "approval",
            MergeGate::Checks => "checks",
            MergeGate::Mergeable => "mergeable",
        }
    }

    /// Every gate, so `--force` and the help text cannot drift from the enum.
    pub fn all() -> [MergeGate; 3] {
        [MergeGate::Approval, MergeGate::Checks, MergeGate::Mergeable]
    }

    /// Parse a caller-supplied name. Unknown names are an error rather than a
    /// silent no-op: a misspelled gate that quietly waives nothing reads exactly
    /// like a gate that passed.
    pub fn parse(name: &str) -> anyhow::Result<Self> {
        let wanted = name.trim().to_ascii_lowercase();
        MergeGate::all()
            .into_iter()
            .find(|g| g.as_str() == wanted)
            .ok_or_else(|| {
                anyhow::anyhow!(
                    "unknown merge gate '{}'. Known gates: {}",
                    name.trim(),
                    MergeGate::all()
                        .iter()
                        .map(|g| g.as_str())
                        .collect::<Vec<_>>()
                        .join(", ")
                )
            })
    }
}

/// The suppression notes belonging to one PR, selected by its index.
///
/// A free function so the attribution can be tested directly. The previous form
/// was an inline filter matching a SUBSTRING of the rendered message, which
/// mis-attributes in two ways that a fix aimed at the first would leave open:
/// "PR #77" is a substring of "PR #777", and this command is multi-repo so two
/// different repos can each carry a PR #42.
///
/// The line this feeds is the one telling an operator exactly what is being
/// suppressed on exactly this PR. A suppression they do not recognise teaches
/// them to distrust the line, and a safety disclosure people distrust stops
/// being a safety disclosure.
fn notes_for(index: usize, suppressed: &[(usize, String)]) -> Vec<&str> {
    suppressed
        .iter()
        .filter(|(i, _)| *i == index)
        .map(|(_, note)| note.as_str())
        .collect()
}

/// Options for the PR merge command.
pub struct MergeOptions<'a> {
    pub method: Option<&'a crate::platform::MergeMethod>,
    /// Waive EVERY gate. Retained for compatibility; prefer naming the one you
    /// mean via `skip_gates`, so the record says what was actually waived.
    pub force: bool,
    /// Gates waived by name. Composes with `force`, which implies all of them.
    pub skip_gates: Vec<MergeGate>,
    pub update: bool,
    pub auto: bool,
    pub json: bool,
    pub wait: bool,
    pub timeout: u64,
    pub delete_branch: bool,
    pub repo_filter: Option<Vec<String>>,
    pub yes: bool,
    pub allow_all: bool,
}

/// Run the PR merge command
pub async fn run_pr_merge(
    workspace_root: &Path,
    manifest: &Manifest,
    opts: &MergeOptions<'_>,
) -> anyhow::Result<()> {
    validate_repo_filters_known(manifest, opts.repo_filter.as_deref())
        .map_err(|error| CliOutcomeError::refusal(error.to_string()))?;

    if !opts.json {
        Output::header("Merging pull requests...");
        println!();
    }

    let repos: Vec<RepoInfo> = manifest
        .repos
        .iter()
        .filter_map(|(name, config)| {
            RepoInfo::from_config(
                name,
                config,
                workspace_root,
                &manifest.settings,
                manifest.remotes.as_ref(),
            )
        })
        .filter(|r| !r.reference) // Skip reference repos
        .filter(|r| {
            if let Some(ref filter) = opts.repo_filter {
                filter.iter().any(|f| f == &r.name)
            } else {
                true
            }
        })
        .collect();

    // Precedence: explicit --method, then the manifest, then a merge commit.
    // The host is never asked to CHOOSE -- only, later, whether the choice is
    // permitted. Letting the host choose is what produced squashes in a
    // merge-commit-only workspace.
    let merge_method = match opts.method.copied() {
        Some(explicit) => explicit,
        None => match manifest.settings.merge_method {
            crate::core::manifest::DefaultMergeMethod::Merge => MergeMethod::Merge,
            crate::core::manifest::DefaultMergeMethod::Squash => MergeMethod::Squash,
            crate::core::manifest::DefaultMergeMethod::Rebase => MergeMethod::Rebase,
        },
    };

    // Also check manifest repo if configured and not filtered out
    let mut all_repos = repos.clone();
    if let Some(manifest_repo) = get_manifest_repo_info(manifest, workspace_root) {
        let manifest_included = match opts.repo_filter {
            Some(ref filter) => filter
                .iter()
                .any(|f| f == &manifest_repo.name || f == "manifest"),
            None => true,
        };
        if manifest_included {
            match check_repo_for_changes(&manifest_repo) {
                Ok(true) => {
                    all_repos.push(manifest_repo);
                }
                Ok(false) => {
                    Output::info("manifest: no changes, skipping");
                }
                Err(e) => {
                    Output::warning(&format!("manifest: could not check for changes: {}", e));
                }
            }
        }
    }

    // Collect PRs to merge
    struct PRToMerge {
        repo_name: String,
        owner: String,
        repo: String,
        branch: String,
        /// The branch this merge is irreversible INTO. Carried so the act-time
        /// line can name it: "which PR" and "into what" are different facts and
        /// only the second one says where the commits land.
        base: String,
        /// Local checkout, so the merge can be verified against the REPOSITORY
        /// rather than against the API's report of it.
        local_path: std::path::PathBuf,
        pr_number: u64,
        platform: Arc<dyn crate::platform::HostingPlatform>,
        approved: bool,
        check_status: CheckStatus,
        mergeable: bool,
    }

    let mut prs_to_merge: Vec<PRToMerge> = Vec::new();
    let mut json_skipped: Vec<String> = Vec::new();
    // A repo whose PR lookup failed belongs in neither of the two collections
    // above: it is not a merge candidate and it was not skipped. Without a
    // third one, "we looked and found nothing" and "we could not look" arrive
    // at the summary as the same state.
    let mut lookup_failures: Vec<String> = Vec::new();

    for repo in &all_repos {
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

        // Skip if on target branch
        if branch == repo.target_branch() {
            continue;
        }

        let platform = get_platform_adapter(repo.platform_type, repo.platform_base_url.as_deref());

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
                let check_status = match platform
                    .get_status_checks(&repo.owner, &repo.repo, &branch)
                    .await
                {
                    Ok(status) => {
                        // Successfully got check status
                        if !status.checks_configured {
                            Output::info(&format!(
                                "{}: no CI checks configured for branch '{}', proceeding",
                                repo.name, branch
                            ));
                        }
                        resolve_check_status(&status)
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

                prs_to_merge.push(PRToMerge {
                    repo_name: repo.name.clone(),
                    owner: repo.owner.clone(),
                    repo: repo.repo.clone(),
                    branch: branch.clone(),
                    base: repo.target_branch().to_string(),
                    local_path: repo.absolute_path.clone(),
                    pr_number: pr.number,
                    platform,
                    approved,
                    check_status,
                    mergeable,
                });
            }
            Ok(None) => {
                if !opts.json {
                    Output::info(&format!("{}: no open PR for this branch", repo.name));
                }
                json_skipped.push(repo.name.clone());
            }
            Err(e) => {
                if !opts.json {
                    Output::error(&format!("{}: {}", repo.name, e));
                }
                lookup_failures.push(repo.name.clone());
            }
        }
    }

    if prs_to_merge.is_empty() {
        // An empty candidate list has two causes that read identically here.
        // Only one of them is an absence of PRs; the other is an absence of
        // knowledge, and reporting it as the first is a false statement the
        // exit code then endorses.
        if !lookup_failures.is_empty() {
            anyhow::bail!(
                "could not determine PR state for {} of {} repositories: {}",
                lookup_failures.len(),
                all_repos.len(),
                lookup_failures.join(", ")
            );
        }
        println!("No open PRs found for any repository.");
        println!("Repositories checked: {}", all_repos.len());
        return Ok(());
    }

    // Same guard as `gr pr edit`/`gr pr review`: an unscoped multi-repo match is
    // ambiguous, not consent. --repo already narrows opts.repo_filter above; --all
    // is the explicit opt-in when the caller genuinely wants every matched repo.
    require_explicit_multi_repo_scope(
        &prs_to_merge,
        opts.repo_filter.is_some(),
        opts.allow_all,
        "gr pr merge",
        |pr| {
            format!(
                "{} PR #{} on {}/{}",
                pr.repo_name, pr.pr_number, pr.owner, pr.repo
            )
        },
    )?;

    // Show which repos have PRs and which don't
    let repos_with_prs: Vec<String> = prs_to_merge.iter().map(|p| p.repo_name.clone()).collect();
    let repos_without_prs: Vec<String> = all_repos
        .iter()
        .filter(|r| !repos_with_prs.contains(&r.name))
        .map(|r| r.name.clone())
        .collect();

    if !repos_without_prs.is_empty() {
        Output::info(&format!(
            "Merging {} repo(s) with open PRs. {} repo(s) have no open PRs and will be skipped.",
            prs_to_merge.len(),
            repos_without_prs.len()
        ));
        for repo_name in &repos_without_prs {
            Output::info(&format!("  - {}: skipped (no open PR)", repo_name));
        }
        println!();
    }

    // Wait for checks to pass if --wait
    if opts.wait {
        let any_pending = prs_to_merge
            .iter()
            .any(|pr| matches!(pr.check_status, CheckStatus::Pending));

        if any_pending {
            let start = std::time::Instant::now();
            let timeout_duration = std::time::Duration::from_secs(opts.timeout);

            let spinner = Output::spinner("Waiting for checks to pass...");

            loop {
                let pending_count = prs_to_merge
                    .iter()
                    .filter(|pr| matches!(pr.check_status, CheckStatus::Pending))
                    .count();

                if pending_count == 0 {
                    break;
                }

                if start.elapsed() > timeout_duration {
                    spinner.finish_with_message("Timed out waiting for checks");
                    anyhow::bail!(
                        "Timed out after {} seconds waiting for checks to pass",
                        opts.timeout
                    );
                }

                // Early exit if all remaining non-passing checks have definitively failed
                let all_resolved = prs_to_merge
                    .iter()
                    .all(|pr| !matches!(pr.check_status, CheckStatus::Pending));
                if all_resolved {
                    break;
                }

                let elapsed = start.elapsed().as_secs();
                spinner.set_message(format!(
                    "Waiting for checks... ({} pending, {}s elapsed)",
                    pending_count, elapsed
                ));

                tokio::time::sleep(std::time::Duration::from_secs(15)).await;

                // Re-poll check status for pending PRs
                for pr in &mut prs_to_merge {
                    if !matches!(pr.check_status, CheckStatus::Pending) {
                        continue;
                    }

                    match pr
                        .platform
                        .get_status_checks(&pr.owner, &pr.repo, &pr.branch)
                        .await
                    {
                        Ok(status) => {
                            pr.check_status = resolve_check_status(&status);

                            match pr.check_status {
                                CheckStatus::Passing => {
                                    Output::success(&format!(
                                        "{} PR #{}: checks passed",
                                        pr.repo_name, pr.pr_number
                                    ));
                                }
                                CheckStatus::Failing => {
                                    Output::error(&format!(
                                        "{} PR #{}: checks failed",
                                        pr.repo_name, pr.pr_number
                                    ));
                                }
                                _ => {}
                            }
                        }
                        Err(_) => {
                            // Keep as pending, will retry next iteration
                        }
                    }
                }
            }

            spinner.finish_with_message("All checks resolved");
            println!();
        }
    }

    // When --force is used, confirm which PRs will be merged
    if opts.force && !opts.yes && !opts.json && prs_to_merge.len() > 1 {
        Output::warning(&format!(
            "--force will merge {} PRs across these repos:",
            prs_to_merge.len()
        ));
        for pr in &prs_to_merge {
            println!("  - {} PR #{}", pr.repo_name, pr.pr_number);
        }
        print!("\nProceed? [y/N] ");
        std::io::stdout().flush()?;
        let mut input = String::new();
        std::io::stdin().read_line(&mut input)?;
        if !input.trim().eq_ignore_ascii_case("y") {
            println!("Aborted. Use --repo to scope to specific repos.");
            return Ok(());
        }
        println!();
    }

    // Which gates the caller waived, and by which flag. `--force` implies all
    // of them; naming one waives exactly one. Recorded rather than folded into a
    // boolean, because the whole point is that the record says what was waived.
    let waived: Vec<MergeGate> = if opts.force {
        MergeGate::all().to_vec()
    } else {
        opts.skip_gates.clone()
    };
    let is_waived = |gate: MergeGate| waived.contains(&gate);

    // Evaluate every gate, then subtract the waived ones. Evaluating first means
    // a waiver still reports what it suppressed -- a gate that was never run
    // cannot say whether it would have failed, and "no output" is exactly how a
    // suppressed failure disguises itself as a pass.
    let mut blocking = Vec::new();
    // Keyed by INDEX into `prs_to_merge`, never by re-reading the PR number out
    // of the rendered message. Two collisions live in that shortcut, and the
    // second survives a fix aimed only at the first:
    //
    //   * "PR #77" is a SUBSTRING of "PR #777", and one invocation can carry
    //     both, so #77's merge line would print #777's suppression note
    //   * this command is multi-repo, so two DIFFERENT repos can each have a
    //     PR #42 -- matching on the number alone still mis-attributes
    //
    // An index is unique across both. A value reconstructed from a rendering is
    // a value that can be reconstructed wrong; carrying it cannot be.
    let mut suppressed: Vec<(usize, String)> = Vec::new();
    for (index, pr) in prs_to_merge.iter().enumerate() {
        let mut failures: Vec<(MergeGate, String)> = Vec::new();
        if !pr.approved {
            failures.push((
                MergeGate::Approval,
                format!("{} PR #{}: no formal approval", pr.repo_name, pr.pr_number),
            ));
        }
        match pr.check_status {
            CheckStatus::Failing => failures.push((
                MergeGate::Checks,
                format!("{} PR #{}: checks failing", pr.repo_name, pr.pr_number),
            )),
            CheckStatus::Pending => failures.push((
                MergeGate::Checks,
                format!(
                    "{} PR #{}: checks still running",
                    pr.repo_name, pr.pr_number
                ),
            )),
            CheckStatus::Unknown => {
                Output::warning(&format!(
                    "{} PR #{}: check status unknown - proceeding with caution",
                    pr.repo_name, pr.pr_number
                ));
            }
            CheckStatus::Passing => {}
        }
        if !pr.mergeable {
            failures.push((
                MergeGate::Mergeable,
                format!(
                    "{} PR #{}: not mergeable (branch may be behind base — try --update)",
                    pr.repo_name, pr.pr_number
                ),
            ));
        }
        for (gate, message) in failures {
            if is_waived(gate) {
                suppressed.push((index, format!("{} [{}]", message, gate.as_str())));
            } else {
                blocking.push(format!("{} [{}]", message, gate.as_str()));
            }
        }
    }

    if !blocking.is_empty() {
        Output::warning("Some PRs have issues:");
        for issue in &blocking {
            println!("  - {}", issue);
        }
        println!();
        println!(
            "Waive one gate with --skip-gate <{}>, or --force to waive all.",
            MergeGate::all()
                .iter()
                .map(|g| g.as_str())
                .collect::<Vec<_>>()
                .join("|")
        );
        return Err(CliOutcomeError::reported_refusal("merge refused by readiness gate").into());
    }

    // Auto-merge flow: enable auto-merge and return early
    if opts.auto {
        let mut success_count = 0;
        let mut error_count = 0;

        for pr in prs_to_merge {
            let effective_method = merge_method;
            if let Err(reason) =
                confirm_method_allowed(pr.platform.as_ref(), &pr.owner, &pr.repo, effective_method)
                    .await
            {
                Output::warning(&reason);
                error_count += 1;
                continue;
            }

            let spinner = Output::spinner(&format!(
                "Enabling auto-merge for {} PR #{} ({:?})...",
                pr.repo_name, pr.pr_number, effective_method
            ));

            match pr
                .platform
                .enable_auto_merge(&pr.owner, &pr.repo, pr.pr_number, Some(effective_method))
                .await
            {
                Ok(true) => {
                    spinner.finish_with_message(format!(
                        "{}: PR #{} will auto-merge when checks pass",
                        pr.repo_name, pr.pr_number
                    ));
                    success_count += 1;
                }
                Ok(false) => {
                    spinner.finish_with_message(format!(
                        "{}: PR #{} auto-merge could not be enabled",
                        pr.repo_name, pr.pr_number
                    ));
                    error_count += 1;
                }
                Err(e) => {
                    spinner.finish_with_message(format!("{}: failed - {}", pr.repo_name, e));
                    error_count += 1;
                }
            }
        }

        println!();
        if error_count == 0 {
            Output::success(&format!(
                "Auto-merge enabled for {} PR(s). They will merge when all checks pass.",
                success_count
            ));
        } else {
            Output::warning(&format!(
                "{} auto-merge enabled, {} failed",
                success_count, error_count
            ));
        }

        // Case 3: any per-repo failure makes the run a failure, including a
        // mixed run. The warning above is read by a human; the exit code is
        // the only part a script sees, and it reported this as done.
        if error_count > 0 || !lookup_failures.is_empty() {
            anyhow::bail!(
                "{} of {} auto-merge attempts failed{}",
                error_count,
                success_count + error_count,
                describe_lookup_failures(&lookup_failures)
            );
        }

        return Ok(());
    }

    // Merge PRs
    let mut success_count = 0;
    let mut error_count = 0;

    #[derive(serde::Serialize)]
    struct JsonMergedPr {
        repo: String,
        pr_number: u64,
    }
    #[derive(serde::Serialize)]
    struct JsonFailedPr {
        repo: String,
        pr_number: u64,
        reason: String,
    }
    let mut json_merged: Vec<JsonMergedPr> = Vec::new();
    let mut json_failed_prs: Vec<JsonFailedPr> = Vec::new();

    for (pr_index, pr) in prs_to_merge.into_iter().enumerate() {
        let effective_method = merge_method;
        if let Err(reason) =
            confirm_method_allowed(pr.platform.as_ref(), &pr.owner, &pr.repo, effective_method)
                .await
        {
            Output::warning(&reason);
            error_count += 1;
            json_failed_prs.push(JsonFailedPr {
                repo: pr.repo_name.clone(),
                pr_number: pr.pr_number,
                reason,
            });
            continue;
        }

        // THE MOMENT OF THE IRREVERSIBLE ACT. Printed here -- not earlier from
        // the plan, not afterwards from the result -- and durably rather than
        // in a spinner that erases itself.
        //
        // Everything that goes wrong with this command goes wrong in the gap
        // between what it is about to do and what the operator believes it is
        // about to do. `gr pr merge` takes no PR number: it merges whatever PR
        // the current branch owns. So the resolved slug, number, branch, base
        // and method are the facts that close that gap, and they are only facts
        // at this point in the code.
        if !opts.json {
            let mut line = format!(
                "MERGING {}/{}#{}  {} -> {}  method={:?}",
                pr.owner, pr.repo, pr.pr_number, pr.branch, pr.base, effective_method
            );
            if !waived.is_empty() {
                line.push_str(&format!(
                    "  WAIVED={}",
                    waived
                        .iter()
                        .map(|g| g.as_str())
                        .collect::<Vec<_>>()
                        .join(",")
                ));
            }
            println!("{}", line);
            for note in notes_for(pr_index, &suppressed) {
                println!("  suppressed: {}", note);
            }
        }

        let spinner = if !opts.json {
            Some(Output::spinner(&format!(
                "Merging {} PR #{} ({:?})...",
                pr.repo_name, pr.pr_number, effective_method
            )))
        } else {
            None
        };

        let merge_result = pr
            .platform
            .merge_pull_request(
                &pr.owner,
                &pr.repo,
                pr.pr_number,
                Some(effective_method),
                opts.delete_branch,
            )
            .await;

        // Handle BranchBehind with --update retry
        let merge_result = match merge_result {
            Err(PlatformError::BranchBehind(ref msg)) if opts.update => {
                if let Some(ref s) = spinner {
                    s.finish_with_message(format!(
                        "{}: branch behind base, updating...",
                        pr.repo_name
                    ));
                }
                let update_spinner = if !opts.json {
                    Some(Output::spinner(&format!(
                        "Updating {} PR #{} branch...",
                        pr.repo_name, pr.pr_number
                    )))
                } else {
                    None
                };

                match pr
                    .platform
                    .update_branch(&pr.owner, &pr.repo, pr.pr_number)
                    .await
                {
                    Ok(true) => {
                        if let Some(ref s) = update_spinner {
                            s.finish_with_message(format!(
                                "{}: branch updated, retrying merge...",
                                pr.repo_name
                            ));
                        }
                        tokio::time::sleep(std::time::Duration::from_secs(3)).await;

                        let retry_spinner = if !opts.json {
                            Some(Output::spinner(&format!(
                                "Merging {} PR #{}...",
                                pr.repo_name, pr.pr_number
                            )))
                        } else {
                            None
                        };

                        match pr
                            .platform
                            .merge_pull_request(
                                &pr.owner,
                                &pr.repo,
                                pr.pr_number,
                                Some(effective_method),
                                opts.delete_branch,
                            )
                            .await
                        {
                            Ok(merged) => {
                                let verified = match pr
                                    .platform
                                    .get_pull_request(&pr.owner, &pr.repo, pr.pr_number)
                                    .await
                                {
                                    Ok(verified_pr) => verified_pr.merged,
                                    Err(_) => merged,
                                };

                                if verified {
                                    if let Some(ref s) = retry_spinner {
                                        s.finish_with_message(format!(
                                            "{}: merged PR #{}",
                                            pr.repo_name, pr.pr_number
                                        ));
                                    }
                                    success_count += 1;
                                    json_merged.push(JsonMergedPr {
                                        repo: pr.repo_name.clone(),
                                        pr_number: pr.pr_number,
                                    });
                                } else if merged {
                                    if let Some(ref s) = retry_spinner {
                                        s.finish_with_message(format!(
                                            "{}: PR #{} merge reported success but PR is not merged",
                                            pr.repo_name, pr.pr_number
                                        ));
                                    }
                                    error_count += 1;
                                    json_failed_prs.push(JsonFailedPr {
                                        repo: pr.repo_name.clone(),
                                        pr_number: pr.pr_number,
                                        reason: "merge reported success but PR is not merged"
                                            .to_string(),
                                    });
                                } else {
                                    if let Some(ref s) = retry_spinner {
                                        s.finish_with_message(format!(
                                            "{}: PR #{} was already merged",
                                            pr.repo_name, pr.pr_number
                                        ));
                                    }
                                    success_count += 1;
                                    json_merged.push(JsonMergedPr {
                                        repo: pr.repo_name.clone(),
                                        pr_number: pr.pr_number,
                                    });
                                }
                                continue;
                            }
                            Err(e) => Err(e),
                        }
                    }
                    Ok(false) => {
                        if let Some(ref s) = update_spinner {
                            s.finish_with_message(format!(
                                "{}: branch already up to date",
                                pr.repo_name
                            ));
                        }
                        Err(PlatformError::BranchBehind(msg.clone()))
                    }
                    Err(update_err) => {
                        if let Some(ref s) = update_spinner {
                            s.finish_with_message(format!(
                                "{}: branch update failed - {}",
                                pr.repo_name, update_err
                            ));
                        }
                        Err(PlatformError::BranchBehind(msg.clone()))
                    }
                }
            }
            other => other,
        };

        match merge_result {
            Ok(merged) => {
                let verified = match pr
                    .platform
                    .get_pull_request(&pr.owner, &pr.repo, pr.pr_number)
                    .await
                {
                    Ok(verified_pr) => verified_pr.merged,
                    Err(_) => merged,
                };

                if verified {
                    if let Some(ref s) = spinner {
                        s.finish_with_message(format!(
                            "{}: merged PR #{}",
                            pr.repo_name, pr.pr_number
                        ));
                    }
                    if let Some(problem) =
                        verify_merge_commit_parents(&pr.local_path, &pr.base, effective_method)
                    {
                        Output::warning(&problem);
                    }
                    success_count += 1;
                    json_merged.push(JsonMergedPr {
                        repo: pr.repo_name.clone(),
                        pr_number: pr.pr_number,
                    });
                } else if merged {
                    if let Some(ref s) = spinner {
                        s.finish_with_message(format!(
                            "{}: PR #{} merge reported success but PR is not merged — check branch protection or required checks",
                            pr.repo_name, pr.pr_number
                        ));
                    }
                    error_count += 1;
                    json_failed_prs.push(JsonFailedPr {
                        repo: pr.repo_name.clone(),
                        pr_number: pr.pr_number,
                        reason: "merge reported success but PR is not merged".to_string(),
                    });
                } else {
                    if let Some(ref s) = spinner {
                        s.finish_with_message(format!(
                            "{}: PR #{} was already merged",
                            pr.repo_name, pr.pr_number
                        ));
                    }
                    success_count += 1;
                    json_merged.push(JsonMergedPr {
                        repo: pr.repo_name.clone(),
                        pr_number: pr.pr_number,
                    });
                }
            }
            Err(PlatformError::BranchBehind(_)) => {
                if let Some(ref s) = spinner {
                    s.finish_with_message(format!(
                        "{}: PR #{} branch is behind base branch",
                        pr.repo_name, pr.pr_number
                    ));
                }
                if !opts.json {
                    Output::info(
                        "  Hint: use 'gr pr merge --update' to update the branch and retry",
                    );
                }
                error_count += 1;
                json_failed_prs.push(JsonFailedPr {
                    repo: pr.repo_name.clone(),
                    pr_number: pr.pr_number,
                    reason: "branch is behind base branch".to_string(),
                });
            }
            Err(PlatformError::BranchProtected(ref msg)) => {
                if let Some(ref s) = spinner {
                    s.finish_with_message(format!("{}: {}", pr.repo_name, msg));
                }
                if !opts.json {
                    Output::info(
                        "  Hint: use 'gr pr merge --auto' to enable auto-merge when checks pass",
                    );
                    Output::info(&format!(
                        "  Or:   gh pr merge {} --admin --repo {}/{}",
                        pr.pr_number, pr.owner, pr.repo
                    ));
                }
                error_count += 1;
                json_failed_prs.push(JsonFailedPr {
                    repo: pr.repo_name.clone(),
                    pr_number: pr.pr_number,
                    reason: msg.clone(),
                });
            }
            Err(e) => {
                if let Some(ref s) = spinner {
                    s.finish_with_message(format!("{}: failed - {}", pr.repo_name, e));
                }
                json_failed_prs.push(JsonFailedPr {
                    repo: pr.repo_name.clone(),
                    pr_number: pr.pr_number,
                    reason: e.to_string(),
                });
                error_count += 1;

                if !opts.force
                    && manifest.settings.merge_strategy
                        == crate::core::manifest::MergeStrategy::AllOrNothing
                {
                    if !opts.json {
                        Output::error(
                            "Stopping due to all-or-nothing merge strategy. Use --force to bypass.",
                        );
                    }
                    return Err(e.into());
                }
                if opts.force
                    && manifest.settings.merge_strategy
                        == crate::core::manifest::MergeStrategy::AllOrNothing
                    && !opts.json
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
    if opts.json {
        #[derive(serde::Serialize)]
        struct JsonPrMergeResult {
            success: bool,
            merged: Vec<JsonMergedPr>,
            failed: Vec<JsonFailedPr>,
            skipped: Vec<String>,
        }

        let result = JsonPrMergeResult {
            success: error_count == 0,
            merged: json_merged,
            failed: json_failed_prs,
            skipped: json_skipped,
        };
        println!("{}", serde_json::to_string_pretty(&result)?);
    } else {
        println!();
        if error_count == 0 {
            Output::success(&format!("Successfully merged {} PR(s).", success_count));
        } else {
            Output::warning(&format!(
                "{} merged, {} failed:",
                success_count, error_count
            ));
            for failed in &json_failed_prs {
                println!(
                    "  {}: PR #{} - {}",
                    failed.repo, failed.pr_number, failed.reason
                );
            }
        }
    }

    // Case 3, on the path that matters most: a run that failed to merge some
    // of the PRs it selected has already emitted its JSON document and its
    // human summary by this point. Both are truthful. The exit code was not.
    if error_count > 0 || !lookup_failures.is_empty() {
        anyhow::bail!(
            "{} of {} PR merges failed{}",
            error_count,
            success_count + error_count,
            describe_lookup_failures(&lookup_failures)
        );
    }

    Ok(())
}

/// Render the lookup-failure tail of a summary, or nothing when every repo
/// was successfully inspected. Kept separate so the three case-3 exits phrase
/// the same fact identically.
fn describe_lookup_failures(failures: &[String]) -> String {
    if failures.is_empty() {
        String::new()
    } else {
        format!(
            "; PR state could not be determined for {}",
            failures.join(", ")
        )
    }
}

/// Check if a repo has changes ahead of its default branch
/// Returns Ok(true) if there are changes, Ok(false) if no changes or on default branch
fn check_repo_for_changes(repo: &RepoInfo) -> anyhow::Result<bool> {
    let git_repo = open_repo(&repo.absolute_path)
        .map_err(|e| anyhow::anyhow!("Failed to open repo: {}", e))?;

    let current = get_current_branch(&git_repo)
        .map_err(|e| anyhow::anyhow!("Failed to get current branch: {}", e))?;

    // Skip if on target branch
    if current == repo.target_branch() {
        return Ok(false);
    }

    // Check for commits ahead of target branch using shared helper
    has_commits_ahead(&git_repo, &current, repo.target_branch())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn status(checks_configured: bool, state: CheckState) -> StatusCheckResult {
        StatusCheckResult {
            state,
            statuses: Vec::new(),
            checks_configured,
        }
    }

    // ── resolve_check_status: the single seam both the initial fetch and the
    // ── --wait re-poll loop call (grip#776 finding 3). Pure and synchronous,
    // ── so these pin the decision directly with no HTTP or sleep involved.

    #[test]
    fn test_resolve_check_status_not_configured_is_passing() {
        // grip#772: a ref with no CI configured at all has nothing to wait
        // on, regardless of what `state` the platform reports alongside it.
        assert_eq!(
            resolve_check_status(&status(false, CheckState::Pending)),
            CheckStatus::Passing
        );
    }

    #[test]
    fn test_resolve_check_status_configured_success_is_passing() {
        assert_eq!(
            resolve_check_status(&status(true, CheckState::Success)),
            CheckStatus::Passing
        );
    }

    #[test]
    fn test_resolve_check_status_configured_failure_is_failing() {
        assert_eq!(
            resolve_check_status(&status(true, CheckState::Failure)),
            CheckStatus::Failing
        );
    }

    #[test]
    fn test_resolve_check_status_configured_pending_is_pending() {
        assert_eq!(
            resolve_check_status(&status(true, CheckState::Pending)),
            CheckStatus::Pending
        );
    }
}

#[cfg(test)]
mod gate_tests {
    use super::MergeGate;

    #[test]
    fn every_known_gate_round_trips_through_its_name() {
        for gate in MergeGate::all() {
            let parsed = MergeGate::parse(gate.as_str()).expect("known gate must parse");
            assert_eq!(parsed, gate, "{} did not round-trip", gate.as_str());
        }
    }

    #[test]
    fn gate_names_are_case_insensitive_and_trimmed() {
        assert_eq!(MergeGate::parse("APPROVAL").unwrap(), MergeGate::Approval);
        assert_eq!(MergeGate::parse("  checks ").unwrap(), MergeGate::Checks);
    }

    /// An unknown gate name must be an ERROR, never a silent no-op.
    ///
    /// This is the whole failure mode the flag exists to remove. A misspelled
    /// `--skip-gate aproval` that quietly waives nothing produces a run that
    /// looks exactly like one where the gate passed -- and the operator, having
    /// typed a waiver, believes the opposite of what happened.
    #[test]
    fn an_unknown_gate_is_rejected_rather_than_ignored() {
        let err = MergeGate::parse("aproval").expect_err("a typo must not be accepted");
        let message = err.to_string();
        assert!(
            message.contains("unknown merge gate"),
            "message should name the problem: {message}"
        );
        assert!(
            message.contains("approval")
                && message.contains("checks")
                && message.contains("mergeable"),
            "message should list the valid gates so the typo is fixable: {message}"
        );
    }

    #[test]
    fn an_empty_gate_name_is_rejected() {
        assert!(MergeGate::parse("").is_err());
        assert!(MergeGate::parse("   ").is_err());
    }

    /// `all()` is hand-written, so it can drift from the enum. This match is
    /// exhaustive on purpose: adding a variant without adding it to `all()`
    /// fails to COMPILE rather than silently shrinking what `--force` waives.
    ///
    /// A compile error is the right instrument here. A runtime test can only
    /// check the variants it was told about, which is the same gap that let a
    /// parsed-and-dropped field through three review rounds elsewhere today.
    #[test]
    fn the_enumeration_cannot_silently_grow() {
        fn enumerated(gate: MergeGate) -> bool {
            match gate {
                MergeGate::Approval => MergeGate::all().contains(&gate),
                MergeGate::Checks => MergeGate::all().contains(&gate),
                MergeGate::Mergeable => MergeGate::all().contains(&gate),
            }
        }
        for gate in MergeGate::all() {
            assert!(enumerated(gate), "{} missing from all()", gate.as_str());
        }
        assert_eq!(
            MergeGate::all().len(),
            3,
            "a gate was added or removed; update --force's waiver set and this count deliberately"
        );
    }

    #[test]
    fn gate_names_are_distinct() {
        let mut names: Vec<&str> = MergeGate::all().iter().map(|g| g.as_str()).collect();
        names.sort_unstable();
        let before = names.len();
        names.dedup();
        assert_eq!(before, names.len(), "two gates share a name: {names:?}");
    }
}

#[cfg(test)]
mod attribution_tests {
    use super::notes_for;

    /// PR numbers where one is a prefix of another, in a single invocation.
    ///
    /// This is the exact collision the previous implementation had: it filtered
    /// notes by `message.contains("PR #77")`, and "PR #777" contains that. The
    /// merge line for #77 printed #777's suppression as its own.
    ///
    /// It could only ever over-attribute, never omit — which is why it is narrow
    /// and why it still mattered: the line's entire job is saying precisely what
    /// is suppressed on precisely this PR.
    #[test]
    fn a_pr_number_that_is_a_prefix_of_another_does_not_steal_its_notes() {
        let suppressed = vec![
            (
                0usize,
                "app PR #77: no formal approval [approval]".to_string(),
            ),
            (1usize, "app PR #777: checks failing [checks]".to_string()),
        ];
        assert_eq!(
            notes_for(0, &suppressed),
            vec!["app PR #77: no formal approval [approval]"],
            "#77 must not receive #777's note"
        );
        assert_eq!(
            notes_for(1, &suppressed),
            vec!["app PR #777: checks failing [checks]"],
        );
    }

    /// Two repos can each carry the SAME PR number in one invocation.
    ///
    /// Matching on the number alone — the obvious repair for the substring bug —
    /// still mis-attributes here. Only an identifier unique across the whole run
    /// closes both, which is why the notes are keyed by index rather than by any
    /// value re-read from the rendered text.
    #[test]
    fn the_same_pr_number_in_two_repos_keeps_its_notes_separate() {
        let suppressed = vec![
            (
                0usize,
                "frontend PR #42: no formal approval [approval]".to_string(),
            ),
            (
                1usize,
                "backend PR #42: checks failing [checks]".to_string(),
            ),
        ];
        assert_eq!(
            notes_for(0, &suppressed),
            vec!["frontend PR #42: no formal approval [approval]"],
        );
        assert_eq!(
            notes_for(1, &suppressed),
            vec!["backend PR #42: checks failing [checks]"],
        );
    }

    #[test]
    fn a_pr_with_several_suppressions_gets_all_of_them_and_only_them() {
        let suppressed = vec![
            (
                0usize,
                "app PR #1: no formal approval [approval]".to_string(),
            ),
            (1usize, "other PR #2: checks failing [checks]".to_string()),
            (0usize, "app PR #1: checks failing [checks]".to_string()),
        ];
        assert_eq!(notes_for(0, &suppressed).len(), 2);
        assert_eq!(notes_for(1, &suppressed).len(), 1);
    }

    /// The negative control: no suppressions means no line, not a stray one.
    #[test]
    fn a_pr_with_no_suppressions_reports_none() {
        let suppressed = vec![(1usize, "other PR #2: checks failing [checks]".to_string())];
        assert!(notes_for(0, &suppressed).is_empty());
    }
}

#[cfg(test)]
mod method_default_tests {
    use crate::core::manifest::{DefaultMergeMethod, ManifestSettings};
    use crate::platform::MergeMethod;

    /// The whole incident in one assertion.
    ///
    /// Auto-detection took the first of squash > merge > rebase, so on any repo
    /// permitting squash the tool chose it -- in a workspace whose policy is
    /// merge-commit-only, and on private repos where no hosting ruleset could
    /// reject the result.
    #[test]
    fn the_default_is_a_merge_commit_not_a_squash() {
        assert_eq!(
            ManifestSettings::default().merge_method,
            DefaultMergeMethod::Merge,
            "an unconfigured workspace must get a real merge commit"
        );
    }

    /// The mapping the command uses when no --method is given.
    ///
    /// Written as an exhaustive match so a new variant fails to COMPILE rather
    /// than silently falling through to a default -- which is the same class of
    /// silent substitution this change exists to remove.
    #[test]
    fn every_configured_method_maps_to_the_one_it_names() {
        fn mapped(setting: DefaultMergeMethod) -> MergeMethod {
            match setting {
                DefaultMergeMethod::Merge => MergeMethod::Merge,
                DefaultMergeMethod::Squash => MergeMethod::Squash,
                DefaultMergeMethod::Rebase => MergeMethod::Rebase,
            }
        }
        assert_eq!(mapped(DefaultMergeMethod::Merge), MergeMethod::Merge);
        assert_eq!(mapped(DefaultMergeMethod::Squash), MergeMethod::Squash);
        assert_eq!(mapped(DefaultMergeMethod::Rebase), MergeMethod::Rebase);
    }

    /// A workspace CAN choose otherwise -- this is a default, not a prohibition.
    ///
    /// The negative control for the test above: if the setting were ignored and
    /// merge hardcoded, that test would still pass and this one would not.
    #[test]
    fn a_workspace_can_configure_a_different_method() {
        let toml = r#"
repos: {}
settings:
  merge_method: squash
"#;
        let parsed: serde_yaml::Value = serde_yaml::from_str(toml).expect("yaml parses");
        let method = parsed["settings"]["merge_method"].as_str();
        assert_eq!(
            method,
            Some("squash"),
            "the setting must be readable as written"
        );
    }

    /// `merge_strategy` and `merge_method` are unrelated and easily confused.
    ///
    /// Named because the issue called the similarity out: one is cross-repo
    /// coordination, the other is the git strategy. Changing one expecting the
    /// other is a plausible mistake, and this pins that they are separate fields.
    #[test]
    fn merge_strategy_and_merge_method_are_independent() {
        let settings = ManifestSettings {
            merge_method: DefaultMergeMethod::Squash,
            ..Default::default()
        };
        assert_eq!(
            settings.merge_strategy,
            ManifestSettings::default().merge_strategy,
            "changing the git method must not disturb cross-repo coordination"
        );
    }
}

#[cfg(test)]
mod parent_assertion_tests {
    use super::verify_merge_commit_parents;
    use crate::platform::MergeMethod;
    use std::path::Path;

    /// Build a repo whose `origin/main` points at a commit with `parents` parents.
    fn repo_with_head_parents(dir: &Path, parents: usize) {
        let repo = git2::Repository::init(dir).expect("init");
        let sig = git2::Signature::now("t", "t@example.invalid").expect("sig");
        let tree = {
            let mut idx = repo.index().expect("index");
            let oid = idx.write_tree().expect("write tree");
            repo.find_tree(oid).expect("tree")
        };
        let base = repo
            .commit(None, &sig, &sig, "base", &tree, &[])
            .expect("base commit");
        let base_commit = repo.find_commit(base).expect("find base");

        let head = if parents >= 2 {
            let side = repo
                .commit(None, &sig, &sig, "side", &tree, &[&base_commit])
                .expect("side commit");
            let side_commit = repo.find_commit(side).expect("find side");
            repo.commit(
                None,
                &sig,
                &sig,
                "merge",
                &tree,
                &[&base_commit, &side_commit],
            )
            .expect("merge commit")
        } else {
            repo.commit(None, &sig, &sig, "single", &tree, &[&base_commit])
                .expect("single commit")
        };

        repo.reference("refs/remotes/origin/main", head, true, "test")
            .expect("ref");
    }

    /// The incident, as a test: a single-parent head after a requested Merge.
    ///
    /// This is what the original squash produced -- the API reported success,
    /// the output said nothing, and the only way to find out was to count
    /// parents by hand afterwards. Now the command says it.
    #[test]
    fn a_single_parent_head_after_a_requested_merge_is_reported() {
        let dir = tempfile::tempdir().expect("tempdir");
        repo_with_head_parents(dir.path(), 1);

        let problem = verify_merge_commit_parents(dir.path(), "main", MergeMethod::Merge);
        let message = problem.expect("a single-parent head must be reported");
        assert!(
            message.contains("1 parent"),
            "the message must state what was actually found: {message}"
        );
        assert!(
            message.contains("two"),
            "and what a merge commit should have: {message}"
        );
    }

    /// The negative control. Without it, a function that always complains passes.
    #[test]
    fn a_real_merge_commit_is_not_reported() {
        let dir = tempfile::tempdir().expect("tempdir");
        repo_with_head_parents(dir.path(), 2);
        assert!(
            verify_merge_commit_parents(dir.path(), "main", MergeMethod::Merge).is_none(),
            "two parents is exactly what a merge commit has"
        );
    }

    /// Squash and rebase produce single-parent commits BY DESIGN.
    ///
    /// Asserting two parents for them would be wrong rather than strict, and
    /// would make the guard fire on every correct squash -- which is how a
    /// warning becomes noise and then becomes ignored.
    #[test]
    fn squash_and_rebase_are_not_expected_to_have_two_parents() {
        let dir = tempfile::tempdir().expect("tempdir");
        repo_with_head_parents(dir.path(), 1);
        for method in [MergeMethod::Squash, MergeMethod::Rebase] {
            assert!(
                verify_merge_commit_parents(dir.path(), "main", method).is_none(),
                "{method:?} produces one parent by design"
            );
        }
    }

    /// An unreadable repository must not be reported as a bad merge.
    ///
    /// The check is best-effort by design: failing a merge because a local
    /// checkout is missing would invent an outage. But it must fail SILENT
    /// rather than fail LOUD-AND-WRONG, and that distinction deserves its own
    /// case rather than being inferred from the `?` operators.
    #[test]
    fn an_unreadable_repository_reports_nothing_rather_than_a_false_alarm() {
        let dir = tempfile::tempdir().expect("tempdir");
        let missing = dir.path().join("not-a-repo");
        assert!(verify_merge_commit_parents(&missing, "main", MergeMethod::Merge).is_none());
    }

    /// A READABLE repository whose named base ref does not exist.
    ///
    /// This is the state our own topology produces. `base` is the PR's base
    /// branch, and a base branch can be deleted -- or, before the bind above
    /// it was corrected, `base` could be a stale manifest target naming a
    /// branch that no longer exists at all. `find_reference` then fails on a
    /// repository that is perfectly readable, and a bare `?` collapsed that
    /// onto the same `None` as an unreadable checkout.
    ///
    /// Those are two different states and only one of them was reasoned
    /// about. "I looked and it was fine" and "I could not look" must not be
    /// the same observation, because the caller prints nothing for `None` --
    /// so the silent branch reads as clearance in the one direction the
    /// check cannot fail.
    #[test]
    fn an_absent_base_ref_in_a_readable_repository_is_reported() {
        let dir = tempfile::tempdir().expect("tempdir");
        repo_with_head_parents(dir.path(), 1);

        // Control: the fixture must be able to produce a finding at all.
        // Without this, a function that had been broken into always
        // returning None would pass the assertion below by accident.
        assert!(
            verify_merge_commit_parents(dir.path(), "main", MergeMethod::Merge).is_some(),
            "control: this fixture reports a single-parent head for a ref that EXISTS"
        );

        let problem = verify_merge_commit_parents(dir.path(), "sprint-39", MergeMethod::Merge);
        let message = problem.expect("an absent base ref must be reported, not silently cleared");
        assert!(
            message.contains("sprint-39"),
            "the message must name the ref it could not read: {message}"
        );
        assert!(
            message.contains("could not"),
            "and must say it could not check, never that the merge looked fine: {message}"
        );
    }
}
