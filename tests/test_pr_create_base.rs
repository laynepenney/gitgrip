//! `gr pr create --base` and the pre-flight base-existence check.
//!
//! `run_pr_create` resolves the base once, honoring `--base`, and then had a
//! second expression that re-derived it from the manifest's stored target. The
//! two disagreed whenever `--base` was passed, which is precisely when the
//! stored target is stale -- passing `--base` is what we do BECAUSE it is
//! stale. These tests pin the resolved base as the single source for the
//! check, its messages, and the created PR.

mod common;

use common::fixtures::WorkspaceBuilder;
use common::git_helpers;
use common::mock_platform::{
    mock_branch_exists, mock_create_pr, mock_not_found, point_repo_at_mock, setup_github_mock,
};
use wiremock::http::Method;

/// Put the repo one commit ahead of `origin/<base>` on a feature branch, so
/// the command's own selection step groups it and execution reaches the check.
fn repo_ahead_of(ws: &common::fixtures::WorkspaceFixture, repo: &str, base: &str, feature: &str) {
    let path = ws.repo_path(repo);
    git_helpers::create_branch(&path, base);
    git_helpers::commit_file(&path, "base.txt", "base", "Add base");
    git_helpers::push_branch(&path, "origin", base);
    git_helpers::create_branch(&path, feature);
    git_helpers::commit_file(&path, "feature.txt", "feature", "Add feature");
}

/// The stale stored target must not be consulted when `--base` is explicit.
///
/// Before the fix the command resolved `dev`, then asked the platform whether
/// `sprint-39` existed, got 404 for a branch nobody named, and skipped the
/// repo reporting a base the operator never asked for. The PR that GitHub
/// would have accepted was never attempted.
#[tokio::test]
async fn base_override_is_the_branch_that_gets_checked_and_the_pr_that_gets_opened() {
    let (server, _adapter) = setup_github_mock().await;

    let ws = WorkspaceBuilder::new().add_repo("frontend").build();
    let mut manifest = ws.load_manifest();

    // A retired sprint branch: still stored, gone from the remote.
    manifest.settings.target = Some("sprint-39".to_string());

    repo_ahead_of(&ws, "frontend", "dev", "feat/thing");
    point_repo_at_mock(&mut manifest, "frontend", &server);

    mock_branch_exists(&server, "owner", "repo", "dev").await;
    mock_not_found(&server, "/repos/owner/repo/branches/sprint-39").await;
    mock_create_pr(&server, 7, "https://github.com/owner/repo/pull/7").await;

    let filter = vec!["frontend".to_string()];
    let result = gitgrip::cli::commands::pr::run_pr_create(
        &ws.workspace_root,
        &manifest,
        Some("Add feature"),
        None,
        false,
        false,
        false,
        Some(&filter),
        Some("dev"),
        false,
    )
    .await;
    assert!(result.is_ok(), "command errored: {result:?}");

    let requests = server.received_requests().await.unwrap();
    let branch_checks: Vec<String> = requests
        .iter()
        .filter(|r| r.method == Method::GET && r.url.path().contains("/branches/"))
        .map(|r| r.url.path().to_string())
        .collect();

    // Control: the command must have performed a pre-flight check at all.
    // Without it, deleting the check entirely would pass the assertion below.
    assert!(
        !branch_checks.is_empty(),
        "control: a pre-flight base check must happen; saw none"
    );
    assert!(
        branch_checks.iter().any(|p| p.ends_with("/branches/dev")),
        "the base the operator asked for must be the one checked; got {branch_checks:?}"
    );
    assert!(
        !branch_checks
            .iter()
            .any(|p| p.ends_with("/branches/sprint-39")),
        "the stale stored target must not be consulted when --base is explicit; got {branch_checks:?}"
    );

    let posts: Vec<_> = requests
        .iter()
        .filter(|r| r.method == Method::POST && r.url.path().ends_with("/pulls"))
        .collect();
    assert_eq!(
        posts.len(),
        1,
        "the PR must actually be created against the requested base"
    );
}

/// The negative control for the test above: with NO `--base`, the stored
/// target is still the right thing to check. Without this case, "always use
/// the override" and "ignore the manifest entirely" are indistinguishable.
#[tokio::test]
async fn without_an_override_the_stored_target_is_still_what_gets_checked() {
    let (server, _adapter) = setup_github_mock().await;

    let ws = WorkspaceBuilder::new().add_repo("frontend").build();
    let mut manifest = ws.load_manifest();
    manifest.settings.target = Some("release".to_string());

    repo_ahead_of(&ws, "frontend", "release", "feat/thing");
    point_repo_at_mock(&mut manifest, "frontend", &server);

    mock_branch_exists(&server, "owner", "repo", "release").await;
    mock_create_pr(&server, 8, "https://github.com/owner/repo/pull/8").await;

    let filter = vec!["frontend".to_string()];
    let result = gitgrip::cli::commands::pr::run_pr_create(
        &ws.workspace_root,
        &manifest,
        Some("Add feature"),
        None,
        false,
        false,
        false,
        Some(&filter),
        None,
        false,
    )
    .await;
    assert!(result.is_ok(), "command errored: {result:?}");

    let requests = server.received_requests().await.unwrap();
    assert!(
        requests
            .iter()
            .any(|r| r.method == Method::GET && r.url.path().ends_with("/branches/release")),
        "with no override the stored target is the base and must be the one checked"
    );
}
