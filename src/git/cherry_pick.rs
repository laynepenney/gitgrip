//! Git cherry-pick operations

use crate::git::GitError;
use crate::util::log_cmd;
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
    let mut cmd = Command::new("git");
    cmd.args(["cat-file", "-t", "--", commit_sha])
        .current_dir(repo_path);
    log_cmd(&cmd);
    cmd.output()
        .map(|o| o.status.success() && String::from_utf8_lossy(&o.stdout).trim() == "commit")
        .unwrap_or(false)
}

/// Cherry-pick a commit in a repository
pub fn cherry_pick(repo_path: &Path, commit_sha: &str) -> CherryPickResult {
    if !commit_exists(repo_path, commit_sha) {
        return CherryPickResult::CommitNotFound;
    }

    let mut cmd = Command::new("git");
    cmd.args(["cherry-pick", "--", commit_sha])
        .current_dir(repo_path);
    log_cmd(&cmd);
    let output = match cmd.output() {
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
    let mut cmd = Command::new("git");
    cmd.args(["cherry-pick", "--abort"]).current_dir(repo_path);
    log_cmd(&cmd);
    let output = cmd
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
    let mut cmd = Command::new("git");
    cmd.args(["cherry-pick", "--continue"])
        .current_dir(repo_path);
    log_cmd(&cmd);
    let output = cmd
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

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;
    use std::process::Command as StdCommand;
    use tempfile::TempDir;

    fn git(dir: &Path, args: &[&str]) {
        let output = StdCommand::new("git")
            .current_dir(dir)
            .args(args)
            .output()
            .unwrap_or_else(|e| panic!("failed to run git {:?}: {}", args, e));
        assert!(
            output.status.success(),
            "git {:?} failed: {}",
            args,
            String::from_utf8_lossy(&output.stderr)
        );
    }

    fn setup_repo_with_commit() -> TempDir {
        let temp = TempDir::new().unwrap();
        let dir = temp.path();
        git(dir, &["init", "-b", "main"]);
        git(dir, &["config", "user.email", "test@example.com"]);
        git(dir, &["config", "user.name", "Test User"]);
        fs::write(dir.join("file.txt"), "initial").unwrap();
        git(dir, &["add", "file.txt"]);
        git(dir, &["commit", "-m", "initial commit"]);
        temp
    }

    fn get_head_sha(dir: &Path) -> String {
        let output = StdCommand::new("git")
            .current_dir(dir)
            .args(["rev-parse", "HEAD"])
            .output()
            .unwrap();
        String::from_utf8_lossy(&output.stdout).trim().to_string()
    }

    #[test]
    fn test_commit_exists_true() {
        let temp = setup_repo_with_commit();
        let sha = get_head_sha(temp.path());
        assert!(commit_exists(temp.path(), &sha));
    }

    #[test]
    fn test_commit_exists_false() {
        let temp = setup_repo_with_commit();
        assert!(!commit_exists(
            temp.path(),
            "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef"
        ));
    }

    #[test]
    fn test_cherry_pick_applied() {
        let temp = setup_repo_with_commit();
        let dir = temp.path();

        // Create a second commit on a side branch
        git(dir, &["checkout", "-b", "side"]);
        fs::write(dir.join("side.txt"), "side content").unwrap();
        git(dir, &["add", "side.txt"]);
        git(dir, &["commit", "-m", "side commit"]);
        let side_sha = get_head_sha(dir);

        // Switch back to main and cherry-pick
        git(dir, &["checkout", "main"]);
        let result = cherry_pick(dir, &side_sha);
        assert!(matches!(result, CherryPickResult::Applied));
        assert!(dir.join("side.txt").exists());
    }

    #[test]
    fn test_cherry_pick_commit_not_found() {
        let temp = setup_repo_with_commit();
        let result = cherry_pick(temp.path(), "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef");
        assert!(matches!(result, CherryPickResult::CommitNotFound));
    }

    #[test]
    fn test_cherry_pick_in_progress_false() {
        let temp = setup_repo_with_commit();
        assert!(!cherry_pick_in_progress(temp.path()));
    }

    #[test]
    fn test_cherry_pick_abort_no_cherry_pick() {
        let temp = setup_repo_with_commit();
        // Aborting when no cherry-pick is in progress should error
        let result = cherry_pick_abort(temp.path());
        assert!(result.is_err());
    }
}
