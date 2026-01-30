//! Add command implementation

use crate::cli::output::Output;
use crate::core::manifest::Manifest;
use crate::core::repo::RepoInfo;
use crate::git::{open_repo, path_exists};
use crate::git::cache::invalidate_status_cache;
use git2::Repository;
use std::path::PathBuf;

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

/// Stage files in a repository
fn stage_files(repo: &Repository, repo_path: &PathBuf, files: &[String]) -> anyhow::Result<usize> {
    let mut index = repo.index()?;
    let mut staged_count = 0;

    // If files is ["."], add all changes
    if files.len() == 1 && files[0] == "." {
        // Get all modified/untracked files
        let statuses = repo.statuses(None)?;

        for entry in statuses.iter() {
            let status = entry.status();
            if let Some(path) = entry.path() {
                // Stage modified, new, and deleted files
                if status.is_wt_modified()
                    || status.is_wt_new()
                    || status.is_wt_deleted()
                    || status.is_wt_renamed()
                    || status.is_wt_typechange()
                {
                    let file_path = repo_path.join(path);
                    if file_path.exists() {
                        index.add_path(std::path::Path::new(path))?;
                    } else {
                        // File was deleted
                        index.remove_path(std::path::Path::new(path))?;
                    }
                    staged_count += 1;
                }
            }
        }
    } else {
        // Add specific files
        for file in files {
            let path = std::path::Path::new(file);
            if repo_path.join(path).exists() {
                index.add_path(path)?;
                staged_count += 1;
            } else {
                // Try to remove (file might be deleted)
                let _ = index.remove_path(path);
                staged_count += 1;
            }
        }
    }

    index.write()?;
    Ok(staged_count)
}
