//! Workspace checkouts — independent child clones materialized from the cache
//!
//! Each checkout lives under `.grip/checkouts/<name>/` and contains full clones
//! of manifest repos, created with `--reference` to reuse objects from the
//! bare cache. Checkouts are independently disposable.

use anyhow::{Context, Result};
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::process::Command;

use crate::core::manifest::{Manifest, PlatformConfig, RepoConfig};
use crate::core::manifest_paths;
use crate::core::repo::RepoInfo;
use crate::core::workspace_cache;
use crate::util::log_cmd;

/// Directory name under .grip/ where checkouts live.
const CHECKOUTS_DIR: &str = "checkouts";

/// Metadata for a single checkout.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CheckoutInfo {
    pub name: String,
    pub path: PathBuf,
    pub repos: Vec<CheckoutRepo>,
    pub created_at: String,
}

/// A single repo within a checkout.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CheckoutRepo {
    pub name: String,
    pub path: PathBuf,
    pub branch: Option<String>,
}

/// Resolve the checkout root: `<workspace_root>/.grip/checkouts/<name>/`
pub fn checkout_path(workspace_root: &Path, name: &str) -> PathBuf {
    workspace_root.join(".grip").join(CHECKOUTS_DIR).join(name)
}

/// Check whether a checkout exists.
pub fn checkout_exists(workspace_root: &Path, name: &str) -> bool {
    checkout_path(workspace_root, name).is_dir()
}

/// Materialize a single repo into a checkout from the cache.
///
/// Uses `git clone --reference <cache> <url> <target>` if a cache exists,
/// otherwise falls back to a direct clone.
/// Optionally checks out a specific branch.
pub fn materialize_repo(
    workspace_root: &Path,
    checkout_name: &str,
    repo_name: &str,
    repo_url: &str,
    repo_path: &str,
    branch: Option<&str>,
) -> Result<PathBuf> {
    let checkout_root = checkout_path(workspace_root, checkout_name);
    let target = checkout_root.join(repo_path);

    if target.join(".git").exists() {
        // Already materialized
        return Ok(target);
    }

    // Ensure parent directory exists
    if let Some(parent) = target.parent() {
        std::fs::create_dir_all(parent)
            .with_context(|| format!("creating checkout dir: {}", parent.display()))?;
    }

    let cache = workspace_cache::resolve_cache_path(workspace_root, repo_name, repo_url)?;
    let has_cache = workspace_cache::cache_exists(workspace_root, repo_name, repo_url)?;

    let mut cmd = Command::new("git");
    cmd.arg("clone");

    // Use cache as reference if available (fast, saves disk via hardlinks)
    if has_cache {
        cmd.args(["--reference", &cache.to_string_lossy()]);
    }

    // Optionally specify branch
    if let Some(b) = branch {
        cmd.args(["--branch", b]);
    }

    cmd.arg(repo_url).arg(&target);
    log_cmd(&cmd);

    let output = cmd
        .output()
        .with_context(|| format!("cloning {} into checkout {}", repo_name, checkout_name))?;

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        anyhow::bail!(
            "failed to clone {} into checkout {}: {}",
            repo_name,
            checkout_name,
            stderr.trim()
        );
    }

    Ok(target)
}

/// Create a full checkout with all provided repos.
///
/// `parent_manifest` supplies `settings` for the derived checkout manifest
/// (see `write_checkout_manifest`); `repos` supplies the already-resolved
/// per-repo info (url, path, revision, target, platform, ...) to materialize
/// and to carry into that derived manifest verbatim.
/// Returns info about the created checkout.
pub fn create_checkout(
    workspace_root: &Path,
    checkout_name: &str,
    parent_manifest: &Manifest,
    repos: &[RepoInfo],
    branch: Option<&str>,
) -> Result<CheckoutInfo> {
    if checkout_exists(workspace_root, checkout_name) {
        anyhow::bail!("checkout '{}' already exists", checkout_name);
    }

    let checkout_root = checkout_path(workspace_root, checkout_name);
    std::fs::create_dir_all(&checkout_root)
        .with_context(|| format!("creating checkout root: {}", checkout_root.display()))?;

    let mut checkout_repos = Vec::new();

    for repo in repos {
        let target = materialize_repo(
            workspace_root,
            checkout_name,
            &repo.name,
            &repo.url,
            &repo.path,
            branch,
        )?;
        checkout_repos.push(CheckoutRepo {
            name: repo.name.clone(),
            path: target,
            branch: branch.map(String::from),
        });
    }

    let now = chrono::Utc::now().to_rfc3339();
    let info = CheckoutInfo {
        name: checkout_name.to_string(),
        path: checkout_root.clone(),
        repos: checkout_repos,
        created_at: now,
    };

    // Write checkout metadata
    let meta_path = checkout_root.join(".checkout.json");
    let json = serde_json::to_string_pretty(&info)?;
    std::fs::write(&meta_path, json)
        .with_context(|| format!("writing checkout metadata: {}", meta_path.display()))?;

    // Write a self-contained gripspace manifest so `gr` commands run from
    // inside the checkout resolve THIS checkout as the workspace root
    // (grip#774) instead of climbing past it to the parent gripspace --
    // `load_from_workspace`'s ancestor walk only recognizes a `.gitgrip`
    // directory, which nothing wrote here before this.
    write_checkout_manifest(&checkout_root, parent_manifest, repos)?;

    Ok(info)
}

