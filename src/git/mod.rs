//! Git operations wrapper
//!
//! Provides a unified interface for git operations.
//! Uses git2 (libgit2 bindings) by default.
//! Can optionally use gitoxide (gix) with the "gitoxide" feature flag.

pub mod branch;
pub mod cache;
pub mod remote;
pub mod status;

pub use branch::*;
pub use cache::{invalidate_status_cache, GitStatusCache, STATUS_CACHE};
pub use remote::*;
pub use status::*;

use git2::Repository;
use std::path::Path;
use std::process::Command;
use thiserror::Error;

/// Errors that can occur during git operations
#[derive(Error, Debug)]
pub enum GitError {
    #[error("Git error: {0}")]
    Git(#[from] git2::Error),

    #[error("Repository not found: {0}")]
    NotFound(String),

    #[error("Not a git repository: {0}")]
    NotARepo(String),

    #[error("Branch not found: {0}")]
    BranchNotFound(String),

    #[error("IO error: {0}")]
    Io(#[from] std::io::Error),

    #[error("Operation failed: {0}")]
    OperationFailed(String),

    #[error("Reference error: {0}")]
    Reference(String),

    #[error("Object error: {0}")]
    Object(String),
}

/// Open a git repository at the given path
pub fn open_repo<P: AsRef<Path>>(path: P) -> Result<Repository, GitError> {
    Repository::open(path.as_ref())
        .map_err(|e| GitError::NotARepo(format!("{}: {}", path.as_ref().display(), e)))
}

/// Check if a path is a git repository
pub fn is_git_repo<P: AsRef<Path>>(path: P) -> bool {
    Repository::open(path.as_ref()).is_ok()
}

/// Check if a path exists
pub fn path_exists<P: AsRef<Path>>(path: P) -> bool {
    path.as_ref().exists()
}

/// Clone a repository
pub fn clone_repo<P: AsRef<Path>>(
    url: &str,
    path: P,
    branch: Option<&str>,
) -> Result<Repository, GitError> {
    let path = path.as_ref();

    let mut args = vec!["clone"];
    if let Some(b) = branch {
        args.push("-b");
        args.push(b);
    }
    args.push(url);
    args.push(path.to_str().unwrap_or("."));

    let output = Command::new("git")
        .args(&args)
        .output()
        .map_err(|e| GitError::OperationFailed(e.to_string()))?;

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        return Err(GitError::OperationFailed(format!(
            "git clone failed: {}",
            stderr
        )));
    }

    open_repo(path)
}

/// Get the current branch name
pub fn get_current_branch(repo: &Repository) -> Result<String, GitError> {
    let head = repo
        .head()
        .map_err(|e| GitError::Reference(e.to_string()))?;

    if head.is_branch() {
        let name = head.shorthand().unwrap_or("HEAD");
        Ok(name.to_string())
    } else {
        // Detached HEAD
        let oid = head
            .target()
            .ok_or_else(|| GitError::Reference("HEAD has no target".to_string()))?;
        Ok(format!("(HEAD detached at {})", &oid.to_string()[..7]))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    #[test]
    fn test_is_git_repo() {
        let temp = TempDir::new().unwrap();
        assert!(!is_git_repo(temp.path()));

        // Initialize a git repo
        Repository::init(temp.path()).unwrap();
        assert!(is_git_repo(temp.path()));
    }

    #[test]
    fn test_path_exists() {
        let temp = TempDir::new().unwrap();
        assert!(path_exists(temp.path()));
        assert!(!path_exists(temp.path().join("nonexistent")));
    }

    #[test]
    fn test_open_repo() {
        let temp = TempDir::new().unwrap();

        // Should fail for non-repo
        assert!(open_repo(temp.path()).is_err());

        // Should succeed after init
        Repository::init(temp.path()).unwrap();
        assert!(open_repo(temp.path()).is_ok());
    }
}
