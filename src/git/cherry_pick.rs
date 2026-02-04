//! Git cherry-pick operations

use crate::git::GitError;
use std::path::Path;
use std::process::Command;

/// Result of a cherry-pick operation
pub enum CherryPickResult {
    /// Commit was successfully applied
    Applied,
    /// Commit SHA not found in this repo
    CommitNotFound,
    /// Cherry-pick resulted in a conflict
    Conflict(String),
    /// An error occurred
    Error(String),
}

/// Check if a commit exists in the repository
pub fn commit_exists(repo_path: &Path, commit_sha: &str) -> bool {
    Command::new("git")
        .args(["cat-file", "-t", commit_sha])
        .current_dir(repo_path)
        .output()
        .map(|o| o.status.success())
        .unwrap_or(false)
}

/// Cherry-pick a commit in a repository
pub fn cherry_pick(repo_path: &Path, commit_sha: &str) -> CherryPickResult {
    if !commit_exists(repo_path, commit_sha) {
        return CherryPickResult::CommitNotFound;
    }

    let output = match Command::new("git")
        .args(["cherry-pick", commit_sha])
        .current_dir(repo_path)
        .output()
    {
        Ok(o) => o,
        Err(e) => return CherryPickResult::Error(format!("failed to run git cherry-pick: {}", e)),
    };

    if output.status.success() {
        return CherryPickResult::Applied;
    }

    let stderr = String::from_utf8_lossy(&output.stderr).to_string();
    if stderr.contains("CONFLICT") || stderr.contains("conflict") {
        CherryPickResult::Conflict(stderr)
    } else {
        CherryPickResult::Error(stderr)
    }
}

/// Abort an in-progress cherry-pick
pub fn cherry_pick_abort(repo_path: &Path) -> Result<(), GitError> {
    let output = Command::new("git")
        .args(["cherry-pick", "--abort"])
        .current_dir(repo_path)
        .output()
        .map_err(|e| GitError::OperationFailed(format!("failed to abort cherry-pick: {}", e)))?;

    if output.status.success() {
        Ok(())
    } else {
        let stderr = String::from_utf8_lossy(&output.stderr);
        Err(GitError::OperationFailed(format!(
            "cherry-pick --abort failed: {}",
            stderr.trim()
        )))
    }
}

/// Continue an in-progress cherry-pick
pub fn cherry_pick_continue(repo_path: &Path) -> Result<(), GitError> {
    let output = Command::new("git")
        .args(["cherry-pick", "--continue"])
        .current_dir(repo_path)
        .output()
        .map_err(|e| GitError::OperationFailed(format!("failed to continue cherry-pick: {}", e)))?;

    if output.status.success() {
        Ok(())
    } else {
        let stderr = String::from_utf8_lossy(&output.stderr);
        Err(GitError::OperationFailed(format!(
            "cherry-pick --continue failed: {}",
            stderr.trim()
        )))
    }
}

/// Check if a cherry-pick is in progress
pub fn cherry_pick_in_progress(repo_path: &Path) -> bool {
    repo_path.join(".git").join("CHERRY_PICK_HEAD").exists()
}
