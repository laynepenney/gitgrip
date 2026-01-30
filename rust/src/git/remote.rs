//! Git remote operations

use git2::Repository;
use std::process::Command;

use super::cache::invalidate_status_cache;
use super::{get_current_branch, GitError};

/// Get the URL of a remote
pub fn get_remote_url(repo: &Repository, remote: &str) -> Result<Option<String>, GitError> {
    let repo_path = repo.path().parent().unwrap_or(repo.path());

    let output = Command::new("git")
        .args(["remote", "get-url", remote])
        .current_dir(repo_path)
        .output()
        .map_err(|e| GitError::OperationFailed(e.to_string()))?;

    if output.status.success() {
        let url = String::from_utf8_lossy(&output.stdout).trim().to_string();
        Ok(Some(url))
    } else {
        Ok(None)
    }
}

/// Set the URL of a remote (creates if it doesn't exist)
pub fn set_remote_url(repo: &Repository, remote: &str, url: &str) -> Result<(), GitError> {
    let repo_path = repo.path().parent().unwrap_or(repo.path());

    if get_remote_url(repo, remote)?.is_none() {
        Command::new("git")
            .args(["remote", "add", remote, url])
            .current_dir(repo_path)
            .output()
            .map_err(|e| GitError::OperationFailed(e.to_string()))?;
    } else {
        Command::new("git")
            .args(["remote", "set-url", remote, url])
            .current_dir(repo_path)
            .output()
            .map_err(|e| GitError::OperationFailed(e.to_string()))?;
    }
    Ok(())
}

/// Fetch from remote
pub fn fetch_remote(repo: &Repository, remote: &str) -> Result<(), GitError> {
    let repo_path = repo.path().parent().unwrap_or(repo.path());

    let output = Command::new("git")
        .args(["fetch", remote])
        .current_dir(repo_path)
        .output()
        .map_err(|e| GitError::OperationFailed(e.to_string()))?;

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        return Err(GitError::OperationFailed(stderr.to_string()));
    }

    Ok(())
}

/// Pull latest changes (fetch + merge)
pub fn pull_latest(repo: &Repository, remote: &str) -> Result<(), GitError> {
    let repo_path = repo.path().parent().unwrap_or(repo.path());

    let output = Command::new("git")
        .args(["pull", remote])
        .current_dir(repo_path)
        .output()
        .map_err(|e| GitError::OperationFailed(e.to_string()))?;

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        if stderr.contains("CONFLICT") {
            return Err(GitError::OperationFailed(
                "Merge conflict occurred. Resolve conflicts manually.".to_string(),
            ));
        }
        if stderr.contains("non-fast-forward") {
            return Err(GitError::OperationFailed(
                "Non-fast-forward merge required. Please merge manually.".to_string(),
            ));
        }
        return Err(GitError::OperationFailed(stderr.to_string()));
    }

    // Invalidate cache
    invalidate_status_cache(&repo_path.to_path_buf());

    Ok(())
}

/// Push branch to remote
pub fn push_branch(
    repo: &Repository,
    branch_name: &str,
    remote: &str,
    set_upstream: bool,
) -> Result<(), GitError> {
    let repo_path = repo.path().parent().unwrap_or(repo.path());

    let mut args = vec!["push", remote, branch_name];
    if set_upstream {
        args.insert(1, "-u");
    }

    let output = Command::new("git")
        .args(&args)
        .current_dir(repo_path)
        .output()
        .map_err(|e| GitError::OperationFailed(e.to_string()))?;

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        return Err(GitError::OperationFailed(stderr.to_string()));
    }

    Ok(())
}

/// Force push branch to remote
pub fn force_push_branch(repo: &Repository, branch_name: &str, remote: &str) -> Result<(), GitError> {
    let repo_path = repo.path().parent().unwrap_or(repo.path());

    let output = Command::new("git")
        .args(["push", "--force", remote, branch_name])
        .current_dir(repo_path)
        .output()
        .map_err(|e| GitError::OperationFailed(e.to_string()))?;

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        return Err(GitError::OperationFailed(stderr.to_string()));
    }

    Ok(())
}

