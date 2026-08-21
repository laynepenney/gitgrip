//! Repo iteration helpers
//!
//! Provides common patterns for iterating over repos with consistent
//! error handling, skip logic, and result collection.

use crate::cli::output::Output;
use crate::core::repo::RepoInfo;
use crate::git::open_repo;
use git2::Repository;

/// Result of visiting a single repo
pub enum RepoVisitResult {
    /// Operation succeeded with a message
    Success(String),
    /// Repo was skipped (not cloned, no changes, etc.)
    Skipped(String),
    /// Operation produced an error but iteration should continue
    Error(String),
}

/// Summary of a batch repo operation
pub struct RepoOpSummary {
    pub success_count: usize,
    pub skip_count: usize,
    pub error_count: usize,
}

/// Iterate over repos, opening each as a git repository.
///
/// For each repo that exists and can be opened, calls `op` with the
/// repo info and opened `git2::Repository`. Handles:
/// - Skipping repos that aren't cloned
/// - Opening git repos with error reporting
/// - Collecting results
///
/// Returns a summary of successes, skips, and errors.
pub fn for_each_repo<F>(repos: &[RepoInfo], quiet: bool, mut op: F) -> RepoOpSummary
where
    F: FnMut(&RepoInfo, &Repository) -> RepoVisitResult,
{
    let mut summary = RepoOpSummary {
        success_count: 0,
        skip_count: 0,
        error_count: 0,
    };

    for repo in repos {
        // `RepoInfo::exists` tests for `.git`, which is what "cloned" means.
        // A bare `path_exists` on the directory answers a different question:
        // a checkout whose `.git` is gone still has its files, so it would
        // pass that check and then fail to open, turning a not-cloned skip
        // into an error. This is what the docstring above has always claimed.
        if !repo.exists() {
            if !quiet {
                Output::warning(&format!("{}: not cloned", repo.name));
            }
            summary.skip_count += 1;
            continue;
        }

        match open_repo(&repo.absolute_path) {
            Ok(git_repo) => match op(repo, &git_repo) {
                RepoVisitResult::Success(msg) => {
                    if !quiet {
                        Output::success(&msg);
                    }
                    summary.success_count += 1;
                }
                RepoVisitResult::Skipped(msg) => {
                    if !quiet {
                        Output::info(&msg);
                    }
                    summary.skip_count += 1;
                }
                RepoVisitResult::Error(msg) => {
                    Output::error(&msg);
                    summary.error_count += 1;
                }
            },
            Err(e) => {
                Output::error(&format!("{}: {}", repo.name, e));
                summary.error_count += 1;
            }
        }
    }

    summary
}
