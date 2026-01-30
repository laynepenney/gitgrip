//! Commit command implementation

use crate::cli::output::Output;
use crate::core::manifest::Manifest;
use crate::core::repo::RepoInfo;
use crate::git::{open_repo, path_exists};
use crate::git::cache::invalidate_status_cache;
use git2::Repository;
use std::path::PathBuf;
use std::process::Command;

/// Run the commit command
pub fn run_commit(
    workspace_root: &PathBuf,
    manifest: &Manifest,
    message: &str,
    amend: bool,
) -> anyhow::Result<()> {
    Output::header("Committing changes...");
    println!();

    let repos: Vec<RepoInfo> = manifest
        .repos
        .iter()
        .filter_map(|(name, config)| RepoInfo::from_config(name, config, workspace_root))
        .collect();

    let mut success_count = 0;
    let mut skip_count = 0;

    for repo in &repos {
        if !path_exists(&repo.absolute_path) {
            continue;
        }

        match open_repo(&repo.absolute_path) {
            Ok(git_repo) => {
                // Check if there are staged changes
                if !has_staged_changes(&git_repo)? {
                    skip_count += 1;
                    continue;
                }

                match create_commit(&git_repo, message, amend) {
                    Ok(commit_id) => {
                        let short_id = &commit_id[..7.min(commit_id.len())];
                        if amend {
                            Output::success(&format!("{}: amended ({})", repo.name, short_id));
                        } else {
                            Output::success(&format!("{}: committed ({})", repo.name, short_id));
                        }
                        success_count += 1;
                        invalidate_status_cache(&repo.absolute_path);
                    }
                    Err(e) => Output::error(&format!("{}: {}", repo.name, e)),
                }
            }
            Err(e) => Output::error(&format!("{}: {}", repo.name, e)),
        }
    }

    println!();
    if success_count > 0 {
        println!(
            "Created {} commit(s){}.",
            success_count,
            if skip_count > 0 {
                format!(", {} repo(s) had no staged changes", skip_count)
            } else {
                String::new()
            }
        );
    } else {
        println!("No changes to commit.");
    }

    Ok(())
}

/// Check if a repository has staged changes using git CLI
fn has_staged_changes(repo: &Repository) -> anyhow::Result<bool> {
    let repo_path = repo.path().parent().unwrap_or(repo.path());

    let output = Command::new("git")
        .args(["diff", "--cached", "--quiet"])
        .current_dir(repo_path)
        .output()?;

    // Exit code 0 means no diff (no staged changes)
    // Exit code 1 means there are changes
    Ok(!output.status.success())
}

/// Create a commit in the repository using git CLI
fn create_commit(repo: &Repository, message: &str, amend: bool) -> anyhow::Result<String> {
    let repo_path = repo.path().parent().unwrap_or(repo.path());

    let mut args = vec!["commit", "-m", message];
    if amend {
        args.push("--amend");
    }

    let output = Command::new("git")
        .args(&args)
        .current_dir(repo_path)
        .output()?;

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        anyhow::bail!("git commit failed: {}", stderr);
    }

    // Get the commit hash
    let hash_output = Command::new("git")
        .args(["rev-parse", "HEAD"])
        .current_dir(repo_path)
        .output()?;

    let commit_id = String::from_utf8_lossy(&hash_output.stdout).trim().to_string();
    Ok(commit_id)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::git::open_repo;
    use tempfile::TempDir;
    use std::fs;
    use std::process::Command as StdCommand;

    fn setup_test_repo() -> (TempDir, Repository) {
        let temp_dir = TempDir::new().unwrap();

        StdCommand::new("git")
            .args(["init"])
            .current_dir(temp_dir.path())
            .output()
            .unwrap();

        StdCommand::new("git")
            .args(["config", "user.name", "Test User"])
            .current_dir(temp_dir.path())
            .output()
            .unwrap();

        StdCommand::new("git")
            .args(["config", "user.email", "test@example.com"])
            .current_dir(temp_dir.path())
            .output()
            .unwrap();

        let repo = open_repo(temp_dir.path()).unwrap();
        (temp_dir, repo)
    }

    #[test]
    fn test_has_staged_changes_empty() {
        let (_temp_dir, repo) = setup_test_repo();
        assert!(!has_staged_changes(&repo).unwrap());
    }

    #[test]
    fn test_has_staged_changes_with_staged() {
        let (temp_dir, repo) = setup_test_repo();

        // Create and stage a file
        let file_path = temp_dir.path().join("test.txt");
        fs::write(&file_path, "content").unwrap();

        StdCommand::new("git")
            .args(["add", "test.txt"])
            .current_dir(temp_dir.path())
            .output()
            .unwrap();

        assert!(has_staged_changes(&repo).unwrap());
    }

    #[test]
    fn test_create_commit() {
        let (temp_dir, repo) = setup_test_repo();

        // Create and stage a file
        let file_path = temp_dir.path().join("test.txt");
        fs::write(&file_path, "content").unwrap();

        StdCommand::new("git")
            .args(["add", "test.txt"])
            .current_dir(temp_dir.path())
            .output()
            .unwrap();

        let commit_id = create_commit(&repo, "Test commit", false).unwrap();
        assert!(!commit_id.is_empty());

        // Verify commit was created
        let output = StdCommand::new("git")
            .args(["log", "-1", "--format=%s"])
            .current_dir(temp_dir.path())
            .output()
            .unwrap();
        let message = String::from_utf8_lossy(&output.stdout).trim().to_string();
        assert_eq!(message, "Test commit");
    }

    #[test]
    fn test_amend_commit() {
        let (temp_dir, repo) = setup_test_repo();

        // Create initial commit
        let file_path = temp_dir.path().join("test.txt");
        fs::write(&file_path, "initial").unwrap();

        StdCommand::new("git")
            .args(["add", "test.txt"])
            .current_dir(temp_dir.path())
            .output()
            .unwrap();

        create_commit(&repo, "Initial commit", false).unwrap();

        // Modify and stage
        fs::write(&file_path, "amended").unwrap();

        StdCommand::new("git")
            .args(["add", "test.txt"])
            .current_dir(temp_dir.path())
            .output()
            .unwrap();

        // Amend
        create_commit(&repo, "Amended commit", true).unwrap();

        // Verify only one commit exists
        let output = StdCommand::new("git")
            .args(["rev-list", "--count", "HEAD"])
            .current_dir(temp_dir.path())
            .output()
            .unwrap();
        let count: usize = String::from_utf8_lossy(&output.stdout).trim().parse().unwrap();
        assert_eq!(count, 1);

        // Verify message was updated
        let output = StdCommand::new("git")
            .args(["log", "-1", "--format=%s"])
            .current_dir(temp_dir.path())
            .output()
            .unwrap();
        let message = String::from_utf8_lossy(&output.stdout).trim().to_string();
        assert_eq!(message, "Amended commit");
    }
}
