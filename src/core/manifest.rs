//! Manifest parsing and validation
//!
//! The manifest file (manifest.yaml) defines the multi-repo workspace configuration.

use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::path::Path;
use thiserror::Error;

/// Errors that can occur when loading or validating a manifest
#[derive(Error, Debug)]
pub enum ManifestError {
    #[error("Failed to read manifest file: {0}")]
    IoError(#[from] std::io::Error),

    #[error("Failed to parse manifest YAML: {0}")]
    ParseError(#[from] serde_yaml::Error),

    #[error("Validation error: {0}")]
    ValidationError(String),

    #[error("Path escapes workspace boundary: {0}")]
    PathTraversal(String),
}

/// Hosting platform type
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize, Default)]
#[serde(rename_all = "lowercase")]
pub enum PlatformType {
    #[default]
    #[serde(rename = "github")]
    GitHub,
    #[serde(rename = "gitlab")]
    GitLab,
    #[serde(rename = "azure-devops")]
    AzureDevOps,
    #[serde(rename = "bitbucket")]
    Bitbucket,
}

impl std::fmt::Display for PlatformType {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            PlatformType::GitHub => write!(f, "github"),
            PlatformType::GitLab => write!(f, "gitlab"),
            PlatformType::AzureDevOps => write!(f, "azure-devops"),
            PlatformType::Bitbucket => write!(f, "bitbucket"),
        }
    }
}

/// Platform configuration for a repository
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PlatformConfig {
    #[serde(rename = "type")]
    pub platform_type: PlatformType,
    /// Base URL for self-hosted instances
    #[serde(skip_serializing_if = "Option::is_none")]
    pub base_url: Option<String>,
}

/// File copy configuration
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CopyFileConfig {
    /// Source path relative to repo
    pub src: String,
    /// Destination path relative to workspace root
    pub dest: String,
}

/// Symlink configuration
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LinkFileConfig {
    /// Source path relative to repo
    pub src: String,
    /// Destination path relative to workspace root
    pub dest: String,
}

/// Repository configuration in the manifest
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RepoConfig {
    /// Git URL (SSH or HTTPS)
    pub url: String,
    /// Local path relative to manifest root
    pub path: String,
    /// Default branch (e.g., "main", "master")
    #[serde(default = "default_branch")]
    pub default_branch: String,
    /// Optional file copies
    #[serde(skip_serializing_if = "Option::is_none")]
    pub copyfile: Option<Vec<CopyFileConfig>>,
    /// Optional symlinks
    #[serde(skip_serializing_if = "Option::is_none")]
    pub linkfile: Option<Vec<LinkFileConfig>>,
    /// Optional platform override
    #[serde(skip_serializing_if = "Option::is_none")]
    pub platform: Option<PlatformConfig>,
    /// Reference repo (read-only, excluded from branch/PR operations)
    #[serde(default, skip_serializing_if = "std::ops::Not::not")]
    pub reference: bool,
}

fn default_branch() -> String {
    "main".to_string()
}

/// Manifest repository self-tracking configuration
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ManifestRepoConfig {
    /// Git URL for the manifest repository
    pub url: String,
    /// Default branch (defaults to "main")
    #[serde(default = "default_branch")]
    pub default_branch: String,
    /// Optional file copies
    #[serde(skip_serializing_if = "Option::is_none")]
    pub copyfile: Option<Vec<CopyFileConfig>>,
    /// Optional symlinks
    #[serde(skip_serializing_if = "Option::is_none")]
    pub linkfile: Option<Vec<LinkFileConfig>>,
    /// Optional platform override
    #[serde(skip_serializing_if = "Option::is_none")]
    pub platform: Option<PlatformConfig>,
}

/// PR merge strategy
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, Default)]
#[serde(rename_all = "kebab-case")]
pub enum MergeStrategy {
    /// All linked PRs must be merged together or none
    #[default]
    AllOrNothing,
    /// Each PR can be merged independently
    Independent,
}

/// Global manifest settings
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ManifestSettings {
    /// PR title prefix (e.g., "[cross-repo]")
    #[serde(default = "default_pr_prefix")]
    pub pr_prefix: String,
    /// Merge strategy for linked PRs
    #[serde(default)]
    pub merge_strategy: MergeStrategy,
}

