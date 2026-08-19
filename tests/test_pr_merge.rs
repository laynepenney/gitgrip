//! Integration tests for the PR merge command.
//!
//! Tests the `run_pr_merge()` orchestration using WorkspaceBuilder.
//! Some tests verify behavior without API calls (reference repos, default branch),
//! while others use wiremock to mock the GitHub API.

mod common;

use common::fixtures::WorkspaceBuilder;
use common::git_helpers;
use common::mock_platform::{
    mock_check_runs, mock_get_pr, mock_legacy_combined_status, mock_list_prs, mock_merge_pr,
    mock_merge_pr_behind, mock_pr_reviews, point_repo_at_mock, setup_github_mock,
};
use gitgrip::core::manifest::{PlatformConfig, PlatformType};
use wiremock::http::Method;

// ── No Open PRs ─────────────────────────────────────────────────
// When all repos are on the default branch, no API calls are made
// and the command should report "No open PRs found."

#[tokio::test]
async fn test_pr_merge_no_open_prs() {
    let ws = WorkspaceBuilder::new()
        .add_repo("frontend")
        .add_repo("backend")
        .build();

    let manifest = ws.load_manifest();

    // All repos are on main (default branch) — no PRs to find
    let result = gitgrip::cli::commands::pr::run_pr_merge(
        &ws.workspace_root,
        &manifest,
        &gitgrip::cli::commands::pr::MergeOptions {
            method: None,
            force: false,
            skip_gates: Vec::new(),
            update: false,
            auto: false,
            json: false,
            wait: false,
            timeout: 600,
            delete_branch: true,
            repo_filter: None,
            yes: true,
            allow_all: false,
        },
    )
    .await;

    // Should succeed with "No open PRs found" message (no API calls made)
    assert!(
        result.is_ok(),
        "pr merge with all repos on default branch should succeed: {:?}",
        result.err()
    );
}

// ── Skip Default Branch ─────────────────────────────────────────
// Repos on the default branch are skipped entirely (no API calls).

#[tokio::test]
async fn test_pr_merge_skip_default_branch() {
    let ws = WorkspaceBuilder::new()
        .add_repo("frontend")
        .add_repo("backend")
        .build();

    let manifest = ws.load_manifest();

    // Put frontend on a feature branch, leave backend on main
    git_helpers::create_branch(&ws.repo_path("frontend"), "feat/test");
    git_helpers::commit_file(
        &ws.repo_path("frontend"),
        "test.txt",
        "test content",
        "Add test file",
    );

    // backend stays on main — should be skipped without API call

    // This will try to find a PR for frontend (which will fail since no API mock)
    // but backend should be skipped silently
    let result = gitgrip::cli::commands::pr::run_pr_merge(
        &ws.workspace_root,
        &manifest,
        &gitgrip::cli::commands::pr::MergeOptions {
            method: None,
            force: false,
            skip_gates: Vec::new(),
            update: false,
            auto: false,
            json: false,
            wait: false,
            timeout: 600,
            delete_branch: true,
            repo_filter: None,
            yes: true,
            allow_all: false,
        },
    )
    .await;

    // The call will fail because frontend is on a feature branch and there's no
    // real API to query. But the important thing is backend (on main) was skipped.
    // We can't easily assert this without refactoring, so this test mainly ensures
    // the skip logic doesn't panic.
    //
    // In a full test, we'd mock the API and verify backend never appears in the merge list.
    let _ = result; // Ignore result - we're testing that it doesn't panic
}

// ── Skip Reference Repos ────────────────────────────────────────
// Reference repos are filtered out before any API calls.