/// Derive and write a `.gitgrip/spaces/main/gripspace.yml` scoped to exactly
/// the repos materialized into this checkout, so the checkout is a
/// self-sufficient gripspace discoverable by the same ancestor walk every
/// other `gr` command already uses (no new discovery path, no special-casing
/// checkouts anywhere else in the CLI).
fn write_checkout_manifest(
    checkout_root: &Path,
    parent_manifest: &Manifest,
    repos: &[RepoInfo],
) -> Result<()> {
    let mut derived_repos: HashMap<String, RepoConfig> = HashMap::new();
    for repo in repos {
        derived_repos.insert(
            repo.name.clone(),
            RepoConfig {
                url: Some(repo.url.clone()),
                remote: None,
                path: repo.path.clone(),
                revision: Some(repo.revision.clone()),
                target: Some(repo.target.clone()),
                sync_remote: Some(repo.sync_remote.clone()),
                push_remote: Some(repo.push_remote.clone()),
                copyfile: None,
                linkfile: None,
                platform: Some(PlatformConfig {
                    platform_type: repo.platform_type,
                    base_url: repo.platform_base_url.clone(),
                }),
                reference: repo.reference,
                groups: repo.groups.clone(),
                agent: None,
                clone_strategy: None,
            },
        );
    }

    let derived_manifest = Manifest {
        version: 2,
        remotes: None,
        gripspaces: None,
        manifest: None,
        repos: derived_repos,
        settings: parent_manifest.settings.clone(),
        workspace: None,
    };

    let manifest_dir = manifest_paths::main_space_dir(checkout_root);
    std::fs::create_dir_all(&manifest_dir)
        .with_context(|| format!("creating checkout manifest dir: {}", manifest_dir.display()))?;
    let manifest_path = manifest_dir.join(manifest_paths::PRIMARY_FILE_NAME);
    let yaml = serde_yaml::to_string(&derived_manifest)
        .context("serializing derived checkout manifest")?;
    std::fs::write(&manifest_path, yaml)
        .with_context(|| format!("writing checkout manifest: {}", manifest_path.display()))?;

    Ok(())
}

/// List all checkouts under `.grip/checkouts/`.
pub fn list_checkouts(workspace_root: &Path) -> Result<Vec<CheckoutInfo>> {
    let checkouts_dir = workspace_root.join(".grip").join(CHECKOUTS_DIR);
    if !checkouts_dir.is_dir() {
        return Ok(vec![]);
    }

    let mut checkouts = Vec::new();
    for entry in std::fs::read_dir(&checkouts_dir)? {
        let entry = entry?;
        if !entry.path().is_dir() {
            continue;
        }
        let meta_path = entry.path().join(".checkout.json");
        if meta_path.is_file() {
            let content = std::fs::read_to_string(&meta_path)?;
            if let Ok(info) = serde_json::from_str::<CheckoutInfo>(&content) {
                checkouts.push(info);
            }
        } else {
            // Checkout dir exists but no metadata — construct minimal info
            let name = entry.file_name().to_string_lossy().to_string();
            checkouts.push(CheckoutInfo {
                name: name.clone(),
                path: entry.path(),
                repos: vec![],
                created_at: "unknown".to_string(),
            });
        }
    }

    Ok(checkouts)
}

