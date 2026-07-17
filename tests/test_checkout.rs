//! Integration tests for the checkout command.

mod common;

use assert_cmd::Command;

use common::assertions::assert_on_branch;
use common::fixtures::WorkspaceBuilder;

#[test]
fn test_checkout_existing_branch() {
    let ws = WorkspaceBuilder::new()
        .add_repo("frontend")
        .add_repo("backend")
        .build();

    let manifest = ws.load_manifest();

    // Create a branch
    gitgrip::cli::commands::branch::run_branch(gitgrip::cli::commands::branch::BranchOptions {
        workspace_root: &ws.workspace_root,
        manifest: &manifest,
        name: Some("feat/checkout-test"),
        delete: false,
        move_commits: false,
        repos_filter: None,
        group_filter: None,
        json: false,
    })
    .unwrap();

    // Go back to main
    gitgrip::cli::commands::checkout::run_checkout(
        &ws.workspace_root,
        &manifest,
        "main",
        false,
        None,
        None,
    )
    .unwrap();
    assert_on_branch(&ws.repo_path("frontend"), "main");
    assert_on_branch(&ws.repo_path("backend"), "main");

    // Checkout the feature branch
    let result = gitgrip::cli::commands::checkout::run_checkout(
        &ws.workspace_root,
        &manifest,
        "feat/checkout-test",
        false,
        None,
        None,
    );
    assert!(
        result.is_ok(),
        "checkout should succeed: {:?}",
        result.err()
    );

    assert_on_branch(&ws.repo_path("frontend"), "feat/checkout-test");
    assert_on_branch(&ws.repo_path("backend"), "feat/checkout-test");
}

#[test]
fn test_checkout_nonexistent_branch() {
    let ws = WorkspaceBuilder::new().add_repo("app").build();

    let manifest = ws.load_manifest();

    // Checkout a branch that doesn't exist -- should succeed (skips repos)
    let result = gitgrip::cli::commands::checkout::run_checkout(
        &ws.workspace_root,
        &manifest,
        "feat/does-not-exist",
        false,
        None,
        None,
    );
    assert!(
        result.is_ok(),
        "checkout of nonexistent branch should not error: {:?}",
        result.err()
    );

    // Should still be on main
    assert_on_branch(&ws.repo_path("app"), "main");
}

#[test]
fn test_checkout_main() {
    let ws = WorkspaceBuilder::new()
        .add_repo("app")
        .add_repo("lib")
        .build();

    let manifest = ws.load_manifest();

    // Create and switch to feature branch
    gitgrip::cli::commands::branch::run_branch(gitgrip::cli::commands::branch::BranchOptions {
        workspace_root: &ws.workspace_root,
        manifest: &manifest,
        name: Some("feat/temp"),
        delete: false,
        move_commits: false,
        repos_filter: None,
        group_filter: None,
        json: false,
    })
    .unwrap();
    assert_on_branch(&ws.repo_path("app"), "feat/temp");

    // Checkout main
    let result = gitgrip::cli::commands::checkout::run_checkout(
        &ws.workspace_root,
        &manifest,
        "main",
        false,
        None,
        None,
    );
    assert!(
        result.is_ok(),
        "checkout main should succeed: {:?}",
        result.err()
    );

    assert_on_branch(&ws.repo_path("app"), "main");
    assert_on_branch(&ws.repo_path("lib"), "main");
}

#[test]
fn test_checkout_create_flag() {
    let ws = WorkspaceBuilder::new()
        .add_repo("frontend")
        .add_repo("backend")
        .build();

    let manifest = ws.load_manifest();

    // Use -b flag to create and checkout in one command
    let result = gitgrip::cli::commands::checkout::run_checkout(
        &ws.workspace_root,
        &manifest,
        "feat/new-feature",
        true, // create = true (-b flag)
        None,
        None,
    );
    assert!(
        result.is_ok(),
        "checkout -b should succeed: {:?}",
        result.err()
    );

    // Both repos should now be on the new branch
    assert_on_branch(&ws.repo_path("frontend"), "feat/new-feature");
    assert_on_branch(&ws.repo_path("backend"), "feat/new-feature");
}
#[test]
fn test_checkout_skips_non_git_repo() {
    let ws = WorkspaceBuilder::new()
        .add_repo("frontend")
        .add_repo("backend")
        .build();

    let manifest = ws.load_manifest();

    // Create branch across repos
    gitgrip::cli::commands::branch::run_branch(gitgrip::cli::commands::branch::BranchOptions {
        workspace_root: &ws.workspace_root,
        manifest: &manifest,
        name: Some("feat/checkout-safe"),
        delete: false,
        move_commits: false,
        repos_filter: None,
        group_filter: None,
        json: false,
    })
    .unwrap();

    // Corrupt backend repo by removing .git
    std::fs::remove_dir_all(ws.repo_path("backend").join(".git")).unwrap();

    let result = gitgrip::cli::commands::checkout::run_checkout(
        &ws.workspace_root,
        &manifest,
        "feat/checkout-safe",
        false,
        None,
        None,
    );
    assert!(
        result.is_ok(),
        "checkout should not crash on non-git repo: {:?}",
        result.err()
    );

    // Healthy repo should switch; corrupted repo remains non-git
    assert_on_branch(&ws.repo_path("frontend"), "feat/checkout-safe");
    assert!(!ws.repo_path("backend").join(".git").exists());
}