#[tokio::test]
async fn test_pr_merge_skip_reference_repos() {
    let ws = WorkspaceBuilder::new()
        .add_reference_repo("ref-lib")
        .add_reference_repo("ref-sdk")
        .build();

    let manifest = ws.load_manifest();

    // Put reference repos on feature branches
    git_helpers::create_branch(&ws.repo_path("ref-lib"), "feat/update");
    git_helpers::commit_file(&ws.repo_path("ref-lib"), "update.txt", "update", "Update");

    // Even though ref-lib is on a feature branch, it should be skipped
    // because it's a reference repo (line 25 filters them out)
    let result = gitgrip::cli::commands::pr::run_pr_merge(
        &ws.workspace_root,
        &manifest,
        &gitgrip::cli::commands::pr::MergeOptions {
            method: None,
            force: false,
            skip_gates: Vec::new(),
            update: false,
            auto: false,
            json: false,
            wait: false,
            timeout: 600,
            delete_branch: true,
            repo_filter: None,
            yes: true,
            allow_all: false,
        },
    )
    .await;

    // Should succeed with "No open PRs found" since all repos are reference repos
    assert!(
        result.is_ok(),
        "pr merge with only reference repos should succeed: {:?}",
        result.err()
    );
}

// ── Mixed: Regular + Reference ──────────────────────────────────
// Regular repos on default branch + reference repos on feature branches.
// All should be skipped without API calls.

#[tokio::test]
async fn test_pr_merge_mixed_repos_all_skipped() {
    let ws = WorkspaceBuilder::new()
        .add_repo("app") // regular repo, will stay on main
        .add_reference_repo("lib") // reference repo
        .build();

    let manifest = ws.load_manifest();

    // Put lib on a feature branch (but it's a reference, so skipped)
    git_helpers::create_branch(&ws.repo_path("lib"), "feat/lib-update");
    git_helpers::commit_file(&ws.repo_path("lib"), "lib.txt", "lib", "Update lib");

    // app stays on main (skipped), lib is reference (skipped)
    let result = gitgrip::cli::commands::pr::run_pr_merge(
        &ws.workspace_root,
        &manifest,
        &gitgrip::cli::commands::pr::MergeOptions {
            method: None,
            force: false,
            skip_gates: Vec::new(),
            update: false,
            auto: false,
            json: false,
            wait: false,
            timeout: 600,
            delete_branch: true,
            repo_filter: None,
            yes: true,
            allow_all: false,
        },
    )
    .await;

    assert!(
        result.is_ok(),
        "pr merge should succeed when all repos are skipped: {:?}",
        result.err()
    );
}

// ══════════════════════════════════════════════════════════════════
// The following tests require API mocking. They are marked with
// #[ignore] until platform injection infrastructure is added.
// ══════════════════════════════════════════════════════════════════

// ── Force Bypasses Checks ───────────────────────────────────────
// The --force flag should merge PRs even if not approved or checks pending.

#[tokio::test]
async fn test_pr_merge_force_bypasses_checks() {
    let (server, _adapter) = setup_github_mock().await;

    let ws = WorkspaceBuilder::new().add_repo("app").build();
    let mut manifest = ws.load_manifest();

    // Switch to feature branch
    git_helpers::create_branch(&ws.repo_path("app"), "feat/test");
    git_helpers::commit_file(
        &ws.repo_path("app"),
        "feature.txt",
        "feature",
        "Add feature",
    );

    // Point manifest at mock GitHub
    let repo_config = manifest.repos.get_mut("app").unwrap();
    repo_config.url = Some("https://github.com/owner/repo.git".to_string());
    repo_config.platform = Some(PlatformConfig {
        platform_type: PlatformType::GitHub,
        base_url: Some(server.uri()),
    });

    mock_list_prs(&server, vec![(42, "feat/test")]).await;
    mock_get_pr(&server, 42, "open", false).await;
    mock_pr_reviews(&server, 42, vec![("COMMENTED", "alice")]).await;
    mock_check_runs(&server, "feat/test", vec![("CI", "in_progress", None)]).await;
    mock_merge_pr(&server, 42, true).await;

    let result = gitgrip::cli::commands::pr::run_pr_merge(
        &ws.workspace_root,
        &manifest,
        &gitgrip::cli::commands::pr::MergeOptions {
            method: None,
            force: true,
            skip_gates: Vec::new(),
            update: false,
            auto: false,
            json: false,
            wait: false,
            timeout: 600,
            delete_branch: true,
            repo_filter: None,
            yes: true,
            allow_all: false,
        },
    )
    .await;

    assert!(
        result.is_ok(),
        "force merge should not error: {:?}",
        result.err()
    );

    let requests = server.received_requests().await.unwrap();
    assert!(
        requests
            .iter()
            .any(|r| r.method == Method::PUT && r.url.path().ends_with("/merge")),
        "expected merge request to be sent"
    );
}