/// Remove a checkout and all its contents.
pub fn remove_checkout(workspace_root: &Path, name: &str) -> Result<bool> {
    let path = checkout_path(workspace_root, name);
    if path.is_dir() {
        std::fs::remove_dir_all(&path)
            .with_context(|| format!("removing checkout: {}", path.display()))?;
        Ok(true)
    } else {
        Ok(false)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::core::manifest::ManifestSettings;
    use crate::core::workspace_cache::test_support;
    use std::fs;

    /// Build a single-repo manifest + resolved `RepoInfo`, matching the shape
    /// `setup_cached_workspace` produces (one repo named "testrepo" checked
    /// out at path "testrepo"), for tests exercising `create_checkout`'s
    /// derived-manifest path without hand-rolling every `RepoInfo` field.
    fn single_repo_manifest_and_info(
        workspace: &Path,
        name: &str,
        url: &str,
    ) -> (Manifest, Vec<RepoInfo>) {
        // parse_git_url only recognizes git@, https://, http://, and file://
        // -- setup_cached_workspace hands back a bare filesystem path, so it
        // needs the file:// scheme RepoInfo::from_config requires to resolve
        // owner/repo. materialize_repo's `git clone` accepts file:// URLs
        // the same as a bare path, so this doesn't change what gets cloned.
        let file_url = if url.contains("://") {
            url.to_string()
        } else {
            format!("file://{}", url)
        };

        let mut repos = HashMap::new();
        repos.insert(
            name.to_string(),
            RepoConfig {
                url: Some(file_url),
                remote: None,
                path: name.to_string(),
                revision: None,
                target: None,
                sync_remote: None,
                push_remote: None,
                copyfile: None,
                linkfile: None,
                platform: None,
                reference: false,
                groups: vec![],
                agent: None,
                clone_strategy: None,
            },
        );
        let manifest = Manifest {
            version: 2,
            remotes: None,
            gripspaces: None,
            manifest: None,
            repos,
            settings: ManifestSettings::default(),
            workspace: None,
        };
        let settings = manifest.settings.clone();
        let config = manifest.repos.get(name).unwrap();
        let repo_info = RepoInfo::from_config(name, config, workspace, &settings, None)
            .expect("from_config should resolve a repo with an explicit url");
        (manifest, vec![repo_info])
    }

    fn with_cache_dir<T>(cache_dir: &Path, f: impl FnOnce() -> T) -> T {
        let _guard = test_support::ENV_LOCK
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        let previous = std::env::var_os("GRIP_CACHE_DIR");
        std::env::set_var("GRIP_CACHE_DIR", cache_dir);
        let result = f();
        match previous {
            Some(value) => std::env::set_var("GRIP_CACHE_DIR", value),
            None => std::env::remove_var("GRIP_CACHE_DIR"),
        }
        result
    }

    /// Helper: create a test remote repo and bootstrap its cache
    fn setup_cached_workspace(dir: &Path) -> (PathBuf, PathBuf) {
        let remote_path = dir.join("remote-repo.git");
        let workspace = dir.join("workspace");

        // Init bare remote
        Command::new("git")
            .args(["init", "--bare"])
            .arg(&remote_path)
            .output()
            .expect("git init --bare");

        // Create work repo with a commit
        let work = dir.join("work-repo");
        Command::new("git")
            .args(["init"])
            .arg(&work)
            .output()
            .expect("git init");
        Command::new("git")
            .args(["config", "user.email", "test@test.com"])
            .current_dir(&work)
            .output()
            .expect("config email");
        Command::new("git")
            .args(["config", "user.name", "Test"])
            .current_dir(&work)
            .output()
            .expect("config name");
        fs::write(work.join("README.md"), "# test repo").expect("write");
        Command::new("git")
            .args(["add", "."])
            .current_dir(&work)
            .output()
            .expect("add");
        Command::new("git")
            .args(["commit", "-m", "initial"])
            .current_dir(&work)
            .output()
            .expect("commit");
        // Push to bare remote — try both main and master
        let _ = Command::new("git")
            .args(["remote", "add", "origin"])
            .arg(&remote_path)
            .current_dir(&work)
            .output();
        let _ = Command::new("git")
            .args(["push", "origin", "HEAD"])
            .current_dir(&work)
            .output();

        // Create workspace and bootstrap cache
        fs::create_dir_all(&workspace).expect("mkdir workspace");
        let url = remote_path.to_string_lossy().to_string();
        workspace_cache::bootstrap_cache(&workspace, "testrepo", &url).expect("bootstrap cache");

        (workspace, remote_path)
    }

    #[test]
    fn test_checkout_path() {
        let root = Path::new("/ws");
        assert_eq!(
            checkout_path(root, "mybranch"),
            PathBuf::from("/ws/.grip/checkouts/mybranch")
        );
    }

    #[test]
    fn test_checkout_does_not_exist_initially() {
        let tmp = tempfile::tempdir().expect("tempdir");
        assert!(!checkout_exists(tmp.path(), "nope"));
    }

    #[test]
    fn test_materialize_single_repo() {
        let tmp = tempfile::tempdir().expect("tempdir");
        let cache_dir = tmp.path().join("global-cache");
        with_cache_dir(&cache_dir, || {
            let (workspace, remote) = setup_cached_workspace(tmp.path());

            let url = remote.to_string_lossy().to_string();
            let target = materialize_repo(
                &workspace,
                "test-checkout",
                "testrepo",
                &url,
                "testrepo",
                None,
            )
            .expect("materialize");

            assert!(target.join(".git").exists());
            assert!(target.join("README.md").exists());
        });
    }

    #[test]
    fn test_materialize_is_independent_clone() {
        let tmp = tempfile::tempdir().expect("tempdir");
        let cache_dir = tmp.path().join("global-cache");
        with_cache_dir(&cache_dir, || {
            let (workspace, remote) = setup_cached_workspace(tmp.path());

            let url = remote.to_string_lossy().to_string();
            let target = materialize_repo(
                &workspace,
                "independent",
                "testrepo",
                &url,
                "testrepo",
                None,
            )
            .expect("materialize");

            assert!(target.join(".git").is_dir());
            assert!(!target.join(".git").is_file());
        });
    }

    #[test]
    fn test_materialize_uses_cache_reference() {
        let tmp = tempfile::tempdir().expect("tempdir");
        let cache_dir = tmp.path().join("global-cache");
        with_cache_dir(&cache_dir, || {
            let (workspace, remote) = setup_cached_workspace(tmp.path());

            let url = remote.to_string_lossy().to_string();
            let target =
                materialize_repo(&workspace, "ref-test", "testrepo", &url, "testrepo", None)
                    .expect("materialize");

            let alternates = target.join(".git/objects/info/alternates");
            assert!(alternates.is_file(), "alternates file should exist");
            let content = fs::read_to_string(&alternates).expect("read alternates");
            assert!(
                content.contains(&workspace_cache::cache_key(&url)),
                "alternates should reference the global cache path"
            );
        });
    }

    #[test]
    fn test_create_and_list_checkout() {
        let tmp = tempfile::tempdir().expect("tempdir");
        let cache_dir = tmp.path().join("global-cache");
        with_cache_dir(&cache_dir, || {
            let (workspace, remote) = setup_cached_workspace(tmp.path());

            let url = remote.to_string_lossy().to_string();
            let (manifest, repos) = single_repo_manifest_and_info(&workspace, "testrepo", &url);

            let info = create_checkout(&workspace, "feat-x", &manifest, &repos, None)
                .expect("create checkout");

            assert_eq!(info.name, "feat-x");
            assert_eq!(info.repos.len(), 1);
            assert!(checkout_exists(&workspace, "feat-x"));

            let all = list_checkouts(&workspace).expect("list");
            assert_eq!(all.len(), 1);
            assert_eq!(all[0].name, "feat-x");
        });
    }

    #[test]
    fn test_create_duplicate_fails() {
        let tmp = tempfile::tempdir().expect("tempdir");
        let cache_dir = tmp.path().join("global-cache");
        with_cache_dir(&cache_dir, || {
            let (workspace, remote) = setup_cached_workspace(tmp.path());

            let url = remote.to_string_lossy().to_string();
            let (manifest, repos) = single_repo_manifest_and_info(&workspace, "testrepo", &url);
            create_checkout(&workspace, "dup", &manifest, &repos, None).expect("first");

            let result = create_checkout(&workspace, "dup", &manifest, &repos, None);
            assert!(result.is_err());
        });
    }

    #[test]
    fn test_remove_checkout() {
        let tmp = tempfile::tempdir().expect("tempdir");
        let cache_dir = tmp.path().join("global-cache");
        with_cache_dir(&cache_dir, || {
            let (workspace, remote) = setup_cached_workspace(tmp.path());

            let url = remote.to_string_lossy().to_string();
            let (manifest, repos) = single_repo_manifest_and_info(&workspace, "testrepo", &url);
            create_checkout(&workspace, "removeme", &manifest, &repos, None).expect("create");

            assert!(checkout_exists(&workspace, "removeme"));
            let removed = remove_checkout(&workspace, "removeme").expect("remove");
            assert!(removed);
            assert!(!checkout_exists(&workspace, "removeme"));
        });
    }

    #[test]
    fn test_remove_nonexistent_returns_false() {
        let tmp = tempfile::tempdir().expect("tempdir");
        let removed = remove_checkout(tmp.path(), "nope").expect("remove");
        assert!(!removed);
    }

    #[test]
    fn test_cache_survives_checkout_removal() {
        let tmp = tempfile::tempdir().expect("tempdir");
        let cache_dir = tmp.path().join("global-cache");
        with_cache_dir(&cache_dir, || {
            let (workspace, remote) = setup_cached_workspace(tmp.path());

            let url = remote.to_string_lossy().to_string();
            let (manifest, repos) = single_repo_manifest_and_info(&workspace, "testrepo", &url);
            create_checkout(&workspace, "ephemeral", &manifest, &repos, None).expect("create");

            remove_checkout(&workspace, "ephemeral").expect("remove");

            assert!(
                workspace_cache::cache_exists(&workspace, "testrepo", &url).expect("cache exists"),
                "cache must survive checkout deletion"
            );
        });
    }

    // ── grip#774: checkout must be a self-discoverable workspace ──────────

    #[test]
    fn test_create_checkout_writes_self_contained_gripspace_manifest() {
        let tmp = tempfile::tempdir().expect("tempdir");
        let cache_dir = tmp.path().join("global-cache");
        with_cache_dir(&cache_dir, || {
            let (workspace, remote) = setup_cached_workspace(tmp.path());

            let url = remote.to_string_lossy().to_string();
            let (mut manifest, repos) = single_repo_manifest_and_info(&workspace, "testrepo", &url);
            manifest.settings.pr_prefix = "[from-parent]".to_string();

            create_checkout(&workspace, "self-contained", &manifest, &repos, None)
                .expect("create checkout");

            let checkout_root = checkout_path(&workspace, "self-contained");

            // This is the exact marker `load_from_workspace`'s ancestor walk
            // looks for (dispatch.rs) -- before this fix, nothing wrote it,
            // so the walk climbed straight past the checkout to the parent.
            let gitgrip_dir = checkout_root.join(".gitgrip");
            assert!(
                gitgrip_dir.is_dir(),
                "checkout root must contain a .gitgrip marker so gr commands \
                 discover the checkout itself, not the parent workspace"
            );

            let manifest_path = manifest_paths::default_gripspace_manifest_path(&checkout_root);
            assert!(
                manifest_path.is_file(),
                "expected a gripspace manifest at {}",
                manifest_path.display()
            );

            let content = fs::read_to_string(&manifest_path).expect("read derived manifest");
            let derived = crate::core::manifest::Manifest::parse(&content)
                .expect("derived checkout manifest should parse");

            assert_eq!(
                derived.repos.len(),
                1,
                "derived manifest should carry exactly the repos materialized into this checkout"
            );
            let repo_config = derived.repos.get("testrepo").expect("testrepo entry");
            assert_eq!(
                repo_config.url.as_deref(),
                Some(format!("file://{}", url).as_str()),
                "derived repo url must match the resolved (file://-scheme) url used to \
                 materialize the repo"
            );
            assert_eq!(
                repo_config.path, "testrepo",
                "derived repo path must be relative to the checkout root, matching \
                 where materialize_repo actually cloned it"
            );
            assert_eq!(
                derived.settings.pr_prefix, "[from-parent]",
                "derived manifest must carry the parent's settings, not gitgrip's built-in default"
            );
        });
    }

    #[test]
    fn test_checkout_gripspace_manifest_is_independently_discoverable() {
        let tmp = tempfile::tempdir().expect("tempdir");
        let cache_dir = tmp.path().join("global-cache");
        with_cache_dir(&cache_dir, || {
            let (workspace, remote) = setup_cached_workspace(tmp.path());

            let url = remote.to_string_lossy().to_string();
            let (manifest, repos) = single_repo_manifest_and_info(&workspace, "testrepo", &url);
            create_checkout(&workspace, "discoverable", &manifest, &repos, None)
                .expect("create checkout");

            let checkout_root = checkout_path(&workspace, "discoverable");
            let repo_dir = checkout_root.join("testrepo");
            assert!(repo_dir.is_dir(), "materialized repo dir must exist");

            // Mirrors dispatch.rs's `load_from_workspace` ancestor walk directly
            // (that function is private to the CLI crate): starting from a repo
            // *inside* the checkout, the nearest `.gitgrip` ancestor must be the
            // checkout root, not the parent workspace root two levels up.
            let mut search = repo_dir.as_path();
            let found_root = loop {
                if search.join(".gitgrip").exists() {
                    break Some(search.to_path_buf());
                }
                match search.parent() {
                    Some(parent) => search = parent,
                    None => break None,
                }
            };

            assert_eq!(
                found_root,
                Some(checkout_root.clone()),
                "the nearest .gitgrip ancestor from inside the checkout's repo must be \
                 the checkout root ({}), not the parent workspace ({})",
                checkout_root.display(),
                workspace.display()
            );
        });
    }
}
