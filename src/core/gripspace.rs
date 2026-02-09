//! Gripspace include resolution
//!
//! Gripspaces allow composable manifest inheritance. A workspace manifest can
//! include one or more gripspace repositories, inheriting their repos, scripts,
//! env vars, hooks, and linkfiles. Local values always win on conflict.

use crate::core::manifest::{
    GripspaceConfig, HookCommand, Manifest, ManifestError, WorkspaceConfig, WorkspaceHooks,
};
use crate::git::clone_repo;
use std::collections::{HashMap, HashSet};
use std::path::{Path, PathBuf};
use std::process::Command;

/// Maximum depth for recursive gripspace includes
const MAX_GRIPSPACE_DEPTH: usize = 5;

/// Extract a gripspace name from its URL.
///
/// Takes the last path component without `.git` suffix.
/// e.g., `https://github.com/user/codi-gripspace.git` -> `codi-gripspace`
pub fn gripspace_name(url: &str) -> String {
    let url = url.trim_end_matches('/');
    let last = url.rsplit('/').next().unwrap_or(url);
    // Handle SSH URLs like git@github.com:user/repo.git
    let last = last.rsplit(':').next().unwrap_or(last);
    let last = last.rsplit('/').next().unwrap_or(last);
    last.trim_end_matches(".git").to_string()
}

/// Ensure a gripspace is cloned locally. Returns the path to the gripspace directory.
///
/// If the gripspace is already cloned, this is a no-op.
/// The gripspace is cloned into `gripspaces_dir/<name>/`.
pub fn ensure_gripspace(
    gripspaces_dir: &Path,
    config: &GripspaceConfig,
) -> Result<PathBuf, ManifestError> {
    let name = gripspace_name(&config.url);
    let gripspace_path = gripspaces_dir.join(&name);

    if gripspace_path.exists() {
        // Already cloned, just checkout the right rev if specified
        if let Some(ref rev) = config.rev {
            checkout_rev(&gripspace_path, rev)?;
        }
        return Ok(gripspace_path);
    }

    // Clone the gripspace
    std::fs::create_dir_all(gripspaces_dir).map_err(|e| {
        ManifestError::GripspaceError(format!("Failed to create gripspaces dir: {}", e))
    })?;

    clone_repo(&config.url, &gripspace_path, None).map_err(|e| {
        ManifestError::GripspaceError(format!(
            "Failed to clone gripspace '{}': {}",
            config.url, e
        ))
    })?;

    // Checkout specific revision if specified
    if let Some(ref rev) = config.rev {
        checkout_rev(&gripspace_path, rev)?;
    }

    Ok(gripspace_path)
}

/// Update a gripspace by fetching and pulling latest.
pub fn update_gripspace(
    gripspace_path: &Path,
    config: &GripspaceConfig,
) -> Result<(), ManifestError> {
    if !gripspace_path.exists() {
        return Err(ManifestError::GripspaceError(format!(
            "Gripspace directory does not exist: {}",
            gripspace_path.display()
        )));
    }

    // Fetch from origin
    let output = Command::new("git")
        .args(["fetch", "origin"])
        .current_dir(gripspace_path)
        .output()
        .map_err(|e| ManifestError::GripspaceError(format!("Failed to fetch gripspace: {}", e)))?;

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        return Err(ManifestError::GripspaceError(format!(
            "Failed to fetch gripspace: {}",
            stderr.trim()
        )));
    }

    // Checkout specific rev or pull latest
    if let Some(ref rev) = config.rev {
        checkout_rev(gripspace_path, rev)?;
    } else {
        // Pull latest on current branch
        let output = Command::new("git")
            .args(["pull", "--ff-only"])
            .current_dir(gripspace_path)
            .output()
            .map_err(|e| {
                ManifestError::GripspaceError(format!("Failed to pull gripspace: {}", e))
            })?;

        if !output.status.success() {
            let stderr = String::from_utf8_lossy(&output.stderr);
            // Non-fatal: gripspace may be on a detached HEAD or have diverged
            // Try a reset to origin/HEAD instead
            let _ = Command::new("git")
                .args(["reset", "--hard", "origin/HEAD"])
                .current_dir(gripspace_path)
                .output();
            // Only error if this is genuinely problematic
            if stderr.contains("fatal") {
                return Err(ManifestError::GripspaceError(format!(
                    "Failed to update gripspace: {}",
                    stderr.trim()
                )));
            }
        }
    }

    Ok(())
}