/// Delete a remote branch
pub fn delete_remote_branch(repo: &Repository, branch_name: &str, remote: &str) -> Result<(), GitError> {
    let repo_path = repo.path().parent().unwrap_or(repo.path());

    let output = Command::new("git")
        .args(["push", remote, "--delete", branch_name])
        .current_dir(repo_path)
        .output()
        .map_err(|e| GitError::OperationFailed(e.to_string()))?;

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        return Err(GitError::OperationFailed(stderr.to_string()));
    }

    Ok(())
}

/// Get upstream tracking branch name
pub fn get_upstream_branch(repo: &Repository, branch_name: Option<&str>) -> Result<Option<String>, GitError> {
    let repo_path = repo.path().parent().unwrap_or(repo.path());

    let branch = match branch_name {
        Some(name) => name.to_string(),
        None => get_current_branch(repo)?,
    };

    let output = Command::new("git")
        .args(["rev-parse", "--abbrev-ref", &format!("{}@{{upstream}}", branch)])
        .current_dir(repo_path)
        .output()
        .map_err(|e| GitError::OperationFailed(e.to_string()))?;

    if output.status.success() {
        let upstream = String::from_utf8_lossy(&output.stdout).trim().to_string();
        Ok(Some(upstream))
    } else {
        Ok(None)
    }
}

/// Check if upstream branch exists on remote
pub fn upstream_branch_exists(repo: &Repository, remote: &str) -> Result<bool, GitError> {
    let upstream = get_upstream_branch(repo, None)?;
    match upstream {
        Some(name) => {
            let branch_name = name.split('/').last().unwrap_or(&name);
            Ok(super::branch::remote_branch_exists(repo, branch_name, remote))
        }
        None => Ok(false),
    }
}

/// Set upstream tracking for the current branch
pub fn set_upstream_branch(repo: &Repository, remote: &str) -> Result<(), GitError> {
    let repo_path = repo.path().parent().unwrap_or(repo.path());
    let branch_name = get_current_branch(repo)?;

    let output = Command::new("git")
        .args(["branch", "--set-upstream-to", &format!("{}/{}", remote, branch_name)])
        .current_dir(repo_path)
        .output()
        .map_err(|e| GitError::OperationFailed(e.to_string()))?;

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        return Err(GitError::OperationFailed(stderr.to_string()));
    }

    Ok(())
}

/// Hard reset to a target
pub fn reset_hard(repo: &Repository, target: &str) -> Result<(), GitError> {
    let repo_path = repo.path().parent().unwrap_or(repo.path());

    let output = Command::new("git")
        .args(["reset", "--hard", target])
        .current_dir(repo_path)
        .output()
        .map_err(|e| GitError::OperationFailed(e.to_string()))?;

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        return Err(GitError::OperationFailed(stderr.to_string()));
    }

    // Invalidate cache
    invalidate_status_cache(&repo_path.to_path_buf());

    Ok(())
}