// ── Branch Behind Suggests Update ───────────────────────────────
// When merge fails with BranchBehind, suggest using --update.

#[tokio::test]
async fn test_pr_merge_branch_behind_suggests_update() {
    let (server, _adapter) = setup_github_mock().await;

    let ws = WorkspaceBuilder::new().add_repo("app").build();
    let mut manifest = ws.load_manifest();

    git_helpers::create_branch(&ws.repo_path("app"), "feat/test");
    git_helpers::commit_file(
        &ws.repo_path("app"),
        "feature.txt",
        "feature",
        "Add feature",
    );

    let repo_config = manifest.repos.get_mut("app").unwrap();
    repo_config.url = Some("https://github.com/owner/repo.git".to_string());
    repo_config.platform = Some(PlatformConfig {
        platform_type: PlatformType::GitHub,
        base_url: Some(server.uri()),
    });

    mock_list_prs(&server, vec![(42, "feat/test")]).await;
    mock_get_pr(&server, 42, "open", false).await;
    mock_pr_reviews(&server, 42, vec![("APPROVED", "alice")]).await;
    mock_check_runs(
        &server,
        "feat/test",
        vec![("CI", "completed", Some("success"))],
    )
    .await;
    mock_merge_pr_behind(&server, 42).await;

    let result = gitgrip::cli::commands::pr::run_pr_merge(
        &ws.workspace_root,
        &manifest,
        &gitgrip::cli::commands::pr::MergeOptions {
            method: None,
            force: true,
            skip_gates: Vec::new(),
            update: false,
            auto: false,
            json: false,
            wait: false,
            timeout: 600,
            delete_branch: true,
            repo_filter: None,
            yes: true,
            allow_all: false,
        },
    )
    .await;

    assert!(
        result.is_ok(),
        "branch-behind merge should be handled without crashing: {:?}",
        result.err()
    );

    let requests = server.received_requests().await.unwrap();
    assert!(
        requests
            .iter()
            .any(|r| r.method == Method::PUT && r.url.path().ends_with("/merge")),
        "expected merge attempt for branch-behind case"
    );
}

// ── AllOrNothing Stops on Failure ───────────────────────────────
// With AllOrNothing merge strategy, first failure should stop all merges.

// ── Repo Filter Scopes Merge ───────────────────────────────────
// --repo filter should only merge PRs for the named repos.

#[tokio::test]
async fn test_pr_merge_repo_filter_excludes_non_target() {
    let (server, _adapter) = setup_github_mock().await;

    let ws = WorkspaceBuilder::new()
        .add_repo("frontend")
        .add_repo("backend")
        .build();
    let mut manifest = ws.load_manifest();

    // Put both repos on feature branches
    git_helpers::create_branch(&ws.repo_path("frontend"), "feat/shared");
    git_helpers::commit_file(&ws.repo_path("frontend"), "f.txt", "f", "Frontend change");
    git_helpers::create_branch(&ws.repo_path("backend"), "feat/shared");
    git_helpers::commit_file(&ws.repo_path("backend"), "b.txt", "b", "Backend change");

    // Point both repos at mock GitHub
    for name in ["frontend", "backend"] {
        let repo_config = manifest.repos.get_mut(name).unwrap();
        repo_config.url = Some("https://github.com/owner/repo.git".to_string());
        repo_config.platform = Some(PlatformConfig {
            platform_type: PlatformType::GitHub,
            base_url: Some(server.uri()),
        });
    }

    // Only mock PR for frontend (PR #10). Backend should never be queried.
    mock_list_prs(&server, vec![(10, "feat/shared")]).await;
    mock_get_pr(&server, 10, "open", true).await;
    mock_pr_reviews(&server, 10, vec![("APPROVED", "alice")]).await;
    mock_check_runs(
        &server,
        "feat/shared",
        vec![("CI", "completed", Some("success"))],
    )
    .await;
    mock_merge_pr(&server, 10, true).await;

    // Filter to frontend only, force to bypass readiness checks
    let result = gitgrip::cli::commands::pr::run_pr_merge(
        &ws.workspace_root,
        &manifest,
        &gitgrip::cli::commands::pr::MergeOptions {
            method: None,
            force: true,
            skip_gates: Vec::new(),
            update: false,
            auto: false,
            json: false,
            wait: false,
            timeout: 600,
            delete_branch: true,
            repo_filter: Some(vec!["frontend".to_string()]),
            yes: true,
            allow_all: false,
        },
    )
    .await;

    assert!(
        result.is_ok(),
        "repo-filtered merge should succeed: {:?}",
        result.err()
    );

    // Verify merge was called (for frontend)
    let requests = server.received_requests().await.unwrap();
    let merge_requests: Vec<_> = requests
        .iter()
        .filter(|r| r.method == Method::PUT && r.url.path().ends_with("/merge"))
        .collect();
    assert_eq!(
        merge_requests.len(),
        1,
        "exactly one merge request should be sent (frontend only, not backend)"
    );
}