/// Checkout a specific revision (branch, tag, or SHA) in a gripspace.
fn checkout_rev(path: &Path, rev: &str) -> Result<(), ManifestError> {
    let output = Command::new("git")
        .args(["checkout", rev])
        .current_dir(path)
        .output()
        .map_err(|e| {
            ManifestError::GripspaceError(format!("Failed to checkout rev '{}': {}", rev, e))
        })?;

    if !output.status.success() {
        // Try as a remote branch
        let output = Command::new("git")
            .args(["checkout", "-B", rev, &format!("origin/{}", rev)])
            .current_dir(path)
            .output()
            .map_err(|e| {
                ManifestError::GripspaceError(format!("Failed to checkout rev '{}': {}", rev, e))
            })?;

        if !output.status.success() {
            let stderr = String::from_utf8_lossy(&output.stderr);
            return Err(ManifestError::GripspaceError(format!(
                "Failed to checkout rev '{}': {}",
                rev,
                stderr.trim()
            )));
        }
    }

    Ok(())
}

/// Resolve all gripspaces: clone/load their manifests, merge into the local manifest.
///
/// Processes gripspaces in order, with recursive include support.
/// Local manifest values always win on conflicts.
pub fn resolve_all_gripspaces(
    manifest: &mut Manifest,
    gripspaces_dir: &Path,
) -> Result<(), ManifestError> {
    let gripspaces = match manifest.gripspaces.take() {
        Some(gs) if !gs.is_empty() => gs,
        _ => return Ok(()),
    };

    let mut visited = HashSet::new();
    let mut merged_repos = HashMap::new();
    let mut merged_scripts = HashMap::new();
    let mut merged_env = HashMap::new();
    let mut merged_hooks_post_sync: Vec<HookCommand> = Vec::new();
    let mut merged_hooks_post_checkout: Vec<HookCommand> = Vec::new();
    let mut merged_linkfiles = Vec::new();
    let mut merged_copyfiles = Vec::new();

    // Process each gripspace
    for gs_config in &gripspaces {
        resolve_gripspace_recursive(
            gs_config,
            gripspaces_dir,
            &mut visited,
            0,
            &mut merged_repos,
            &mut merged_scripts,
            &mut merged_env,
            &mut merged_hooks_post_sync,
            &mut merged_hooks_post_checkout,
            &mut merged_linkfiles,
            &mut merged_copyfiles,
        )?;
    }

    // Now merge gripspace values into the manifest, with local values winning

    // Repos: gripspace repos first, then local overrides
    for (name, config) in merged_repos {
        manifest.repos.entry(name).or_insert(config);
    }

    // Workspace: merge scripts, env, hooks
    let workspace = manifest.workspace.get_or_insert_with(WorkspaceConfig::default);

    // Scripts: gripspace scripts first, local overrides
    if !merged_scripts.is_empty() {
        let scripts = workspace.scripts.get_or_insert_with(HashMap::new);
        for (name, script) in merged_scripts {
            scripts.entry(name).or_insert(script);
        }
    }

    // Env: gripspace env first, local overrides
    if !merged_env.is_empty() {
        let env = workspace.env.get_or_insert_with(HashMap::new);
        for (key, value) in merged_env {
            env.entry(key).or_insert(value);
        }
    }

    // Hooks: concatenate (gripspace hooks run first, then local)
    if !merged_hooks_post_sync.is_empty() || !merged_hooks_post_checkout.is_empty() {
        let hooks = workspace.hooks.get_or_insert_with(WorkspaceHooks::default);

        if !merged_hooks_post_sync.is_empty() {
            let existing = hooks.post_sync.take().unwrap_or_default();
            merged_hooks_post_sync.extend(existing);
            hooks.post_sync = Some(merged_hooks_post_sync);
        }

        if !merged_hooks_post_checkout.is_empty() {
            let existing = hooks.post_checkout.take().unwrap_or_default();
            merged_hooks_post_checkout.extend(existing);
            hooks.post_checkout = Some(merged_hooks_post_checkout);
        }
    }

    // Linkfiles from gripspaces are tracked separately — they'll be applied by the link command
    // We store them as manifest-level linkfiles, with local ones overriding by dest
    if let Some(ref mut manifest_config) = manifest.manifest {
        if !merged_linkfiles.is_empty() {
            let local_linkfiles = manifest_config.linkfile.take().unwrap_or_default();
            let local_dests: HashSet<String> =
                local_linkfiles.iter().map(|l| l.dest.clone()).collect();
            // Keep gripspace linkfiles that don't conflict with local
            let mut combined: Vec<_> = merged_linkfiles
                .into_iter()
                .filter(|l: &crate::core::manifest::LinkFileConfig| !local_dests.contains(&l.dest))
                .collect();
            combined.extend(local_linkfiles);
            if !combined.is_empty() {
                manifest_config.linkfile = Some(combined);
            }
        }

        if !merged_copyfiles.is_empty() {
            let local_copyfiles = manifest_config.copyfile.take().unwrap_or_default();
            let local_dests: HashSet<String> =
                local_copyfiles.iter().map(|c| c.dest.clone()).collect();
            let mut combined: Vec<_> = merged_copyfiles
                .into_iter()
                .filter(|c: &crate::core::manifest::CopyFileConfig| {
                    !local_dests.contains(&c.dest)
                })
                .collect();
            combined.extend(local_copyfiles);
            if !combined.is_empty() {
                manifest_config.copyfile = Some(combined);
            }
        }
    }

    // Put gripspaces back (for status display and re-resolution on sync)
    manifest.gripspaces = Some(gripspaces);

    Ok(())
}

