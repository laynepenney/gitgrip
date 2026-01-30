//! Add command implementation

use crate::cli::output::Output;
use crate::core::manifest::Manifest;
use crate::core::repo::RepoInfo;
use crate::git::{open_repo, path_exists};
use crate::git::cache::invalidate_status_cache;
use git2::Repository;
use std::path::PathBuf;
use std::process::Command;

/// Run the add command
pub fn run_add(
    workspace_root: &PathBuf,
    manifest: &Manifest,
    files: &[String],
) -> anyhow::Result<()> {
    Output::header("Checking repositories for changes to stage...");
    println!();

    let repos: Vec<RepoInfo> = manifest
        .repos
        .iter()
        .filter_map(|(name, config)| RepoInfo::from_config(name, config, workspace_root))
        .collect();

    let mut total_staged = 0;
    let mut repos_with_changes = 0;

    for repo in &repos {
        if !path_exists(&repo.absolute_path) {
            continue;
        }

        match open_repo(&repo.absolute_path) {
            Ok(git_repo) => {
                let staged = stage_files(&git_repo, &repo.absolute_path, files)?;
                if staged > 0 {
                    Output::success(&format!("{}: staged {} file(s)", repo.name, staged));
                    total_staged += staged;
                    repos_with_changes += 1;
                    invalidate_status_cache(&repo.absolute_path);
                }
            }
            Err(e) => Output::error(&format!("{}: {}", repo.name, e)),
        }
    }

    println!();
    if total_staged > 0 {
        println!(
            "Staged {} file(s) in {} repository(s).",
            total_staged, repos_with_changes
        );
    } else {
        println!("No changes to stage.");
    }

    Ok(())
}

/// Stage files in a repository using git CLI
fn stage_files(repo: &Repository, _repo_path: &PathBuf, files: &[String]) -> anyhow::Result<usize> {
    let repo_dir = repo.path().parent().unwrap_or(repo.path());

    // Get count of changes before staging
    let before_output = Command::new("git")
        .args(["status", "--porcelain"])
        .current_dir(repo_dir)
        .output()?;
    let before_count = String::from_utf8_lossy(&before_output.stdout)
        .lines()
        .filter(|l| !l.starts_with("??") || files.contains(&".".to_string()))
        .count();

    if before_count == 0 {
        return Ok(0);
    }

    // Build git add command
    let mut args = vec!["add"];

    if files.len() == 1 && files[0] == "." {
        args.push("-A"); // Add all changes including deletions
    } else {
        for file in files {
            args.push(file);
        }
    }

    let output = Command::new("git")
        .args(&args)
        .current_dir(repo_dir)
        .output()?;

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        anyhow::bail!("git add failed: {}", stderr);
    }

    // Count what was actually staged
    let after_output = Command::new("git")
        .args(["diff", "--cached", "--name-only"])
        .current_dir(repo_dir)
        .output()?;

    let staged_count = String::from_utf8_lossy(&after_output.stdout)
        .lines()
        .count();

    Ok(staged_count)
}
