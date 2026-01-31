//! Init command implementation
//!
//! Initializes a new gitgrip workspace.
//! Supports initialization from:
//! - A manifest URL (default)
//! - Existing local directories (--from-dirs)

use crate::cli::output::Output;
use crate::core::manifest::{Manifest, RepoConfig};
use crate::git::clone_repo;
use dialoguer::{theme::ColorfulTheme, Editor, Select};
use git2::Repository;
use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::process::Command;

/// A discovered repository from local directories
#[derive(Debug, Clone)]
pub struct DiscoveredRepo {
    /// Repository name (directory name by default)
    pub name: String,
    /// Path relative to workspace root
    pub path: String,
    /// Absolute path on disk
    pub absolute_path: PathBuf,
    /// Remote URL if configured
    pub url: Option<String>,
    /// Default branch (main, master, etc.)
    pub default_branch: String,
}

/// Run the init command
pub fn run_init(
    url: Option<&str>,
    path: Option<&str>,
    from_dirs: bool,
    dirs: &[String],
    interactive: bool,
) -> anyhow::Result<()> {
    if from_dirs {
        run_init_from_dirs(path, dirs, interactive)
    } else {
        run_init_from_url(url, path)
    }
}

/// Initialize workspace from a manifest URL (original behavior)
fn run_init_from_url(url: Option<&str>, path: Option<&str>) -> anyhow::Result<()> {
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
            let name = extract_repo_name(&manifest_url).unwrap_or_else(|| "workspace".to_string());
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

/// Initialize workspace from existing local directories
fn run_init_from_dirs(
    path: Option<&str>,
    dirs: &[String],
    interactive: bool,
) -> anyhow::Result<()> {
    // Determine workspace root
    let workspace_root = match path {
        Some(p) => PathBuf::from(p),
        None => std::env::current_dir()?,
    };

    // Check for existing workspace
    let gitgrip_dir = workspace_root.join(".gitgrip");
    if gitgrip_dir.exists() {
        anyhow::bail!(
            "A gitgrip workspace already exists at {:?}. \
             Remove .gitgrip directory to reinitialize.",
            workspace_root
        );
    }

    Output::header(&format!("Discovering repositories in {:?}", workspace_root));
    println!();

    // Discover repos
    let specific_dirs: Option<&[String]> = if dirs.is_empty() { None } else { Some(dirs) };
    let mut discovered = discover_repos(&workspace_root, specific_dirs)?;

    if discovered.is_empty() {
        anyhow::bail!(
            "No git repositories found. Make sure directories contain .git folders.\n\
             Tip: Use --dirs to specify directories explicitly."
        );
    }

    // Ensure unique names
    ensure_unique_names(&mut discovered);

    // Display discovered repos
    println!("Found {} repositories:", discovered.len());
    println!();
    for repo in &discovered {
        let url_display = repo.url.as_deref().unwrap_or("(no remote)");
        Output::list_item(&format!("{} → {} ({})", repo.name, repo.path, url_display));
    }
    println!();

    // Interactive mode
    let manifest = if interactive {
        match run_interactive_init(&workspace_root, &mut discovered)? {
            Some(m) => m,
            None => {
                Output::info("Initialization cancelled.");
                return Ok(());
            }
        }
    } else {
        generate_manifest(&discovered)
    };

    // Create .gitgrip directory structure
    let manifests_dir = gitgrip_dir.join("manifests");
    std::fs::create_dir_all(&manifests_dir)?;

    // Write manifest
    let manifest_path = manifests_dir.join("manifest.yaml");
    let yaml_content = manifest_to_yaml(&manifest)?;
    std::fs::write(&manifest_path, &yaml_content)?;

    // Create state file
    let state_path = gitgrip_dir.join("state.json");
    std::fs::write(&state_path, "{}")?;

    // Initialize manifest as git repo
    init_manifest_repo(&manifests_dir)?;

    println!();
    Output::success("Workspace initialized successfully!");
    println!();
    println!("Manifest created at: {}", manifest_path.display());
    println!();
    println!("Next steps:");
    println!("  1. Review the manifest: cat .gitgrip/manifests/manifest.yaml");
    println!("  2. Add a remote to the manifest repo:");
    println!("     cd .gitgrip/manifests && git remote add origin <your-manifest-url>");
    println!("  3. Run 'gr status' to verify your workspace");

    Ok(())
}

/// Discover git repositories in the given base directory
fn discover_repos(
    base_dir: &Path,
    specific_dirs: Option<&[String]>,
) -> anyhow::Result<Vec<DiscoveredRepo>> {
    let mut repos = Vec::new();

    let dirs_to_scan: Vec<PathBuf> = match specific_dirs {
        Some(dirs) => dirs
            .iter()
            .map(|d| {
                let p = PathBuf::from(d);
                if p.is_absolute() {
                    p
                } else {
                    base_dir.join(d)
                }
            })
            .collect(),
        None => {
            // Scan immediate children of base_dir
            std::fs::read_dir(base_dir)?
                .filter_map(|entry| entry.ok())
                .map(|entry| entry.path())
                .filter(|p| p.is_dir())
                .filter(|p| {
                    // Skip hidden directories
                    p.file_name()
                        .and_then(|n| n.to_str())
                        .map(|n| !n.starts_with('.'))
                        .unwrap_or(false)
                })
                .collect()
        }
    };

    for dir in dirs_to_scan {
        if let Some(repo) = try_discover_repo(base_dir, &dir)? {
            repos.push(repo);
        }
    }

    // Sort by name for consistent ordering
    repos.sort_by(|a, b| a.name.cmp(&b.name));

    Ok(repos)
}

/// Try to discover a repository in the given directory
fn try_discover_repo(workspace_root: &Path, dir: &Path) -> anyhow::Result<Option<DiscoveredRepo>> {
    // Check if it's a git repository
    let git_dir = dir.join(".git");
    if !git_dir.exists() {
        return Ok(None);
    }

    // Open the repository
    let repo = match Repository::open(dir) {
        Ok(r) => r,
        Err(_) => return Ok(None),
    };

    // Get directory name for repo name
    let name = dir
        .file_name()
        .and_then(|n| n.to_str())
        .map(|s| s.to_string())
        .unwrap_or_else(|| "repo".to_string());

    // Get relative path from workspace root
    let path = dir
        .strip_prefix(workspace_root)
        .map(|p| format!("./{}", p.display()))
        .unwrap_or_else(|_| dir.display().to_string());

    // Get remote URL (prefer origin)
    let url = get_remote_url(&repo);

    // Detect default branch
    let default_branch = detect_default_branch(&repo).unwrap_or_else(|_| "main".to_string());

    Ok(Some(DiscoveredRepo {
        name,
        path,
        absolute_path: dir.to_path_buf(),
        url,
        default_branch,
    }))
}

/// Get the remote URL from a repository (preferring origin)
fn get_remote_url(repo: &Repository) -> Option<String> {
    // Try origin first
    if let Ok(remote) = repo.find_remote("origin") {
        if let Some(url) = remote.url() {
            return Some(url.to_string());
        }
    }

    // Try any remote
    if let Ok(remotes) = repo.remotes() {
        for remote_name in remotes.iter().flatten() {
            if let Ok(remote) = repo.find_remote(remote_name) {
                if let Some(url) = remote.url() {
                    return Some(url.to_string());
                }
            }
        }
    }

    None
}

/// Detect the default branch of a repository
fn detect_default_branch(repo: &Repository) -> anyhow::Result<String> {
    // Try to get the current branch
    if let Ok(head) = repo.head() {
        if head.is_branch() {
            if let Some(name) = head.shorthand() {
                return Ok(name.to_string());
            }
        }
    }

    // Check for common default branch names
    for branch_name in &["main", "master", "develop"] {
        if repo
            .find_branch(branch_name, git2::BranchType::Local)
            .is_ok()
        {
            return Ok(branch_name.to_string());
        }
    }

    // Default to main
    Ok("main".to_string())
}

/// Ensure all repository names are unique by adding suffixes
fn ensure_unique_names(repos: &mut [DiscoveredRepo]) {
    let mut name_counts: HashMap<String, usize> = HashMap::new();

    // First pass: count occurrences
    for repo in repos.iter() {
        *name_counts.entry(repo.name.clone()).or_insert(0) += 1;
    }

    // Second pass: rename duplicates
    let mut name_indices: HashMap<String, usize> = HashMap::new();
    for repo in repos.iter_mut() {
        if name_counts[&repo.name] > 1 {
            let idx = name_indices.entry(repo.name.clone()).or_insert(1);
            if *idx > 1 {
                repo.name = format!("{}-{}", repo.name, idx);
            }
            *idx += 1;
        }
    }
}

/// Generate a manifest from discovered repositories
fn generate_manifest(repos: &[DiscoveredRepo]) -> Manifest {
    let mut repo_configs = HashMap::new();

    for repo in repos {
        let url = repo
            .url
            .clone()
            .unwrap_or_else(|| format!("git@github.com:OWNER/{}.git", repo.name));

        repo_configs.insert(
            repo.name.clone(),
            RepoConfig {
                url,
                path: repo.path.clone(),
                default_branch: repo.default_branch.clone(),
                copyfile: None,
                linkfile: None,
                platform: None,
            },
        );
    }

    Manifest {
        version: 1,
        manifest: None,
        repos: repo_configs,
        settings: Default::default(),
        workspace: None,
    }
}

/// Convert a manifest to YAML string
fn manifest_to_yaml(manifest: &Manifest) -> anyhow::Result<String> {
    let yaml = serde_yaml::to_string(manifest)?;
    Ok(yaml)
}

/// Run interactive initialization
fn run_interactive_init(
    _workspace_root: &Path,
    discovered: &mut Vec<DiscoveredRepo>,
) -> anyhow::Result<Option<Manifest>> {
    let theme = ColorfulTheme::default();

    loop {
        // Show options
        let options = vec![
            "Proceed with these repositories",
            "Edit repository list",
            "Cancel",
        ];

        let selection = Select::with_theme(&theme)
            .with_prompt("What would you like to do?")
            .items(&options)
            .default(0)
            .interact()?;

        match selection {
            0 => {
                // Proceed - generate and show YAML preview
                let manifest = generate_manifest(discovered);
                let yaml = manifest_to_yaml(&manifest)?;

                println!();
                println!("Generated manifest.yaml:");
                println!("─────────────────────────────────────────");
                println!("{}", yaml);
                println!("─────────────────────────────────────────");
                println!();

                let edit_options = vec!["Use this manifest", "Edit in editor", "Go back"];

                let edit_selection = Select::with_theme(&theme)
                    .with_prompt("Review the manifest")
                    .items(&edit_options)
                    .default(0)
                    .interact()?;

                match edit_selection {
                    0 => return Ok(Some(manifest)),
                    1 => {
                        // Edit in external editor
                        if let Some(edited_yaml) = Editor::new().extension(".yaml").edit(&yaml)? {
                            // Parse and validate the edited YAML
                            match Manifest::parse(&edited_yaml) {
                                Ok(edited_manifest) => {
                                    println!();
                                    Output::success("Manifest validated successfully.");
                                    return Ok(Some(edited_manifest));
                                }
                                Err(e) => {
                                    Output::error(&format!("Invalid YAML: {}", e));
                                    println!("Please fix the errors and try again.");
                                    continue;
                                }
                            }
                        } else {
                            Output::info("No changes made.");
                            continue;
                        }
                    }
                    2 => continue,
                    _ => unreachable!(),
                }
            }
            1 => {
                // Edit repository list
                run_edit_repo_list(discovered)?;
                if discovered.is_empty() {
                    Output::warning("No repositories selected. Add at least one to continue.");
                    continue;
                }
                // Show updated list
                println!();
                println!("Selected repositories:");
                for repo in discovered.iter() {
                    Output::list_item(&format!("{} → {}", repo.name, repo.path));
                }
                println!();
            }
            2 => return Ok(None),
            _ => unreachable!(),
        }
    }
}

/// Interactive editing of the repository list
fn run_edit_repo_list(repos: &mut Vec<DiscoveredRepo>) -> anyhow::Result<()> {
    let theme = ColorfulTheme::default();

    loop {
        let mut options: Vec<String> = repos
            .iter()
            .map(|r| format!("[✓] {} ({})", r.name, r.path))
            .collect();
        options.push("Done editing".to_string());

        let selection = Select::with_theme(&theme)
            .with_prompt("Toggle repositories (select to remove)")
            .items(&options)
            .default(options.len() - 1)
            .interact()?;

        if selection == repos.len() {
            // Done editing
            break;
        }

        // Remove the selected repo
        let removed = repos.remove(selection);
        Output::info(&format!("Removed: {}", removed.name));

        if repos.is_empty() {
            Output::warning("All repositories removed.");
            break;
        }
    }

    Ok(())
}

/// Initialize the manifest directory as a git repository
fn init_manifest_repo(manifests_dir: &Path) -> anyhow::Result<()> {
    // Initialize git repo
    let output = Command::new("git")
        .args(["init"])
        .current_dir(manifests_dir)
        .output()?;

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        anyhow::bail!("Failed to initialize manifest git repo: {}", stderr);
    }

    // Stage manifest.yaml
    let output = Command::new("git")
        .args(["add", "manifest.yaml"])
        .current_dir(manifests_dir)
        .output()?;

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        anyhow::bail!("Failed to stage manifest.yaml: {}", stderr);
    }

    // Create initial commit
    let output = Command::new("git")
        .args([
            "commit",
            "-m",
            "Initial manifest\n\nGenerated by gr init --from-dirs",
        ])
        .current_dir(manifests_dir)
        .output()?;

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        // Don't fail if commit fails (e.g., no git user configured)
        Output::warning(&format!(
            "Could not create initial commit: {}. You may need to commit manually.",
            stderr.trim()
        ));
    }

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
    use tempfile::TempDir;

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

    #[test]
    fn test_ensure_unique_names() {
        let mut repos = vec![
            DiscoveredRepo {
                name: "app".to_string(),
                path: "./app1".to_string(),
                absolute_path: PathBuf::from("/tmp/app1"),
                url: None,
                default_branch: "main".to_string(),
            },
            DiscoveredRepo {
                name: "app".to_string(),
                path: "./app2".to_string(),
                absolute_path: PathBuf::from("/tmp/app2"),
                url: None,
                default_branch: "main".to_string(),
            },
            DiscoveredRepo {
                name: "backend".to_string(),
                path: "./backend".to_string(),
                absolute_path: PathBuf::from("/tmp/backend"),
                url: None,
                default_branch: "main".to_string(),
            },
        ];

        ensure_unique_names(&mut repos);

        // First "app" keeps its name, second gets "-2"
        assert_eq!(repos[0].name, "app");
        assert_eq!(repos[1].name, "app-2");
        assert_eq!(repos[2].name, "backend");
    }

    #[test]
    fn test_generate_manifest() {
        let repos = vec![
            DiscoveredRepo {
                name: "frontend".to_string(),
                path: "./frontend".to_string(),
                absolute_path: PathBuf::from("/tmp/frontend"),
                url: Some("git@github.com:org/frontend.git".to_string()),
                default_branch: "main".to_string(),
            },
            DiscoveredRepo {
                name: "backend".to_string(),
                path: "./backend".to_string(),
                absolute_path: PathBuf::from("/tmp/backend"),
                url: None,
                default_branch: "master".to_string(),
            },
        ];

        let manifest = generate_manifest(&repos);

        assert_eq!(manifest.repos.len(), 2);
        assert!(manifest.repos.contains_key("frontend"));
        assert!(manifest.repos.contains_key("backend"));
        assert_eq!(
            manifest.repos["frontend"].url,
            "git@github.com:org/frontend.git"
        );
        assert_eq!(manifest.repos["frontend"].default_branch, "main");
        // Backend should have placeholder URL
        assert!(manifest.repos["backend"].url.contains("OWNER"));
        assert_eq!(manifest.repos["backend"].default_branch, "master");
    }

    #[test]
    fn test_discover_repos_empty() {
        let temp = TempDir::new().unwrap();
        let repos = discover_repos(temp.path(), None).unwrap();
        assert!(repos.is_empty());
    }

    #[test]
    fn test_discover_repos_with_git_dir() {
        let temp = TempDir::new().unwrap();

        // Create a subdirectory with a git repo
        let repo_dir = temp.path().join("my-repo");
        std::fs::create_dir_all(&repo_dir).unwrap();
        Repository::init(&repo_dir).unwrap();

        let repos = discover_repos(temp.path(), None).unwrap();
        assert_eq!(repos.len(), 1);
        assert_eq!(repos[0].name, "my-repo");
    }

    #[test]
    fn test_discover_repos_skips_hidden() {
        let temp = TempDir::new().unwrap();

        // Create a hidden directory with a git repo
        let hidden_dir = temp.path().join(".hidden-repo");
        std::fs::create_dir_all(&hidden_dir).unwrap();
        Repository::init(&hidden_dir).unwrap();

        // Create a normal directory with a git repo
        let repo_dir = temp.path().join("visible-repo");
        std::fs::create_dir_all(&repo_dir).unwrap();
        Repository::init(&repo_dir).unwrap();

        let repos = discover_repos(temp.path(), None).unwrap();
        assert_eq!(repos.len(), 1);
        assert_eq!(repos[0].name, "visible-repo");
    }

    #[test]
    fn test_manifest_to_yaml() {
        let repos = vec![DiscoveredRepo {
            name: "test".to_string(),
            path: "./test".to_string(),
            absolute_path: PathBuf::from("/tmp/test"),
            url: Some("git@github.com:org/test.git".to_string()),
            default_branch: "main".to_string(),
        }];

        let manifest = generate_manifest(&repos);
        let yaml = manifest_to_yaml(&manifest).unwrap();

        assert!(yaml.contains("repos:"));
        assert!(yaml.contains("test:"));
        assert!(yaml.contains("git@github.com:org/test.git"));
    }
}