/// Recursively resolve a single gripspace and its nested gripspaces.
#[allow(clippy::too_many_arguments)]
fn resolve_gripspace_recursive(
    config: &GripspaceConfig,
    gripspaces_dir: &Path,
    visited: &mut HashSet<String>,
    depth: usize,
    merged_repos: &mut HashMap<String, crate::core::manifest::RepoConfig>,
    merged_scripts: &mut HashMap<String, crate::core::manifest::WorkspaceScript>,
    merged_env: &mut HashMap<String, String>,
    merged_hooks_post_sync: &mut Vec<HookCommand>,
    merged_hooks_post_checkout: &mut Vec<HookCommand>,
    merged_linkfiles: &mut Vec<crate::core::manifest::LinkFileConfig>,
    merged_copyfiles: &mut Vec<crate::core::manifest::CopyFileConfig>,
) -> Result<(), ManifestError> {
    if depth >= MAX_GRIPSPACE_DEPTH {
        return Err(ManifestError::GripspaceError(format!(
            "Maximum gripspace include depth ({}) exceeded for '{}'",
            MAX_GRIPSPACE_DEPTH, config.url
        )));
    }

    // Cycle detection
    if !visited.insert(config.url.clone()) {
        return Err(ManifestError::GripspaceError(format!(
            "Circular gripspace include detected: '{}'",
            config.url
        )));
    }

    let name = gripspace_name(&config.url);
    let gripspace_path = gripspaces_dir.join(&name);

    // Load the gripspace's manifest
    let manifest_path = gripspace_path.join("manifest.yaml");
    if !manifest_path.exists() {
        return Err(ManifestError::GripspaceError(format!(
            "Gripspace '{}' has no manifest.yaml",
            name
        )));
    }

    let gs_manifest = Manifest::parse_raw(&std::fs::read_to_string(&manifest_path).map_err(
        |e| {
            ManifestError::GripspaceError(format!(
                "Failed to read gripspace '{}' manifest: {}",
                name, e
            ))
        },
    )?)?;

    // Recursively resolve nested gripspaces first
    if let Some(ref nested_gripspaces) = gs_manifest.gripspaces {
        for nested_config in nested_gripspaces {
            resolve_gripspace_recursive(
                nested_config,
                gripspaces_dir,
                visited,
                depth + 1,
                merged_repos,
                merged_scripts,
                merged_env,
                merged_hooks_post_sync,
                merged_hooks_post_checkout,
                merged_linkfiles,
                merged_copyfiles,
            )?;
        }
    }

    // Merge repos (later gripspaces override earlier, but local always wins last)
    for (repo_name, repo_config) in gs_manifest.repos {
        merged_repos.entry(repo_name).or_insert(repo_config);
    }

    // Merge workspace config
    if let Some(ref workspace) = gs_manifest.workspace {
        if let Some(ref scripts) = workspace.scripts {
            for (name, script) in scripts {
                merged_scripts
                    .entry(name.clone())
                    .or_insert_with(|| script.clone());
            }
        }

        if let Some(ref env) = workspace.env {
            for (key, value) in env {
                merged_env
                    .entry(key.clone())
                    .or_insert_with(|| value.clone());
            }
        }

        if let Some(ref hooks) = workspace.hooks {
            if let Some(ref post_sync) = hooks.post_sync {
                merged_hooks_post_sync.extend(post_sync.clone());
            }
            if let Some(ref post_checkout) = hooks.post_checkout {
                merged_hooks_post_checkout.extend(post_checkout.clone());
            }
        }
    }

    // Merge linkfiles and copyfiles from gripspace manifest config
    // These need path adjustment: source from .gitgrip/gripspaces/<name>/
    if let Some(ref manifest_config) = gs_manifest.manifest {
        if let Some(ref linkfiles) = manifest_config.linkfile {
            for lf in linkfiles {
                merged_linkfiles.push(crate::core::manifest::LinkFileConfig {
                    // Prefix src with gripspace name so link.rs knows where to find it
                    src: format!("gripspace:{}:{}", name, lf.src),
                    dest: lf.dest.clone(),
                });
            }
        }
        if let Some(ref copyfiles) = manifest_config.copyfile {
            for cf in copyfiles {
                merged_copyfiles.push(crate::core::manifest::CopyFileConfig {
                    src: format!("gripspace:{}:{}", name, cf.src),
                    dest: cf.dest.clone(),
                });
            }
        }
    }

    Ok(())
}