// ── grip#774: `gr checkout add` must produce a self-discoverable workspace ──
//
// grip#770/#771/#773 fixed `gr pr edit/review/merge` silently fanning out
// across every repo in the *correctly resolved* workspace. This is the sibling
// bug one layer down: `gr checkout add` materializes a disposable child
// checkout, but (before this fix) wrote no workspace marker inside it, so
// EVERY `gr` command run from inside that checkout -- including `gr pr
// review`/`merge` -- silently resolved the *parent* gripspace instead. A
// reviewer entering the checkout to act on its PR head could unknowingly
// operate on the parent's unrelated active branch. Found live during
// grip#773's own review/merge (grip#774).

#[test]
fn test_checkout_add_makes_the_child_checkout_independently_discoverable() {
    let ws = WorkspaceBuilder::new().add_repo("app").build();
    let manifest = ws.load_manifest();

    gitgrip::cli::commands::checkout::run_checkout_add(
        &ws.workspace_root,
        &manifest,
        "review-copy",
        None,
        None,
    )
    .expect("checkout add should succeed");

    let checkout_repo_dir = ws
        .workspace_root
        .join(".grip")
        .join("checkouts")
        .join("review-copy")
        .join("app");
    assert!(
        checkout_repo_dir.is_dir(),
        "materialized checkout repo dir should exist at {}",
        checkout_repo_dir.display()
    );

    // This is Sentinel's exact grip#774 repro: run `gr env` from inside a
    // repo INSIDE the child checkout and check which workspace it reports.
    let output = Command::cargo_bin("gr")
        .expect("gr binary should build")
        .current_dir(&checkout_repo_dir)
        .arg("env")
        .output()
        .expect("gr env should run");
    assert!(
        output.status.success(),
        "gr env should succeed from inside the checkout: {}",
        String::from_utf8_lossy(&output.stderr)
    );

    let stdout = String::from_utf8_lossy(&output.stdout);
    let workspace_line = stdout
        .lines()
        .find(|line| line.trim_start().starts_with("GITGRIP_WORKSPACE="))
        .expect("gr env should print GITGRIP_WORKSPACE");
    let reported = workspace_line
        .split_once('=')
        .map(|(_, v)| v.trim())
        .unwrap_or("");

    let expected_checkout_root = ws
        .workspace_root
        .join(".grip")
        .join("checkouts")
        .join("review-copy");
    let canonical_checkout_root =
        std::fs::canonicalize(&expected_checkout_root).unwrap_or(expected_checkout_root);
    let canonical_reported =
        std::fs::canonicalize(reported).unwrap_or_else(|_| std::path::PathBuf::from(reported));

    assert_eq!(
        canonical_reported, canonical_checkout_root,
        "gr env from inside the child checkout must resolve GITGRIP_WORKSPACE to the \
         checkout root, not the parent workspace -- that is grip#774's exact failure mode"
    );

    let canonical_parent =
        std::fs::canonicalize(&ws.workspace_root).unwrap_or_else(|_| ws.workspace_root.clone());
    assert_ne!(
        canonical_reported, canonical_parent,
        "gr env must not resolve to the parent workspace root from inside the checkout"
    );
}

// ── grip#775 blocker 1: a farther `.griptree` must not eclipse a nearer
// checkout. Reproduces Sentinel's exact live finding: his real parent
// gripspace carries a `.griptree` pointer, so `load_gripspace()`'s OLD
// two-independent-passes structure (check every ancestor for `.griptree`,
// THEN separately check every ancestor for `.gitgrip`) let that distant
// pointer win over the checkout one level down every time. ─────────────────