// ── Repo Filter: No Matching Repos ────────────────────────────
// An explicit selector names something the caller believes exists. Empty is
// therefore a refusal, not a successful operation over an empty set.

#[tokio::test]
async fn test_pr_merge_repo_filter_no_match_is_a_usage_refusal() {
    let ws = WorkspaceBuilder::new().add_repo("app").build();

    let manifest = ws.load_manifest();

    git_helpers::create_branch(&ws.repo_path("app"), "feat/test");
    git_helpers::commit_file(&ws.repo_path("app"), "t.txt", "t", "Test");

    // Filter to nonexistent repo — app should be excluded
    let result = gitgrip::cli::commands::pr::run_pr_merge(
        &ws.workspace_root,
        &manifest,
        &gitgrip::cli::commands::pr::MergeOptions {
            method: None,
            force: false,
            skip_gates: Vec::new(),
            update: false,
            auto: false,
            json: false,
            wait: false,
            timeout: 600,
            delete_branch: true,
            repo_filter: Some(vec!["nonexistent".to_string()]),
            yes: true,
            allow_all: false,
        },
    )
    .await;

    let err = result.expect_err("an unknown explicit --repo selector must fail");
    assert_eq!(gitgrip::cli::outcome::exit_code_for_error(&err), 2);
    assert!(
        err.to_string().contains("nonexistent"),
        "the refusal must name the selector that matched nothing: {err}"
    );
}

// ── Force + Yes Skips Confirmation ─────────────────────────────
// --force --yes merges multiple repos without prompting.

#[tokio::test]
async fn test_pr_merge_force_yes_merges_without_prompt() {
    let (server, _adapter) = setup_github_mock().await;

    let ws = WorkspaceBuilder::new().add_repo("app").build();
    let mut manifest = ws.load_manifest();

    git_helpers::create_branch(&ws.repo_path("app"), "feat/test");
    git_helpers::commit_file(
        &ws.repo_path("app"),
        "feature.txt",
        "feature",
        "Add feature",
    );

    let repo_config = manifest.repos.get_mut("app").unwrap();
    repo_config.url = Some("https://github.com/owner/repo.git".to_string());
    repo_config.platform = Some(PlatformConfig {
        platform_type: PlatformType::GitHub,
        base_url: Some(server.uri()),
    });

    mock_list_prs(&server, vec![(42, "feat/test")]).await;
    mock_get_pr(&server, 42, "open", false).await;
    mock_pr_reviews(&server, 42, vec![]).await;
    mock_check_runs(&server, "feat/test", vec![("CI", "in_progress", None)]).await;
    mock_merge_pr(&server, 42, true).await;

    // --force --yes should merge without stdin prompt
    let result = gitgrip::cli::commands::pr::run_pr_merge(
        &ws.workspace_root,
        &manifest,
        &gitgrip::cli::commands::pr::MergeOptions {
            method: None,
            force: true,
            skip_gates: Vec::new(),
            update: false,
            auto: false,
            json: false,
            wait: false,
            timeout: 600,
            delete_branch: true,
            repo_filter: None,
            yes: true,
            allow_all: false,
        },
    )
    .await;

    assert!(
        result.is_ok(),
        "force+yes merge should succeed: {:?}",
        result.err()
    );
}

