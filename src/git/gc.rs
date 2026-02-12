//! Git garbage collection operations

use crate::git::GitError;
use crate::util::log_cmd;
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

    let mut cmd = Command::new("git");
    cmd.args(&args).current_dir(repo_path);
    log_cmd(&cmd);
    let output = cmd
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

    #[test]
    fn test_format_bytes() {
        assert_eq!(format_bytes(0), "0 B");
        assert_eq!(format_bytes(512), "512 B");
        assert_eq!(format_bytes(1024), "1.0 KB");
        assert_eq!(format_bytes(1536), "1.5 KB");
        assert_eq!(format_bytes(1024 * 1024), "1.0 MB");
        assert_eq!(format_bytes(1024 * 1024 * 1024), "1.0 GB");
    }

    #[test]
    fn test_dir_size_empty() {
        let temp = TempDir::new().unwrap();
        assert_eq!(dir_size(temp.path()), 0);
    }

    #[test]
    fn test_dir_size_with_files() {
        let temp = TempDir::new().unwrap();
        fs::write(temp.path().join("a.txt"), "hello").unwrap();
        fs::write(temp.path().join("b.txt"), "world!").unwrap();
        let size = dir_size(temp.path());
        assert_eq!(size, 11); // "hello" (5) + "world!" (6)
    }

    #[test]
    fn test_dir_size_nonexistent() {
        assert_eq!(dir_size(Path::new("/nonexistent/path")), 0);
    }

    #[test]
    fn test_git_dir_size() {
        let temp = TempDir::new().unwrap();
        git(temp.path(), &["init", "-b", "main"]);
        let size = git_dir_size(temp.path());
        assert!(size > 0, "git dir should have nonzero size after init");
    }

    #[test]
    fn test_run_git_gc() {
        let temp = TempDir::new().unwrap();
        let dir = temp.path();
        git(dir, &["init", "-b", "main"]);
        git(dir, &["config", "user.email", "test@example.com"]);
        git(dir, &["config", "user.name", "Test User"]);
        fs::write(dir.join("file.txt"), "content").unwrap();
        git(dir, &["add", "file.txt"]);
        git(dir, &["commit", "-m", "initial"]);

        let result = run_git_gc(dir, false).unwrap();
        assert!(result.success);
        assert!(result.size_before > 0);
    }

    #[test]
    fn test_run_git_gc_not_a_repo() {
        let temp = TempDir::new().unwrap();
        // Running gc on a non-repo directory should still return a result (git gc fails gracefully)
        let result = run_git_gc(temp.path(), false).unwrap();
        assert!(!result.success);
    }
}
