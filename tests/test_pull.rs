//! Integration tests for the pull command.

mod common;

use common::fixtures::WorkspaceBuilder;

#[tokio::test]
async fn test_pull_merge_on_clean_repo() {
    let ws = WorkspaceBuilder::new().add_repo("app").build();
    let manifest = ws.load_manifest();

    let result = gitgrip::cli::commands::pull::run_pull(
        &ws.workspace_root,
        &manifest,
        false,
        None,
        true,
        true,
    )
    .await;

    assert!(
        result.is_ok(),
        "pull should succeed on clean repo: {:?}",
        result.err()
    );
}