fn default_pr_prefix() -> String {
    "[cross-repo]".to_string()
}

impl Default for ManifestSettings {
    fn default() -> Self {
        Self {
            pr_prefix: default_pr_prefix(),
            merge_strategy: MergeStrategy::default(),
        }
    }
}

/// A step in a multi-step script
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ScriptStep {
    /// Step name for display
    pub name: String,
    /// Command to execute
    pub command: String,
    /// Optional working directory
    #[serde(skip_serializing_if = "Option::is_none")]
    pub cwd: Option<String>,
}

/// Workspace script definition
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct WorkspaceScript {
    /// Optional description
    #[serde(skip_serializing_if = "Option::is_none")]
    pub description: Option<String>,
    /// Single command (mutually exclusive with steps)
    #[serde(skip_serializing_if = "Option::is_none")]
    pub command: Option<String>,
    /// Working directory for command
    #[serde(skip_serializing_if = "Option::is_none")]
    pub cwd: Option<String>,
    /// Multi-step commands (mutually exclusive with command)
    #[serde(skip_serializing_if = "Option::is_none")]
    pub steps: Option<Vec<ScriptStep>>,
}

/// Hook command definition
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct HookCommand {
    /// Command to execute
    pub command: String,
    /// Optional working directory
    #[serde(skip_serializing_if = "Option::is_none")]
    pub cwd: Option<String>,
}

/// Workspace lifecycle hooks
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct WorkspaceHooks {
    /// Hooks to run after sync
    #[serde(rename = "post-sync", skip_serializing_if = "Option::is_none")]
    pub post_sync: Option<Vec<HookCommand>>,
    /// Hooks to run after checkout
    #[serde(rename = "post-checkout", skip_serializing_if = "Option::is_none")]
    pub post_checkout: Option<Vec<HookCommand>>,
}

/// Workspace configuration
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct WorkspaceConfig {
    /// Environment variables
    #[serde(skip_serializing_if = "Option::is_none")]
    pub env: Option<HashMap<String, String>>,
    /// Named scripts
    #[serde(skip_serializing_if = "Option::is_none")]
    pub scripts: Option<HashMap<String, WorkspaceScript>>,
    /// Lifecycle hooks
    #[serde(skip_serializing_if = "Option::is_none")]
    pub hooks: Option<WorkspaceHooks>,
}

/// The main manifest structure
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Manifest {
    /// Schema version
    #[serde(default = "default_version")]
    pub version: u32,
    /// Self-tracking manifest config (optional)
    #[serde(skip_serializing_if = "Option::is_none")]
    pub manifest: Option<ManifestRepoConfig>,
    /// Repository definitions
    pub repos: HashMap<String, RepoConfig>,
    /// Global settings
    #[serde(default)]
    pub settings: ManifestSettings,
    /// Workspace config (optional)
    #[serde(skip_serializing_if = "Option::is_none")]
    pub workspace: Option<WorkspaceConfig>,
}

fn default_version() -> u32 {
    1
}

impl Manifest {
    /// Load a manifest from a YAML file
    pub fn load<P: AsRef<Path>>(path: P) -> Result<Self, ManifestError> {
        let content = std::fs::read_to_string(path)?;
        Self::parse(&content)
    }

    /// Parse a manifest from a YAML string
    pub fn parse(yaml: &str) -> Result<Self, ManifestError> {
        let manifest: Manifest = serde_yaml::from_str(yaml)?;
        manifest.validate()?;
        Ok(manifest)
    }

    /// Validate the manifest
    pub fn validate(&self) -> Result<(), ManifestError> {
        // Must have at least one repo
        if self.repos.is_empty() {
            return Err(ManifestError::ValidationError(
                "Manifest must have at least one repository".to_string(),
            ));
        }

        // Validate each repo config
        for (name, repo) in &self.repos {
            self.validate_repo_config(name, repo)?;
        }

        // Validate manifest repo config if present
        if let Some(ref manifest_config) = self.manifest {
            self.validate_file_configs(
                "manifest",
                &manifest_config.copyfile,
                &manifest_config.linkfile,
            )?;
        }

        // Validate workspace scripts
        if let Some(ref workspace) = self.workspace {
            self.validate_workspace_config(workspace)?;
        }

        Ok(())
    }