#[tokio::test]
#[ignore = "requires platform injection for API mocking"]
async fn test_pr_merge_all_or_nothing_stops_on_failure() {
    // TODO: Implement with mock platform
    // 1. Create workspace with multiple repos on feature branches
    // 2. Configure manifest with merge_strategy: AllOrNothing
    // 3. Mock first repo's merge to fail
    // 4. Verify second repo's merge is never called
    // 5. Verify error message mentions all-or-nothing
}

// ── Command-orchestration regression for the multi-repo scope guard ────────
// (grip#770/grip#771/grip#773, Sentinel reviewer-2 finding on c650a85): the
// committed guard-unit tests all call require_explicit_multi_repo_scope
// directly, so nothing in the original suite would notice the guard's
// call-site being removed from run_pr_merge's own body. This exercises
// run_pr_merge end to end and asserts on the wiremock server's received-
// request log -- the guard must fire before any merge PUT is sent.

#[tokio::test]
async fn test_pr_merge_unscoped_multi_match_sends_zero_merge_puts() {
    let (server, _adapter) = setup_github_mock().await;

    let ws = WorkspaceBuilder::new()
        .add_repo("frontend")
        .add_repo("backend")
        .build();
    let mut manifest = ws.load_manifest();

    for repo_name in ["frontend", "backend"] {
        git_helpers::create_branch(&ws.repo_path(repo_name), "feat/shared-name");
        git_helpers::commit_file(&ws.repo_path(repo_name), "f.txt", "x", "Add f");
        point_repo_at_mock(&mut manifest, repo_name, &server);
    }

    mock_list_prs(&server, vec![(1, "feat/shared-name")]).await;
    mock_get_pr(&server, 1, "open", false).await;
    mock_pr_reviews(&server, 1, vec![("APPROVED", "alice")]).await;
    mock_check_runs(
        &server,
        "feat/shared-name",
        vec![("CI", "completed", Some("success"))],
    )
    .await;
    mock_merge_pr(&server, 1, true).await;

    let result = gitgrip::cli::commands::pr::run_pr_merge(
        &ws.workspace_root,
        &manifest,
        &gitgrip::cli::commands::pr::MergeOptions {
            method: None,
            force: false,
            skip_gates: Vec::new(),
            update: false,
            auto: false,
            json: false,
            wait: false,
            timeout: 600,
            delete_branch: true,
            repo_filter: None, // no --repo
            yes: true,
            allow_all: false, // no --all
        },
    )
    .await;

    assert!(
        result.is_err(),
        "unscoped 2-repo match must be refused, not silently merged"
    );

    let requests = server.received_requests().await.unwrap();
    let merge_puts: Vec<_> = requests
        .iter()
        .filter(|r| r.method == Method::PUT && r.url.path().ends_with("/merge"))
        .collect();
    assert!(
        merge_puts.is_empty(),
        "expected zero merge PUTs, got {}: {:?}",
        merge_puts.len(),
        merge_puts.iter().map(|r| r.url.path()).collect::<Vec<_>>()
    );
}