#[test]
fn test_checkout_wins_over_a_griptree_pointer_at_an_ancestor() {
    let ws = WorkspaceBuilder::new().add_repo("app").build();
    let manifest = ws.load_manifest();

    // Simulate "this parent gripspace also happens to carry a .griptree
    // pointer" -- e.g. it was itself created as a griptree at some point.
    // The pointer's target doesn't need to resolve to anything real: this
    // test asserts the checkout wins BEFORE that pointer is ever followed.
    let pointer = gitgrip::core::griptree::GriptreePointer {
        main_workspace: "/nonexistent/decoy-main-workspace".to_string(),
        branch: "feat/decoy".to_string(),
        locked: false,
        created_at: None,
        repos: vec![],
        manifest_branch: None,
        manifest_worktree_name: None,
    };
    let pointer_json = serde_json::to_string(&pointer).expect("serialize pointer");
    std::fs::write(ws.workspace_root.join(".griptree"), pointer_json)
        .expect("write .griptree pointer at the parent gripspace root");

    gitgrip::cli::commands::checkout::run_checkout_add(
        &ws.workspace_root,
        &manifest,
        "review-copy",
        None,
        None,
    )
    .expect("checkout add should succeed even with a parent .griptree present");

    let checkout_repo_dir = ws
        .workspace_root
        .join(".grip")
        .join("checkouts")
        .join("review-copy")
        .join("app");

    let output = Command::cargo_bin("gr")
        .expect("gr binary should build")
        .current_dir(&checkout_repo_dir)
        .arg("env")
        .output()
        .expect("gr env should run");
    assert!(
        output.status.success(),
        "gr env should succeed from inside the checkout: {}",
        String::from_utf8_lossy(&output.stderr)
    );

    let stdout = String::from_utf8_lossy(&output.stdout);
    let workspace_line = stdout
        .lines()
        .find(|line| line.trim_start().starts_with("GITGRIP_WORKSPACE="))
        .expect("gr env should print GITGRIP_WORKSPACE");
    let reported = workspace_line
        .split_once('=')
        .map(|(_, v)| v.trim())
        .unwrap_or("");

    let expected_checkout_root = ws
        .workspace_root
        .join(".grip")
        .join("checkouts")
        .join("review-copy");
    let canonical_checkout_root =
        std::fs::canonicalize(&expected_checkout_root).unwrap_or(expected_checkout_root);
    let canonical_reported =
        std::fs::canonicalize(reported).unwrap_or_else(|_| std::path::PathBuf::from(reported));

    assert_eq!(
        canonical_reported, canonical_checkout_root,
        "the nearer checkout must win over the farther .griptree pointer at the parent \
         gripspace root -- grip#775 blocker 1's exact failure mode"
    );
    assert_ne!(
        reported, "/nonexistent/decoy-main-workspace",
        "the griptree pointer must never even be followed when a nearer checkout exists"
    );
}

// ── grip#775 blocker 2: creating a checkout that includes the "manifest"
// pseudo-repo must not corrupt that repo's own materialized clone. ─────────

#[test]
fn test_checkout_including_manifest_repo_leaves_it_clean_end_to_end() {
    let ws = WorkspaceBuilder::new()
        .add_repo("app")
        .with_manifest_repo()
        .build();
    let manifest = ws.load_manifest();

    gitgrip::cli::commands::checkout::run_checkout_add(
        &ws.workspace_root,
        &manifest,
        "with-manifest",
        Some(&["app".to_string(), "manifest".to_string()]),
        None,
    )
    .expect("checkout add including the manifest repo should succeed");

    let checkout_root = ws
        .workspace_root
        .join(".grip")
        .join("checkouts")
        .join("with-manifest");
    let materialized_manifest_dir = checkout_root.join(".gitgrip").join("spaces").join("main");
    assert!(
        materialized_manifest_dir.join(".git").is_dir(),
        "the manifest repo should be materialized at its canonical clone path"
    );

    let status = std::process::Command::new("git")
        .args(["status", "--porcelain"])
        .current_dir(&materialized_manifest_dir)
        .output()
        .expect("git status");
    assert!(
        status.stdout.is_empty(),
        "materialized manifest repo must be born clean, not carry a destructive derived-\
         manifest diff -- grip#775 blocker 2's exact failure mode. git status --porcelain: {}",
        String::from_utf8_lossy(&status.stdout)
    );

    // And discovery still works correctly from inside the OTHER materialized
    // repo in the same checkout -- proving .checkout.json (not anything
    // written into the manifest clone) is what makes this checkout resolvable.
    let output = Command::cargo_bin("gr")
        .expect("gr binary should build")
        .current_dir(checkout_root.join("app"))
        .arg("env")
        .output()
        .expect("gr env should run");
    let stdout = String::from_utf8_lossy(&output.stdout);
    let reported = stdout
        .lines()
        .find(|line| line.trim_start().starts_with("GITGRIP_WORKSPACE="))
        .and_then(|line| line.split_once('='))
        .map(|(_, v)| v.trim())
        .unwrap_or("");
    let canonical_checkout_root = std::fs::canonicalize(&checkout_root).unwrap_or(checkout_root);
    let canonical_reported =
        std::fs::canonicalize(reported).unwrap_or_else(|_| std::path::PathBuf::from(reported));
    assert_eq!(canonical_reported, canonical_checkout_root);
}