/// Safe pull that handles deleted upstream branches
pub fn safe_pull_latest(
    repo: &Repository,
    default_branch: &str,
    remote: &str,
) -> Result<SafePullResult, GitError> {
    let current_branch = get_current_branch(repo)?;

    // If on default branch, just pull
    if current_branch == default_branch {
        return match pull_latest(repo, remote) {
            Ok(()) => Ok(SafePullResult {
                pulled: true,
                recovered: false,
                message: None,
            }),
            Err(e) => Ok(SafePullResult {
                pulled: false,
                recovered: false,
                message: Some(e.to_string()),
            }),
        };
    }

    // Check if upstream exists
    let has_upstream = get_upstream_branch(repo, None)?.is_some();
    let upstream_exists = upstream_branch_exists(repo, remote)?;

    if !upstream_exists {
        if !has_upstream {
            return Ok(SafePullResult {
                pulled: false,
                recovered: false,
                message: Some(format!(
                    "Branch '{}' has no upstream configured. Push with 'gr push -u' first, or checkout '{}' manually.",
                    current_branch, default_branch
                )),
            });
        }

        // Check for local-only commits
        let has_local_commits = super::branch::has_commits_ahead(repo, default_branch)?;
        if has_local_commits {
            return Ok(SafePullResult {
                pulled: false,
                recovered: false,
                message: Some(format!(
                    "Branch '{}' has local commits not in '{}'. Push your changes or merge manually.",
                    current_branch, default_branch
                )),
            });
        }

        // Safe to switch - upstream was deleted and no local work would be lost
        super::branch::checkout_branch(repo, default_branch)?;
        pull_latest(repo, remote)?;

        return Ok(SafePullResult {
            pulled: true,
            recovered: true,
            message: Some(format!(
                "Switched from '{}' to '{}' (upstream branch was deleted)",
                current_branch, default_branch
            )),
        });
    }

    // Normal pull
    match pull_latest(repo, remote) {
        Ok(()) => Ok(SafePullResult {
            pulled: true,
            recovered: false,
            message: None,
        }),
        Err(e) => Ok(SafePullResult {
            pulled: false,
            recovered: false,
            message: Some(e.to_string()),
        }),
    }
}

/// Result of safe_pull_latest
#[derive(Debug, Clone)]
pub struct SafePullResult {
    /// Whether pull succeeded
    pub pulled: bool,
    /// Whether recovery was needed (switched to default branch)
    pub recovered: bool,
    /// Optional message
    pub message: Option<String>,
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::git::open_repo;
    use std::fs;
    use std::process::Command;
    use tempfile::TempDir;

    fn setup_test_repo() -> (TempDir, Repository) {
        let temp = TempDir::new().unwrap();

        Command::new("git")
            .args(["init"])
            .current_dir(temp.path())
            .output()
            .unwrap();

        Command::new("git")
            .args(["config", "user.name", "Test User"])
            .current_dir(temp.path())
            .output()
            .unwrap();

        Command::new("git")
            .args(["config", "user.email", "test@example.com"])
            .current_dir(temp.path())
            .output()
            .unwrap();

        // Create initial commit
        fs::write(temp.path().join("README.md"), "# Test").unwrap();
        Command::new("git")
            .args(["add", "README.md"])
            .current_dir(temp.path())
            .output()
            .unwrap();
        Command::new("git")
            .args(["commit", "-m", "Initial commit"])
            .current_dir(temp.path())
            .output()
            .unwrap();

        let repo = open_repo(temp.path()).unwrap();
        (temp, repo)
    }

    #[test]
    fn test_get_remote_url() {
        let (temp, repo) = setup_test_repo();

        // No remote yet
        assert!(get_remote_url(&repo, "origin").unwrap().is_none());

        // Add remote
        Command::new("git")
            .args(["remote", "add", "origin", "https://github.com/test/repo.git"])
            .current_dir(temp.path())
            .output()
            .unwrap();

        let url = get_remote_url(&repo, "origin").unwrap();
        assert_eq!(url, Some("https://github.com/test/repo.git".to_string()));
    }

    #[test]
    fn test_set_remote_url() {
        let (temp, repo) = setup_test_repo();

        // Create new remote
        set_remote_url(&repo, "origin", "https://github.com/test/repo1.git").unwrap();
        assert_eq!(
            get_remote_url(&repo, "origin").unwrap(),
            Some("https://github.com/test/repo1.git".to_string())
        );

        // Update remote
        set_remote_url(&repo, "origin", "https://github.com/test/repo2.git").unwrap();
        assert_eq!(
            get_remote_url(&repo, "origin").unwrap(),
            Some("https://github.com/test/repo2.git".to_string())
        );
    }
}