#[tokio::test]
async fn test_pr_merge_all_flag_proceeds_and_merges_every_match() {
    let (server, _adapter) = setup_github_mock().await;

    let ws = WorkspaceBuilder::new()
        .add_repo("frontend")
        .add_repo("backend")
        .build();
    let mut manifest = ws.load_manifest();

    for repo_name in ["frontend", "backend"] {
        git_helpers::create_branch(&ws.repo_path(repo_name), "feat/shared-name");
        git_helpers::commit_file(&ws.repo_path(repo_name), "f.txt", "x", "Add f");
        point_repo_at_mock(&mut manifest, repo_name, &server);
    }

    mock_list_prs(&server, vec![(1, "feat/shared-name")]).await;
    mock_get_pr(&server, 1, "open", false).await;
    mock_pr_reviews(&server, 1, vec![("APPROVED", "alice")]).await;
    mock_check_runs(
        &server,
        "feat/shared-name",
        vec![("CI", "completed", Some("success"))],
    )
    .await;
    mock_merge_pr(&server, 1, true).await;

    let result = gitgrip::cli::commands::pr::run_pr_merge(
        &ws.workspace_root,
        &manifest,
        &gitgrip::cli::commands::pr::MergeOptions {
            method: None,
            force: false,
            skip_gates: Vec::new(),
            update: false,
            auto: false,
            json: false,
            wait: false,
            timeout: 600,
            delete_branch: true,
            repo_filter: None,
            yes: true,
            allow_all: true, // explicit opt-in
        },
    )
    .await;

    assert!(
        result.is_ok(),
        "--all should proceed past the guard on a genuine multi-match: {:?}",
        result.err()
    );

    let requests = server.received_requests().await.unwrap();
    let merge_puts = requests
        .iter()
        .filter(|r| r.method == Method::PUT && r.url.path().ends_with("/merge"))
        .count();
    assert_eq!(
        merge_puts, 2,
        "expected a merge PUT for each of the two --all-confirmed repos"
    );
}

// ── grip#772: --wait must not block on a branch with no CI configured ──────
//
// Reproduces the exact incident: `gr pr merge --wait --timeout 600` on
// A 2026-07-17 PR ran the full 600s timeout even though the branch
// had zero CI checks configured at all -- GitHub's check-runs API reported
// total_count=0, and its legacy combined-status fallback reports
// state="pending" for a commit with zero posted statuses, the same string it
// uses for "checks are running." `--wait` must treat "confirmed zero checks"
// as immediately resolved, not enter the poll loop at all.

#[tokio::test]
async fn test_pr_merge_wait_does_not_block_when_no_checks_are_configured() {
    let (server, _adapter) = setup_github_mock().await;

    let ws = WorkspaceBuilder::new().add_repo("app").build();
    let mut manifest = ws.load_manifest();

    git_helpers::create_branch(&ws.repo_path("app"), "feat/no-ci");
    git_helpers::commit_file(
        &ws.repo_path("app"),
        "feature.txt",
        "feature",
        "Add feature",
    );

    let repo_config = manifest.repos.get_mut("app").unwrap();
    repo_config.url = Some("https://github.com/owner/repo.git".to_string());
    repo_config.platform = Some(PlatformConfig {
        platform_type: PlatformType::GitHub,
        base_url: Some(server.uri()),
    });

    mock_list_prs(&server, vec![(42, "feat/no-ci")]).await;
    mock_get_pr(&server, 42, "open", false).await;
    mock_pr_reviews(&server, 42, vec![("APPROVED", "alice")]).await;
    // Exact GitHub shape for a ref with no CI configured: check-runs reports
    // zero runs, and the legacy fallback reports "pending" with zero statuses.
    mock_check_runs(&server, "feat/no-ci", vec![]).await;
    mock_legacy_combined_status(&server, "feat/no-ci", "pending", vec![]).await;
    mock_merge_pr(&server, 42, true).await;

    let start = std::time::Instant::now();
    let result = gitgrip::cli::commands::pr::run_pr_merge(
        &ws.workspace_root,
        &manifest,
        &gitgrip::cli::commands::pr::MergeOptions {
            method: None,
            force: false,
            skip_gates: Vec::new(),
            update: false,
            auto: false,
            json: false,
            wait: true,
            timeout: 5,
            delete_branch: true,
            repo_filter: None,
            yes: true,
            allow_all: false,
        },
    )
    .await;
    let elapsed = start.elapsed();

    assert!(
        result.is_ok(),
        "merge with --wait on a no-CI-configured branch should succeed, not time out: {:?}",
        result.err()
    );
    assert!(
        elapsed < std::time::Duration::from_secs(10),
        "expected --wait to resolve immediately (no checks configured means nothing to poll \
         for), took {:?} instead -- this is grip#772's exact symptom if it regresses \
         (the loop's own re-poll sleep is 15s, so a regression would take at least that long)",
        elapsed
    );

    let requests = server.received_requests().await.unwrap();
    assert!(
        requests
            .iter()
            .any(|r| r.method == Method::PUT && r.url.path().ends_with("/merge")),
        "expected the merge to actually proceed, not just avoid timing out"
    );
}

