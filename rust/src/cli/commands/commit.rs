//! Commit command implementation

use crate::cli::output::Output;
use crate::core::manifest::Manifest;
use crate::core::repo::RepoInfo;
use crate::git::{open_repo, path_exists};
use crate::git::cache::invalidate_status_cache;
use git2::{Repository, Signature};
use std::path::PathBuf;

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

/// Check if a repository has staged changes
fn has_staged_changes(repo: &Repository) -> anyhow::Result<bool> {
    let head = match repo.head() {
        Ok(head) => Some(head.peel_to_tree()?),
        Err(_) => None, // No HEAD yet (empty repo)
    };

    let diff = repo.diff_tree_to_index(head.as_ref(), None, None)?;
    Ok(diff.deltas().count() > 0)
}

/// Create a commit in the repository
fn create_commit(repo: &Repository, message: &str, amend: bool) -> anyhow::Result<String> {
    let signature = get_signature(repo)?;
    let mut index = repo.index()?;
    let tree_id = index.write_tree()?;
    let tree = repo.find_tree(tree_id)?;

    let commit_id = if amend {
        // Amend the current HEAD commit using the amend method
        let head = repo.head()?;
        let head_commit = head.peel_to_commit()?;

        head_commit.amend(
            Some("HEAD"),
            Some(&signature),
            Some(&signature),
            None, // encoding
            Some(message),
            Some(&tree),
        )?
    } else {
        // Create a new commit
        let parent = match repo.head() {
            Ok(head) => Some(head.peel_to_commit()?),
            Err(_) => None, // Initial commit
        };

        let parents: Vec<&git2::Commit> = parent.iter().collect();

        repo.commit(
            Some("HEAD"),
            &signature,
            &signature,
            message,
            &tree,
            &parents,
        )?
    };

    Ok(commit_id.to_string())
}

/// Get the signature for commits
fn get_signature(repo: &Repository) -> anyhow::Result<Signature<'static>> {
    // Try to get from git config
    match repo.signature() {
        Ok(sig) => Ok(Signature::now(sig.name().unwrap_or("Unknown"), sig.email().unwrap_or("unknown@example.com"))?),
        Err(_) => {
            // Fall back to environment variables
            let name = std::env::var("GIT_AUTHOR_NAME")
                .or_else(|_| std::env::var("USER"))
                .unwrap_or_else(|_| "Unknown".to_string());
            let email = std::env::var("GIT_AUTHOR_EMAIL")
                .unwrap_or_else(|_| "unknown@example.com".to_string());
            Ok(Signature::now(&name, &email)?)
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;
    use std::fs;

    fn setup_test_repo() -> (TempDir, Repository) {
        let temp_dir = TempDir::new().unwrap();
        let repo = Repository::init(temp_dir.path()).unwrap();

        // Configure user for commits
        let mut config = repo.config().unwrap();
        config.set_str("user.name", "Test User").unwrap();
        config.set_str("user.email", "test@example.com").unwrap();

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

        {
            let mut index = repo.index().unwrap();
            index.add_path(std::path::Path::new("test.txt")).unwrap();
            index.write().unwrap();
        }

        assert!(has_staged_changes(&repo).unwrap());
    }

    #[test]
    fn test_create_commit() {
        let (temp_dir, repo) = setup_test_repo();

        // Create and stage a file
        let file_path = temp_dir.path().join("test.txt");
        fs::write(&file_path, "content").unwrap();

        {
            let mut index = repo.index().unwrap();
            index.add_path(std::path::Path::new("test.txt")).unwrap();
            index.write().unwrap();
        }

        let commit_id = create_commit(&repo, "Test commit", false).unwrap();
        assert!(!commit_id.is_empty());

        // Verify commit was created
        let head = repo.head().unwrap();
        let commit = head.peel_to_commit().unwrap();
        assert_eq!(commit.message().unwrap(), "Test commit");
    }

    #[test]
    fn test_amend_commit() {
        let (temp_dir, repo) = setup_test_repo();

        // Create initial commit
        let file_path = temp_dir.path().join("test.txt");
        fs::write(&file_path, "initial").unwrap();

        {
            let mut index = repo.index().unwrap();
            index.add_path(std::path::Path::new("test.txt")).unwrap();
            index.write().unwrap();
        }

        create_commit(&repo, "Initial commit", false).unwrap();

        // Modify and stage
        fs::write(&file_path, "amended").unwrap();

        {
            let mut index = repo.index().unwrap();
            index.add_path(std::path::Path::new("test.txt")).unwrap();
            index.write().unwrap();
        }

        // Amend
        create_commit(&repo, "Amended commit", true).unwrap();

        // Verify only one commit exists
        let mut revwalk = repo.revwalk().unwrap();
        revwalk.push_head().unwrap();
        assert_eq!(revwalk.count(), 1);

        // Verify message was updated
        let head = repo.head().unwrap();
        let commit = head.peel_to_commit().unwrap();
        assert_eq!(commit.message().unwrap(), "Amended commit");
    }
}
