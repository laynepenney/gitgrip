//! Init command implementation
//!
//! Initializes a new gitgrip workspace.

use crate::cli::output::Output;
use crate::git::clone_repo;
use std::path::PathBuf;

/// Run the init command
pub fn run_init(
    url: Option<&str>,
    path: Option<&str>,
) -> anyhow::Result<()> {
    let manifest_url = match url {
        Some(u) => u.to_string(),
        None => {
            anyhow::bail!("Manifest URL required. Usage: gr init <manifest-url>");
        }
    };

    // Determine target directory
    let target_dir = match path {
        Some(p) => PathBuf::from(p),
        None => {
            // Extract repo name from URL for directory name
            let name = extract_repo_name(&manifest_url)
                .unwrap_or_else(|| "workspace".to_string());
            std::env::current_dir()?.join(name)
        }
    };

    Output::header(&format!("Initializing workspace in {:?}", target_dir));
    println!();

    // Create workspace directory
    if target_dir.exists() {
        anyhow::bail!("Directory already exists: {:?}", target_dir);
    }
    std::fs::create_dir_all(&target_dir)?;

    // Create .gitgrip directory structure
    let gitgrip_dir = target_dir.join(".gitgrip");
    let manifests_dir = gitgrip_dir.join("manifests");
    std::fs::create_dir_all(&manifests_dir)?;

    // Clone manifest repository
    let spinner = Output::spinner("Cloning manifest repository...");
    match clone_repo(&manifest_url, &manifests_dir, None) {
        Ok(_) => {
            spinner.finish_with_message("Manifest cloned successfully");
        }
        Err(e) => {
            spinner.finish_with_message(format!("Failed to clone manifest: {}", e));
            // Clean up on failure
            let _ = std::fs::remove_dir_all(&target_dir);
            return Err(e.into());
        }
    }

    // Verify manifest.yaml exists
    let manifest_path = manifests_dir.join("manifest.yaml");
    if !manifest_path.exists() {
        let _ = std::fs::remove_dir_all(&target_dir);
        anyhow::bail!("No manifest.yaml found in repository");
    }

    // Create state file
    let state_path = gitgrip_dir.join("state.json");
    std::fs::write(&state_path, "{}")?;

    println!();
    Output::success("Workspace initialized successfully!");
    println!();
    println!("Next steps:");
    println!("  cd {:?}", target_dir);
    println!("  gr sync    # Clone all repositories");

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
            extract_repo_name("git@github.com:user/my-workspace.git"),
            Some("my-workspace".to_string())
        );
    }

    #[test]
    fn test_extract_repo_name_https() {
        assert_eq!(
            extract_repo_name("https://github.com/user/my-workspace.git"),
            Some("my-workspace".to_string())
        );
    }

    #[test]
    fn test_extract_repo_name_no_extension() {
        assert_eq!(
            extract_repo_name("https://github.com/user/workspace"),
            Some("workspace".to_string())
        );
    }
}