    fn validate_repo_config(&self, name: &str, repo: &RepoConfig) -> Result<(), ManifestError> {
        // URL must be non-empty
        if repo.url.is_empty() {
            return Err(ManifestError::ValidationError(format!(
                "Repository '{}' must have a URL",
                name
            )));
        }

        // Path must be non-empty
        if repo.path.is_empty() {
            return Err(ManifestError::ValidationError(format!(
                "Repository '{}' must have a path",
                name
            )));
        }

        // Validate path doesn't escape boundary
        if path_escapes_boundary(&repo.path) {
            return Err(ManifestError::PathTraversal(format!(
                "Repository '{}' path escapes workspace boundary: {}",
                name, repo.path
            )));
        }

        // Validate copyfile/linkfile configs
        self.validate_file_configs(name, &repo.copyfile, &repo.linkfile)?;

        Ok(())
    }

    fn validate_file_configs(
        &self,
        repo_name: &str,
        copyfile: &Option<Vec<CopyFileConfig>>,
        linkfile: &Option<Vec<LinkFileConfig>>,
    ) -> Result<(), ManifestError> {
        if let Some(ref copyfiles) = copyfile {
            for cf in copyfiles {
                if cf.src.is_empty() || cf.dest.is_empty() {
                    return Err(ManifestError::ValidationError(format!(
                        "Repository '{}' has copyfile with empty src or dest",
                        repo_name
                    )));
                }
                if path_escapes_boundary(&cf.src) {
                    return Err(ManifestError::PathTraversal(format!(
                        "Repository '{}' copyfile src escapes boundary: {}",
                        repo_name, cf.src
                    )));
                }
                if path_escapes_boundary(&cf.dest) {
                    return Err(ManifestError::PathTraversal(format!(
                        "Repository '{}' copyfile dest escapes boundary: {}",
                        repo_name, cf.dest
                    )));
                }
            }
        }

        if let Some(ref linkfiles) = linkfile {
            for lf in linkfiles {
                if lf.src.is_empty() || lf.dest.is_empty() {
                    return Err(ManifestError::ValidationError(format!(
                        "Repository '{}' has linkfile with empty src or dest",
                        repo_name
                    )));
                }
                if path_escapes_boundary(&lf.src) {
                    return Err(ManifestError::PathTraversal(format!(
                        "Repository '{}' linkfile src escapes boundary: {}",
                        repo_name, lf.src
                    )));
                }
                if path_escapes_boundary(&lf.dest) {
                    return Err(ManifestError::PathTraversal(format!(
                        "Repository '{}' linkfile dest escapes boundary: {}",
                        repo_name, lf.dest
                    )));
                }
            }
        }

        Ok(())
    }

    fn validate_workspace_config(&self, workspace: &WorkspaceConfig) -> Result<(), ManifestError> {
        if let Some(ref scripts) = workspace.scripts {
            for (name, script) in scripts {
                // Scripts must have either command or steps, not both
                match (&script.command, &script.steps) {
                    (Some(_), Some(_)) => {
                        return Err(ManifestError::ValidationError(format!(
                            "Script '{}' cannot have both 'command' and 'steps'",
                            name
                        )));
                    }
                    (None, None) => {
                        return Err(ManifestError::ValidationError(format!(
                            "Script '{}' must have either 'command' or 'steps'",
                            name
                        )));
                    }
                    (None, Some(steps)) => {
                        // Validate each step
                        for step in steps {
                            if step.name.is_empty() {
                                return Err(ManifestError::ValidationError(format!(
                                    "Script '{}' has a step with empty name",
                                    name
                                )));
                            }
                            if step.command.is_empty() {
                                return Err(ManifestError::ValidationError(format!(
                                    "Script '{}' step '{}' has empty command",
                                    name, step.name
                                )));
                            }
                        }
                    }
                    (Some(_), None) => {
                        // Single command is valid
                    }
                }
            }
        }

        Ok(())
    }
}