// ── Gate decomposition ──────────────────────────────────────────
// `--force` waived approval, checks and mergeability together. On a workspace
// that ratifies by review COMMENTS rather than formal approvals, the approval
// gate can never pass — so `--force` became mandatory on every merge and took
// the other gates with it, invisibly. These pin that waiving one waives ONE.

/// Waiving `approval` must NOT waive `checks`.
///
/// This is the test that makes the decomposition real rather than cosmetic. The
/// PR here has no approval AND a still-running check. Under `--force` it merges.
/// Under `--skip-gate approval` it must refuse, because the caller waived the
/// gate that does not apply to their workflow and nothing else.
#[tokio::test]
async fn test_skip_gate_approval_does_not_also_waive_checks() {
    let (server, _adapter) = setup_github_mock().await;

    let ws = WorkspaceBuilder::new().add_repo("app").build();
    let mut manifest = ws.load_manifest();

    git_helpers::create_branch(&ws.repo_path("app"), "feat/test");
    git_helpers::commit_file(
        &ws.repo_path("app"),
        "feature.txt",
        "feature",
        "Add feature",
    );

    let repo_config = manifest.repos.get_mut("app").unwrap();
    repo_config.url = Some("https://github.com/owner/repo.git".to_string());
    repo_config.platform = Some(PlatformConfig {
        platform_type: PlatformType::GitHub,
        base_url: Some(server.uri()),
    });

    mock_list_prs(&server, vec![(42, "feat/test")]).await;
    mock_get_pr(&server, 42, "open", false).await;
    // Reviewed by comment only — the ratification this workspace actually uses,
    // and never a formal approval.
    mock_pr_reviews(&server, 42, vec![("COMMENTED", "alice")]).await;
    // And a check that has not finished.
    mock_check_runs(&server, "feat/test", vec![("CI", "in_progress", None)]).await;
    mock_merge_pr(&server, 42, true).await;

    let result = gitgrip::cli::commands::pr::run_pr_merge(
        &ws.workspace_root,
        &manifest,
        &gitgrip::cli::commands::pr::MergeOptions {
            method: None,
            force: false,
            skip_gates: vec![gitgrip::cli::commands::pr::MergeGate::Approval],
            update: false,
            auto: false,
            json: false,
            wait: false,
            timeout: 600,
            delete_branch: true,
            repo_filter: None,
            yes: true,
            allow_all: false,
        },
    )
    .await;

    let err = result.expect_err("a live readiness gate must refuse the merge");
    assert_eq!(
        gitgrip::cli::outcome::exit_code_for_error(&err),
        2,
        "readiness refusal must be distinguishable from operational failure"
    );

    let requests = server.received_requests().await.unwrap();
    assert!(
        !requests
            .iter()
            .any(|r| r.method == Method::PUT && r.url.path().ends_with("/merge")),
        "checks were still running and only `approval` was waived — no merge must be sent. \
         If this fires, --skip-gate is behaving as a blanket --force."
    );
}

