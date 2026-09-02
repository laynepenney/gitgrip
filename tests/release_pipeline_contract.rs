//! Wiring contracts for the release gate.
//!
//! A green CI workflow protects a release only when the tag workflow invokes
//! it and every artifact-producing or publishing path depends on that result.

const CI_WORKFLOW: &str = include_str!("../.github/workflows/ci.yml");
const RELEASE_WORKFLOW: &str = include_str!("../.github/workflows/release.yml");

/// Normalize CRLF -> LF. `include_str!` embeds the working-tree bytes at compile
/// time, and the GitHub Windows runner checks the repo out with autocrlf=true,
/// so ci.yml/release.yml arrive with `\r\n`. These contracts assert on the
/// wiring (embedded `\n` substrings), not on line-ending style, so normalize
/// first. The `had_crlf` witnesses below make a CRLF cause visible rather than
/// inferred if an assertion ever fails.
fn lf(s: &str) -> String {
    s.replace("\r\n", "\n")
}

#[test]
fn ci_is_callable_at_the_tagged_commit() {
    let ci = lf(CI_WORKFLOW);
    let release = lf(RELEASE_WORKFLOW);
    assert!(
        ci.contains("on:\n  workflow_call:\n"),
        "release.yml can gate on CI only if ci.yml is a reusable workflow; ci.yml had_crlf={}",
        CI_WORKFLOW.contains("\r\n")
    );
    assert!(
        release.contains("  ci:\n    name: CI\n    uses: ./.github/workflows/ci.yml\n"),
        "the release workflow must invoke ci.yml at the tagged commit; release.yml had_crlf={}",
        RELEASE_WORKFLOW.contains("\r\n")
    );
}

#[test]
fn every_release_path_depends_on_ci() {
    let release = lf(RELEASE_WORKFLOW);
    let had_crlf = RELEASE_WORKFLOW.contains("\r\n");
    assert!(
        release.contains("  build:\n    name: Build (${{ matrix.target }})\n    needs: ci\n"),
        "build must depend on ci; release.yml had_crlf={had_crlf}"
    );
    assert!(
        release.contains("  release:\n    name: Create Release\n    needs: [ci, build]\n"),
        "release must depend on [ci, build]; release.yml had_crlf={had_crlf}"
    );
    assert!(
        release.contains(
            "  publish-crates:\n    name: Publish to crates.io\n    needs: [ci, build]\n"
        ),
        "publish-crates must depend on [ci, build]; release.yml had_crlf={had_crlf}"
    );
}

#[test]
fn crates_publish_runs_package_verification() {
    let release = lf(RELEASE_WORKFLOW);
    assert!(
        release.contains("run: cargo publish --locked"),
        "cargo publish must run with --locked so a Cargo.lock drift fails the \
         publish loudly instead of silently regenerating the lock (changed from \
         --allow-dirty in 8ca60c2; publish-crates is a fresh checkout with no \
         build step, so the tree is clean at publish time)"
    );
    assert!(
        !release.contains("cargo publish --no-verify"),
        "release publication must never bypass package verification"
    );
}