/// Get the current revision (branch or SHA) of a gripspace.
pub fn get_gripspace_rev(gripspace_path: &Path) -> Option<String> {
    let output = Command::new("git")
        .args(["rev-parse", "--abbrev-ref", "HEAD"])
        .current_dir(gripspace_path)
        .output()
        .ok()?;

    if output.status.success() {
        let branch = String::from_utf8_lossy(&output.stdout).trim().to_string();
        if branch == "HEAD" {
            // Detached HEAD — return SHA
            let output = Command::new("git")
                .args(["rev-parse", "--short", "HEAD"])
                .current_dir(gripspace_path)
                .output()
                .ok()?;
            Some(String::from_utf8_lossy(&output.stdout).trim().to_string())
        } else {
            Some(branch)
        }
    } else {
        None
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_gripspace_name_https() {
        assert_eq!(
            gripspace_name("https://github.com/user/codi-gripspace.git"),
            "codi-gripspace"
        );
    }

    #[test]
    fn test_gripspace_name_ssh() {
        assert_eq!(
            gripspace_name("git@github.com:user/codi-gripspace.git"),
            "codi-gripspace"
        );
    }

    #[test]
    fn test_gripspace_name_no_extension() {
        assert_eq!(
            gripspace_name("https://github.com/user/my-space"),
            "my-space"
        );
    }

    #[test]
    fn test_gripspace_name_trailing_slash() {
        assert_eq!(
            gripspace_name("https://github.com/user/my-space/"),
            "my-space"
        );
    }

    #[test]
    fn test_resolve_no_gripspaces() {
        let mut manifest = Manifest {
            version: 1,
            gripspaces: None,
            manifest: None,
            repos: HashMap::new(),
            settings: Default::default(),
            workspace: None,
        };

        let temp = tempfile::tempdir().unwrap();
        let result = resolve_all_gripspaces(&mut manifest, temp.path());
        assert!(result.is_ok());
    }

    #[test]
    fn test_resolve_empty_gripspaces() {
        let mut manifest = Manifest {
            version: 1,
            gripspaces: Some(vec![]),
            manifest: None,
            repos: HashMap::new(),
            settings: Default::default(),
            workspace: None,
        };

        let temp = tempfile::tempdir().unwrap();
        let result = resolve_all_gripspaces(&mut manifest, temp.path());
        assert!(result.is_ok());
    }

    #[test]
    fn test_resolve_missing_gripspace_manifest() {
        let temp = tempfile::tempdir().unwrap();
        let gripspaces_dir = temp.path().join("gripspaces");
        // Create gripspace dir but no manifest.yaml
        std::fs::create_dir_all(gripspaces_dir.join("test-gripspace")).unwrap();

        let mut manifest = Manifest {
            version: 1,
            gripspaces: Some(vec![GripspaceConfig {
                url: "https://github.com/user/test-gripspace.git".to_string(),
                rev: None,
            }]),
            manifest: None,
            repos: HashMap::new(),
            settings: Default::default(),
            workspace: None,
        };

        let result = resolve_all_gripspaces(&mut manifest, &gripspaces_dir);
        assert!(result.is_err());
        let err = result.unwrap_err().to_string();
        assert!(err.contains("no manifest.yaml"));
    }

    #[test]
    fn test_resolve_merges_repos() {
        let temp = tempfile::tempdir().unwrap();
        let gripspaces_dir = temp.path();

        // Create gripspace with a repo
        let gs_dir = gripspaces_dir.join("base-gripspace");
        std::fs::create_dir_all(&gs_dir).unwrap();
        std::fs::write(
            gs_dir.join("manifest.yaml"),
            r#"
version: 1
repos:
  shared-repo:
    url: https://github.com/user/shared.git
    path: ./shared
"#,
        )
        .unwrap();

        let mut manifest = Manifest {
            version: 1,
            gripspaces: Some(vec![GripspaceConfig {
                url: "https://github.com/user/base-gripspace.git".to_string(),
                rev: None,
            }]),
            manifest: None,
            repos: {
                let mut m = HashMap::new();
                m.insert(
                    "local-repo".to_string(),
                    crate::core::manifest::RepoConfig {
                        url: "https://github.com/user/local.git".to_string(),
                        path: "./local".to_string(),
                        default_branch: "main".to_string(),
                        copyfile: None,
                        linkfile: None,
                        platform: None,
                        reference: false,
                        groups: Vec::new(),
                    },
                );
                m
            },
            settings: Default::default(),
            workspace: None,
        };

        let result = resolve_all_gripspaces(&mut manifest, gripspaces_dir);
        assert!(result.is_ok());

        // Should have both repos
        assert_eq!(manifest.repos.len(), 2);
        assert!(manifest.repos.contains_key("shared-repo"));
        assert!(manifest.repos.contains_key("local-repo"));
    }

    #[test]
    fn test_resolve_local_repo_wins() {
        let temp = tempfile::tempdir().unwrap();
        let gripspaces_dir = temp.path();

        // Create gripspace with a repo
        let gs_dir = gripspaces_dir.join("base-gripspace");
        std::fs::create_dir_all(&gs_dir).unwrap();
        std::fs::write(
            gs_dir.join("manifest.yaml"),
            r#"
version: 1
repos:
  my-repo:
    url: https://github.com/user/gripspace-version.git
    path: ./my-repo
"#,
        )
        .unwrap();

        let mut manifest = Manifest {
            version: 1,
            gripspaces: Some(vec![GripspaceConfig {
                url: "https://github.com/user/base-gripspace.git".to_string(),
                rev: None,
            }]),
            manifest: None,
            repos: {
                let mut m = HashMap::new();
                m.insert(
                    "my-repo".to_string(),
                    crate::core::manifest::RepoConfig {
                        url: "https://github.com/user/local-version.git".to_string(),
                        path: "./my-repo-local".to_string(),
                        default_branch: "main".to_string(),
                        copyfile: None,
                        linkfile: None,
                        platform: None,
                        reference: false,
                        groups: Vec::new(),
                    },
                );
                m
            },
            settings: Default::default(),
            workspace: None,
        };

        let result = resolve_all_gripspaces(&mut manifest, gripspaces_dir);
        assert!(result.is_ok());

        // Local repo should win
        assert_eq!(manifest.repos.len(), 1);
        let repo = manifest.repos.get("my-repo").unwrap();
        assert_eq!(repo.url, "https://github.com/user/local-version.git");
        assert_eq!(repo.path, "./my-repo-local");
    }

    #[test]
    fn test_resolve_merges_scripts() {
        let temp = tempfile::tempdir().unwrap();
        let gripspaces_dir = temp.path();

        let gs_dir = gripspaces_dir.join("base-gripspace");
        std::fs::create_dir_all(&gs_dir).unwrap();
        std::fs::write(
            gs_dir.join("manifest.yaml"),
            r#"
version: 1
repos:
  shared:
    url: https://github.com/user/shared.git
    path: ./shared
workspace:
  scripts:
    build:
      command: "echo build from gripspace"
      description: "Build from gripspace"
    test:
      command: "echo test from gripspace"
      description: "Test from gripspace"
"#,
        )
        .unwrap();

        let mut manifest = Manifest {
            version: 1,
            gripspaces: Some(vec![GripspaceConfig {
                url: "https://github.com/user/base-gripspace.git".to_string(),
                rev: None,
            }]),
            manifest: None,
            repos: HashMap::new(),
            settings: Default::default(),
            workspace: Some(WorkspaceConfig {
                scripts: Some({
                    let mut m = HashMap::new();
                    m.insert(
                        "build".to_string(),
                        crate::core::manifest::WorkspaceScript {
                            command: Some("echo local build".to_string()),
                            description: Some("Local build".to_string()),
                            cwd: None,
                            steps: None,
                        },
                    );
                    m
                }),
                env: None,
                hooks: None,
                ci: None,
            }),
        };

        let result = resolve_all_gripspaces(&mut manifest, gripspaces_dir);
        assert!(result.is_ok());

        let scripts = manifest.workspace.as_ref().unwrap().scripts.as_ref().unwrap();
        // Local "build" should win
        assert_eq!(
            scripts.get("build").unwrap().command.as_deref(),
            Some("echo local build")
        );
        // Gripspace "test" should be inherited
        assert!(scripts.contains_key("test"));
        assert_eq!(
            scripts.get("test").unwrap().command.as_deref(),
            Some("echo test from gripspace")
        );
    }
}
