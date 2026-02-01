//! Repo command implementation
//!
//! Manages repositories in the workspace.

use crate::cli::output::{Output, Table};
use crate::core::manifest::Manifest;
use crate::core::repo::RepoInfo;
use crate::git::path_exists;
use std::path::PathBuf;

/// Run repo list command
pub fn run_repo_list(workspace_root: &PathBuf, manifest: &Manifest) -> anyhow::Result<()> {
    Output::header("Repositories");
    println!();

    let repos: Vec<RepoInfo> = manifest
        .repos
        .iter()
        .filter_map(|(name, config)| RepoInfo::from_config(name, config, workspace_root))
        .collect();

    let mut table = Table::new(vec!["Name", "Path", "Branch", "Status"]);

    for repo in &repos {
        let status = if path_exists(&repo.absolute_path) {
            "cloned"
        } else {
            "not cloned"
        };

        table.add_row(vec![&repo.name, &repo.path, &repo.default_branch, status]);
    }

    table.print();

    println!();
    let cloned = repos
        .iter()
        .filter(|r| path_exists(&r.absolute_path))
        .count();
    println!("{}/{} repositories cloned", cloned, repos.len());

    Ok(())
}

/// Run repo add command
pub fn run_repo_add(
    workspace_root: &PathBuf,
    url: &str,
    path: Option<&str>,
    default_branch: Option<&str>,
) -> anyhow::Result<()> {
    Output::header("Adding repository");
    println!();

    // Parse URL to get repo name
    let repo_name = extract_repo_name(url)
        .ok_or_else(|| anyhow::anyhow!("Could not parse repository name from URL"))?;

    let repo_path = path
        .map(|p| p.to_string())
        .unwrap_or_else(|| repo_name.clone());

    let branch = default_branch.unwrap_or("main").to_string();

    // Load manifest
    let manifest_path = workspace_root.join(".gitgrip/manifests/manifest.yaml");
    let content = std::fs::read_to_string(&manifest_path)?;

    // Simple YAML append (for a proper implementation, use serde_yaml to read/write)
    let new_repo_yaml = format!(
        r#"
  {}:
    url: {}
    path: {}
    default_branch: {}"#,
        repo_name, url, repo_path, branch
    );

    // Check if repos section exists and append
    let updated_content = if content.contains("repos:") {
        // Find where to insert - after repos: and before next top-level key
        let mut lines: Vec<&str> = content.lines().collect();
        let mut after_repos = false;
        let mut insert_index = lines.len();

        for (i, line) in lines.iter().enumerate() {
            if line.starts_with("repos:") {
                after_repos = true;
                continue;
            }

            // If we're after repos: section and hit a new top-level key, insert here
            if after_repos
                && (line == "settings:"
                    || line == "workspace:"
                    || line == "manifest:")
            {
                insert_index = i;
                break;
            }
        }

        lines.insert(insert_index, &new_repo_yaml);
        lines.join("\n")
    } else {
        format!("{}repos:{}", content, new_repo_yaml)
    };

    std::fs::write(&manifest_path, updated_content)?;

    Output::success(&format!("Added repository '{}' to manifest", repo_name));
    println!();
    println!("Run 'gr sync' to clone the repository.");

    Ok(())
}

/// Run repo remove command
pub fn run_repo_remove(
    workspace_root: &PathBuf,
    name: &str,
    delete_files: bool,
) -> anyhow::Result<()> {
    Output::header(&format!("Removing repository '{}'", name));
    println!();

    // Load manifest to get repo path
    let manifest_path = workspace_root.join(".gitgrip/manifests/manifest.yaml");
    let content = std::fs::read_to_string(&manifest_path)?;
    let manifest = Manifest::parse(&content)?;

    let repo_config = manifest
        .repos
        .get(name)
        .ok_or_else(|| anyhow::anyhow!("Repository '{}' not found in manifest", name))?;

    // Delete files if requested
    if delete_files {
        let repo_path = workspace_root.join(&repo_config.path);
        if repo_path.exists() {
            let spinner = Output::spinner("Removing repository files...");
            std::fs::remove_dir_all(&repo_path)?;
            spinner.finish_with_message("Files removed");
        }
    }

    // Remove from manifest (simple string replacement)
    // For a proper implementation, use serde_yaml to read/write
    let repo_pattern = format!("  {}:", name);
    let lines: Vec<&str> = content.lines().collect();
    let mut new_lines: Vec<&str> = Vec::new();
    let mut skip_until_next_repo = false;

    for line in lines {
        if line.starts_with(&repo_pattern) {
            skip_until_next_repo = true;
            continue;
        }

        if skip_until_next_repo {
            // Check if this is a new repo entry or top-level key
            if line.starts_with("  ") && !line.starts_with("    ") && line.contains(':') {
                skip_until_next_repo = false;
            } else if !line.starts_with("  ") && !line.starts_with("    ") {
                skip_until_next_repo = false;
            } else {
                continue;
            }
        }

        if !skip_until_next_repo {
            new_lines.push(line);
        }
    }

    std::fs::write(&manifest_path, new_lines.join("\n"))?;

    Output::success(&format!("Removed repository '{}' from manifest", name));
    Ok(())
}

/// Extract repository name from URL
fn extract_repo_name(url: &str) -> Option<String> {
    // Handle SSH URLs: git@github.com:owner/repo.git
    if url.starts_with("git@") {
        let parts: Vec<&str> = url.split('/').collect();
        if let Some(last) = parts.last() {
            return Some(last.trim_end_matches(".git").to_string());
        }
    }

    // Handle HTTPS URLs: https://github.com/owner/repo.git
    if url.starts_with("https://") || url.starts_with("http://") {
        let parts: Vec<&str> = url.split('/').collect();
        if let Some(last) = parts.last() {
            return Some(last.trim_end_matches(".git").to_string());
        }
    }

    None
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_extract_repo_name_ssh() {
        assert_eq!(
            extract_repo_name("git@github.com:owner/my-repo.git"),
            Some("my-repo".to_string())
        );
    }

    #[test]
    fn test_extract_repo_name_https() {
        assert_eq!(
            extract_repo_name("https://github.com/owner/my-repo.git"),
            Some("my-repo".to_string())
        );
    }

    #[test]
    fn test_extract_repo_name_no_extension() {
        assert_eq!(
            extract_repo_name("https://github.com/owner/my-repo"),
            Some("my-repo".to_string())
        );
    }

    #[test]
    fn test_extract_repo_name_gitlab() {
        assert_eq!(
            extract_repo_name("git@gitlab.com:group/subgroup/repo.git"),
            Some("repo".to_string())
        );
    }

    #[test]
    fn test_extract_repo_name_azure_devops() {
        assert_eq!(
            extract_repo_name("https://dev.azure.com/org/project/_git/my-repo"),
            Some("my-repo".to_string())
        );
    }

    #[test]
    fn test_extract_repo_name_invalid() {
        assert_eq!(extract_repo_name("not-a-url"), None);
    }

    #[test]
    fn test_extract_repo_name_nested_path() {
        // Nested paths work correctly - splits on '/' and strips .git
        assert_eq!(
            extract_repo_name("git@github.com:org/nested/repo.git"),
            Some("repo".to_string())
        );
    }
}
