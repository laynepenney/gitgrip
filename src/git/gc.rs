//! Git garbage collection operations

use crate::git::GitError;
use std::path::Path;
use std::process::Command;

/// Result of a gc operation on a single repo
pub struct GcResult {
    /// Size of .git directory before gc (bytes)
    pub size_before: u64,
    /// Size of .git directory after gc (bytes)
    pub size_after: u64,
    /// Whether the gc completed successfully
    pub success: bool,
}

/// Recursively compute the size of a directory in bytes
pub fn dir_size(path: &Path) -> u64 {
    if !path.exists() {
        return 0;
    }

    let mut total = 0u64;
    if let Ok(entries) = std::fs::read_dir(path) {
        for entry in entries.flatten() {
            let meta = match entry.metadata() {
                Ok(m) => m,
                Err(_) => continue,
            };
            if meta.is_dir() {
                total += dir_size(&entry.path());
            } else {
                total += meta.len();
            }
        }
    }
    total
}

/// Get the size of the .git directory for a repo
pub fn git_dir_size(repo_path: &Path) -> u64 {
    dir_size(&repo_path.join(".git"))
}

/// Run `git gc` in a repository
pub fn run_git_gc(repo_path: &Path, aggressive: bool) -> Result<GcResult, GitError> {
    let size_before = git_dir_size(repo_path);

    let mut args = vec!["gc"];
    if aggressive {
        args.push("--aggressive");
    }

    let output = Command::new("git")
        .args(&args)
        .current_dir(repo_path)
        .output()
        .map_err(|e| GitError::OperationFailed(format!("failed to run git gc: {}", e)))?;

    let success = output.status.success();
    let size_after = git_dir_size(repo_path);

    Ok(GcResult {
        size_before,
        size_after,
        success,
    })
}

/// Format bytes into a human-readable string
pub fn format_bytes(bytes: u64) -> String {
    const KB: u64 = 1024;
    const MB: u64 = 1024 * KB;
    const GB: u64 = 1024 * MB;

    if bytes >= GB {
        format!("{:.1} GB", bytes as f64 / GB as f64)
    } else if bytes >= MB {
        format!("{:.1} MB", bytes as f64 / MB as f64)
    } else if bytes >= KB {
        format!("{:.1} KB", bytes as f64 / KB as f64)
    } else {
        format!("{} B", bytes)
    }
}
