//! Wiring contracts for the release gate.
//!
//! A green CI workflow protects a release only when the tag workflow invokes
//! it and every artifact-producing or publishing path depends on that result.

const CI_WORKFLOW: &str = include_str!("../.github/workflows/ci.yml");
const RELEASE_WORKFLOW: &str = include_str!("../.github/workflows/release.yml");

#[test]
fn ci_is_callable_at_the_tagged_commit() {
    assert!(
        CI_WORKFLOW.contains("on:\n  workflow_call:\n"),
        "release.yml can gate on CI only if ci.yml is a reusable workflow"
    );
    assert!(
        RELEASE_WORKFLOW.contains("  ci:\n    name: CI\n    uses: ./.github/workflows/ci.yml\n"),
        "the release workflow must invoke ci.yml at the tagged commit"
    );
}

#[test]
fn every_release_path_depends_on_ci() {
    assert!(RELEASE_WORKFLOW
        .contains("  build:\n    name: Build (${{ matrix.target }})\n    needs: ci\n"));
    assert!(
        RELEASE_WORKFLOW.contains("  release:\n    name: Create Release\n    needs: [ci, build]\n")
    );
    assert!(RELEASE_WORKFLOW
        .contains("  publish-crates:\n    name: Publish to crates.io\n    needs: [ci, build]\n"));
}

#[test]
fn crates_publish_runs_package_verification() {
    assert!(
        RELEASE_WORKFLOW.contains("run: cargo publish --locked"),
        "cargo publish must run with --locked so a Cargo.lock drift fails the \
         publish loudly instead of silently regenerating the lock (changed from \
         --allow-dirty in 8ca60c2; publish-crates is a fresh checkout with no \
         build step, so the tree is clean at publish time)"
    );
    assert!(
        !RELEASE_WORKFLOW.contains("cargo publish --no-verify"),
        "release publication must never bypass package verification"
    );
}