/// Check if a path escapes the workspace boundary
fn path_escapes_boundary(path: &str) -> bool {
    // Normalize path separators
    let normalized = path.replace('\\', "/");

    // Reject: paths starting with "..", "/", or containing "/../"
    if normalized.starts_with("..") || normalized.starts_with('/') || normalized.contains("/../") {
        return true;
    }

    false
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_parse_minimal_manifest() {
        let yaml = r#"
repos:
  myrepo:
    url: git@github.com:user/repo.git
    path: repo
"#;
        let manifest = Manifest::parse(yaml).unwrap();
        assert_eq!(manifest.repos.len(), 1);
        assert!(manifest.repos.contains_key("myrepo"));
    }

    #[test]
    fn test_parse_full_manifest() {
        let yaml = r#"
version: 1
manifest:
  url: git@github.com:user/manifest.git
  default_branch: main
repos:
  app:
    url: git@github.com:user/app.git
    path: app
    default_branch: main
    copyfile:
      - src: README.md
        dest: APP_README.md
    linkfile:
      - src: config.yaml
        dest: app-config.yaml
settings:
  pr_prefix: "[multi-repo]"
  merge_strategy: all-or-nothing
workspace:
  env:
    NODE_ENV: development
  scripts:
    build:
      description: Build all packages
      command: npm run build
"#;
        let manifest = Manifest::parse(yaml).unwrap();
        assert_eq!(manifest.version, 1);
        assert!(manifest.manifest.is_some());
        assert_eq!(manifest.repos.len(), 1);
        assert_eq!(manifest.settings.pr_prefix, "[multi-repo]");
    }

    #[test]
    fn test_empty_repos_fails() {
        let yaml = r#"
repos: {}
"#;
        let result = Manifest::parse(yaml);
        assert!(result.is_err());
    }

    #[test]
    fn test_path_traversal_fails() {
        let yaml = r#"
repos:
  evil:
    url: git@github.com:user/repo.git
    path: ../outside
"#;
        let result = Manifest::parse(yaml);
        assert!(matches!(result, Err(ManifestError::PathTraversal(_))));
    }

    #[test]
    fn test_absolute_path_fails() {
        let yaml = r#"
repos:
  evil:
    url: git@github.com:user/repo.git
    path: /etc/passwd
"#;
        let result = Manifest::parse(yaml);
        assert!(matches!(result, Err(ManifestError::PathTraversal(_))));
    }

    #[test]
    fn test_script_with_both_command_and_steps_fails() {
        let yaml = r#"
repos:
  app:
    url: git@github.com:user/app.git
    path: app
workspace:
  scripts:
    bad:
      command: echo hello
      steps:
        - name: step1
          command: echo step
"#;
        let result = Manifest::parse(yaml);
        assert!(matches!(result, Err(ManifestError::ValidationError(_))));
    }

    #[test]
    fn test_path_escapes_boundary() {
        assert!(path_escapes_boundary(".."));
        assert!(path_escapes_boundary("../foo"));
        assert!(path_escapes_boundary("/etc"));
        assert!(path_escapes_boundary("foo/../../../etc"));
        assert!(!path_escapes_boundary("foo"));
        assert!(!path_escapes_boundary("foo/bar"));
        assert!(!path_escapes_boundary("./foo"));
    }

    #[test]
    fn test_reference_repos() {
        let yaml = r#"
repos:
  main-repo:
    url: git@github.com:user/main.git
    path: main
  ref-repo:
    url: https://github.com/other/reference.git
    path: ./ref/reference
    reference: true
"#;
        let manifest = Manifest::parse(yaml).unwrap();
        assert_eq!(manifest.repos.len(), 2);

        let main_repo = manifest.repos.get("main-repo").unwrap();
        assert!(!main_repo.reference);

        let ref_repo = manifest.repos.get("ref-repo").unwrap();
        assert!(ref_repo.reference);
    }

    #[test]
    fn test_reference_default_false() {
        let yaml = r#"
repos:
  myrepo:
    url: git@github.com:user/repo.git
    path: repo
"#;
        let manifest = Manifest::parse(yaml).unwrap();
        let repo = manifest.repos.get("myrepo").unwrap();
        assert!(!repo.reference); // Should default to false
    }
}
