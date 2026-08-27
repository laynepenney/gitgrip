//! `gr pr create` must not report success after printing its own failure.
//!
//! `run_pr_create` collected per-repo failures into `all_failed_repos`, printed
//! `Failed to create N PR(s):` with every one of them, and then returned
//! `Ok(())`. Anything gating on the exit status -- a shell script, CI, an agent
//! deciding whether to continue -- read that as success while the command was
//! saying the opposite on stdout.
//!
//! The predicate was never missing. Four lines above the return, the `--json`
//! branch already computes `success: !created.is_empty() && failed.is_empty()`
//! and serializes it. The truth was computed and then discarded, exactly as the
//! merge base was in #917.
//!
//! Scope, deliberately narrow (grip#886 is an umbrella over nine verbs): this
//! covers ONLY "failures were reported and the exit status disagreed." The
//! zero-created/zero-failed no-op still exits 0 and is left alone -- that is
//! #804/#836/#839's question, and answering it here would change the exit
//! status of a successful `--dry-run`-shaped run without a witness for it.

mod common;

use common::fixtures::WorkspaceBuilder;
use common::git_helpers;
use common::mock_platform::{
    mock_branch_exists, mock_create_pr, mock_create_pr_validation_error, point_repo_at_mock,
    setup_github_mock,
};
use wiremock::http::Method;

fn repo_ahead_of(ws: &common::fixtures::WorkspaceFixture, repo: &str, base: &str, feature: &str) {
    let path = ws.repo_path(repo);
    git_helpers::create_branch(&path, base);
    git_helpers::commit_file(&path, "base.txt", "base", "Add base");
    git_helpers::push_branch(&path, "origin", base);
    git_helpers::create_branch(&path, feature);
    git_helpers::commit_file(&path, "feature.txt", "feature", "Add feature");
}

/// THE WITNESS. The platform refuses the PR; the command reports the failure
/// and must not simultaneously claim success through its exit status.
#[tokio::test]
async fn a_reported_failure_must_not_exit_zero() {
    let (server, _adapter) = setup_github_mock().await;

    let ws = WorkspaceBuilder::new().add_repo("frontend").build();
    let mut manifest = ws.load_manifest();
    manifest.settings.target = Some("dev".to_string());

    repo_ahead_of(&ws, "frontend", "dev", "feat/thing");
    point_repo_at_mock(&mut manifest, "frontend", &server);

    mock_branch_exists(&server, "owner", "repo", "dev").await;
    mock_create_pr_validation_error(&server).await;

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

    // Control: the command must actually have ATTEMPTED the creation. Without
    // this, a command that skipped the repo entirely -- never reaching the
    // failure path at all -- would satisfy the assertion below for the wrong
    // reason, and the test would be pinning a no-op.
    let requests = server.received_requests().await.unwrap();
    let posts = requests
        .iter()
        .filter(|r| r.method == Method::POST && r.url.path().ends_with("/pulls"))
        .count();
    assert!(
        posts >= 1,
        "control: the command must attempt the PR before it can report a failure; saw {posts} POSTs"
    );

    assert!(
        result.is_err(),
        "a run that printed 'Failed to create 1 PR(s)' returned Ok -- any caller \
         gating on the exit status reads the command's own reported failure as success"
    );
}

/// THE DISCRIMINATING CONTROL. A run where every PR is created must still
/// return Ok. Without this case, "return Err whenever anything was attempted"
/// and "return Err only when something failed" are indistinguishable, and the
/// witness above would be satisfied by a command that always fails.
#[tokio::test]
async fn a_run_with_no_failures_still_exits_zero() {
    let (server, _adapter) = setup_github_mock().await;

    let ws = WorkspaceBuilder::new().add_repo("frontend").build();
    let mut manifest = ws.load_manifest();
    manifest.settings.target = Some("dev".to_string());

    repo_ahead_of(&ws, "frontend", "dev", "feat/thing");
    point_repo_at_mock(&mut manifest, "frontend", &server);

    mock_branch_exists(&server, "owner", "repo", "dev").await;
    mock_create_pr(&server, 11, "https://github.com/owner/repo/pull/11").await;

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

    let requests = server.received_requests().await.unwrap();
    let posts = requests
        .iter()
        .filter(|r| r.method == Method::POST && r.url.path().ends_with("/pulls"))
        .count();
    assert_eq!(posts, 1, "control: exactly one PR should have been created");

    assert!(
        result.is_ok(),
        "a run in which every PR was created must not report failure: {result:?}"
    );
}

/// `--json` keeps exit 0 and carries the failure in the body.
///
/// Not an exception carved out for convenience -- it is this repo's shipped
/// convention, and it is shipped rather than merely planned: `gr verify --json`
/// returns Ok before its own `exit(1)` (verify.rs:99), and docs/PLAN-verify.md
/// gives the reason. A caller who asked for JSON is parsing the body by
/// construction, and a non-zero exit makes a `set -e` script die before it can
/// read the answer it asked for.
///
/// Without this case, the fix above would silently change the exit status of
/// every scripted `--json` caller, which is the sort of thing that gets found
/// in someone else's CI rather than here.
#[tokio::test]
async fn json_mode_reports_the_failure_in_the_body_and_still_exits_zero() {
    let (server, _adapter) = setup_github_mock().await;

    let ws = WorkspaceBuilder::new().add_repo("frontend").build();
    let mut manifest = ws.load_manifest();
    manifest.settings.target = Some("dev".to_string());

    repo_ahead_of(&ws, "frontend", "dev", "feat/thing");
    point_repo_at_mock(&mut manifest, "frontend", &server);

    mock_branch_exists(&server, "owner", "repo", "dev").await;
    mock_create_pr_validation_error(&server).await;

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
        true, // json
    )
    .await;

    // Control: the same inputs in human mode DO error. Without this the test
    // would pass equally well against a build where nothing ever errors, which
    // is the state this whole PR exists to leave behind.
    let requests = server.received_requests().await.unwrap();
    let posts = requests
        .iter()
        .filter(|r| r.method == Method::POST && r.url.path().ends_with("/pulls"))
        .count();
    assert!(posts >= 1, "control: the creation must have been attempted");

    assert!(
        result.is_ok(),
        "--json must keep exit 0 and carry pass/fail in the body: {result:?}"
    );
}