#[tokio::test]
async fn test_readiness_refusal_reaches_the_process_exit_status() {
    let (server, _adapter) = setup_github_mock().await;

    let ws = WorkspaceBuilder::new().add_repo("app").build();
    let mut manifest = ws.load_manifest();

    git_helpers::create_branch(&ws.repo_path("app"), "feat/test");
    git_helpers::commit_file(
        &ws.repo_path("app"),
        "feature.txt",
        "feature",
        "Add feature",
    );

    point_repo_at_mock(&mut manifest, "app", &server);
    let manifest_yaml = serde_yaml::to_string(&manifest).unwrap();
    std::fs::write(
        ws.workspace_root.join(".gitgrip/spaces/main/gripspace.yml"),
        manifest_yaml,
    )
    .unwrap();

    mock_list_prs(&server, vec![(42, "feat/test")]).await;
    mock_get_pr(&server, 42, "open", false).await;
    mock_pr_reviews(&server, 42, vec![("COMMENTED", "alice")]).await;
    mock_check_runs(&server, "feat/test", vec![("CI", "in_progress", None)]).await;
    mock_merge_pr(&server, 42, true).await;

    let output = tokio::process::Command::new(assert_cmd::cargo::cargo_bin!("gr"))
        .current_dir(&ws.workspace_root)
        .env("GITHUB_TOKEN", "test")
        .args([
            "pr",
            "merge",
            "--skip-gate",
            "approval",
            "--method",
            "merge",
            "--yes",
        ])
        .output()
        .await
        .unwrap();

    assert_eq!(
        output.status.code(),
        Some(2),
        "readiness refusal must survive dispatch and main; stdout={} stderr={}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );
    assert!(
        !String::from_utf8_lossy(&output.stderr).contains("Error: merge refused"),
        "main must not append a generic error after the command rendered the actionable refusal"
    );

    let requests = server.received_requests().await.unwrap();
    assert!(
        !requests
            .iter()
            .any(|r| r.method == Method::PUT && r.url.path().ends_with("/merge")),
        "a refusal with exit 2 must still send no merge request"
    );
}

/// Waiving `approval` on a PR whose only failing gate IS approval must proceed.
///
/// The negative control for the test above. Without it, a `--skip-gate` that
/// simply refused everything would pass — "waives nothing" and "waives only what
/// was named" are indistinguishable from a single blocked case.
#[tokio::test]
async fn test_skip_gate_approval_allows_a_comment_ratified_merge() {
    let (server, _adapter) = setup_github_mock().await;

    let ws = WorkspaceBuilder::new().add_repo("app").build();
    let mut manifest = ws.load_manifest();

    git_helpers::create_branch(&ws.repo_path("app"), "feat/test");
    git_helpers::commit_file(
        &ws.repo_path("app"),
        "feature.txt",
        "feature",
        "Add feature",
    );

    let repo_config = manifest.repos.get_mut("app").unwrap();
    repo_config.url = Some("https://github.com/owner/repo.git".to_string());
    repo_config.platform = Some(PlatformConfig {
        platform_type: PlatformType::GitHub,
        base_url: Some(server.uri()),
    });

    mock_list_prs(&server, vec![(42, "feat/test")]).await;
    // `merged: false` — the mock derives `mergeable` as `!merged`, so this is a
    // PR that is open and mergeable. Passing `true` here made it UNmergeable and
    // the merge was correctly blocked by the `mergeable` gate, which looked like
    // the waiver failing. The scenario was wrong, not the waiver.
    mock_get_pr(&server, 42, "open", false).await;
    mock_pr_reviews(&server, 42, vec![("COMMENTED", "alice")]).await;
    mock_check_runs(
        &server,
        "feat/test",
        vec![("CI", "completed", Some("success"))],
    )
    .await;
    mock_merge_pr(&server, 42, true).await;

    let result = gitgrip::cli::commands::pr::run_pr_merge(
        &ws.workspace_root,
        &manifest,
        &gitgrip::cli::commands::pr::MergeOptions {
            method: None,
            force: false,
            skip_gates: vec![gitgrip::cli::commands::pr::MergeGate::Approval],
            update: false,
            auto: false,
            json: false,
            wait: false,
            timeout: 600,
            delete_branch: true,
            repo_filter: None,
            yes: true,
            allow_all: false,
        },
    )
    .await;

    assert!(result.is_ok(), "should not error: {:?}", result.err());

    let requests = server.received_requests().await.unwrap();
    assert!(
        requests
            .iter()
            .any(|r| r.method == Method::PUT && r.url.path().ends_with("/merge")),
        "approval was the only failing gate and it was waived by name — the merge must proceed"
    );
}
