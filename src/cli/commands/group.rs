//! Group command implementation
//!
//! Lists, adds, and removes repositories from groups.

use crate::cli::output::Output;
use crate::core::manifest::Manifest;
use crate::core::repo::RepoInfo;
use std::collections::BTreeMap;
use std::path::PathBuf;

/// Run the group list command
pub fn run_group_list(workspace_root: &PathBuf, manifest: &Manifest) -> anyhow::Result<()> {
    Output::header("Repository Groups");
    println!();

    let repos: Vec<RepoInfo> = manifest
        .repos
        .iter()
        .filter_map(|(name, config)| RepoInfo::from_config(name, config, workspace_root))
        .collect();

    // Collect groups -> repos mapping
    let mut groups: BTreeMap<String, Vec<String>> = BTreeMap::new();
    let mut ungrouped: Vec<String> = Vec::new();

    for repo in &repos {
        if repo.groups.is_empty() {
            ungrouped.push(repo.name.clone());
        } else {
            for group in &repo.groups {
                groups
                    .entry(group.clone())
                    .or_default()
                    .push(repo.name.clone());
            }
        }
    }

    if groups.is_empty() && ungrouped.is_empty() {
        Output::info("No repositories found.");
        return Ok(());
    }

    if groups.is_empty() {
        Output::info("No groups defined. Add 'groups' to repos in the manifest.");
        println!();
    }

    for (group_name, mut members) in groups {
        members.sort();
        println!("  {} ({})", Output::repo_name(&group_name), members.len());
        for member in &members {
            println!("    {}", member);
        }
        println!();
    }

    if !ungrouped.is_empty() {
        ungrouped.sort();
        println!("  ungrouped ({})", ungrouped.len());
        for member in &ungrouped {
            println!("    {}", member);
        }
        println!();
    }

    Ok(())
}

/// Add repositories to a group
pub fn run_group_add(
    workspace_root: &PathBuf,
    group: &str,
    repos: &[String],
) -> anyhow::Result<()> {
    let manifest_path = find_manifest_path(workspace_root)?;

    // Load the raw YAML to preserve formatting
    let content = std::fs::read_to_string(&manifest_path)?;
    let mut manifest: serde_yaml::Value = serde_yaml::from_str(&content)?;

    let repos_section = manifest
        .get_mut("repos")
        .ok_or_else(|| anyhow::anyhow!("No 'repos' section found in manifest"))?
        .as_mapping_mut()
        .ok_or_else(|| anyhow::anyhow!("'repos' is not a mapping"))?;

    let mut added_count = 0;
    let mut already_count = 0;

    for repo_name in repos {
        if let Some(repo) = repos_section.get_mut(serde_yaml::Value::String(repo_name.clone())) {
            let repo_map = repo
                .as_mapping_mut()
                .ok_or_else(|| anyhow::anyhow!("Repository '{}' is not a mapping", repo_name))?;

            // Get or create groups array
            let groups_key = serde_yaml::Value::String("groups".to_string());
            let groups = repo_map
                .entry(groups_key.clone())
                .or_insert_with(|| serde_yaml::Value::Sequence(vec![]));

            let groups_seq = groups
                .as_sequence_mut()
                .ok_or_else(|| anyhow::anyhow!("'groups' is not an array in '{}'", repo_name))?;

            let group_value = serde_yaml::Value::String(group.to_string());
            if groups_seq.contains(&group_value) {
                Output::info(&format!("{}: already in group '{}'", repo_name, group));
                already_count += 1;
            } else {
                groups_seq.push(group_value);
                Output::success(&format!("{}: added to group '{}'", repo_name, group));
                added_count += 1;
            }
        } else {
            Output::error(&format!("Repository '{}' not found in manifest", repo_name));
        }
    }

    // Write back
    let yaml = serde_yaml::to_string(&manifest)?;
    std::fs::write(&manifest_path, yaml)?;

    println!();
    if added_count > 0 {
        Output::success(&format!(
            "Added {} repo(s) to group '{}' (updated: {})",
            added_count,
            group,
            manifest_path.display()
        ));
    }
    if already_count > 0 && added_count == 0 {
        Output::info(&format!("All repos already in group '{}'", group));
    }

    Ok(())
}

/// Remove repositories from a group
pub fn run_group_remove(
    workspace_root: &PathBuf,
    group: &str,
    repos: &[String],
) -> anyhow::Result<()> {
    let manifest_path = find_manifest_path(workspace_root)?;

    // Load the raw YAML to preserve formatting
    let content = std::fs::read_to_string(&manifest_path)?;
    let mut manifest: serde_yaml::Value = serde_yaml::from_str(&content)?;

    let repos_section = manifest
        .get_mut("repos")
        .ok_or_else(|| anyhow::anyhow!("No 'repos' section found in manifest"))?
        .as_mapping_mut()
        .ok_or_else(|| anyhow::anyhow!("'repos' is not a mapping"))?;

    let mut removed_count = 0;
    let mut not_in_count = 0;

    for repo_name in repos {
        if let Some(repo) = repos_section.get_mut(serde_yaml::Value::String(repo_name.clone())) {
            let repo_map = repo
                .as_mapping_mut()
                .ok_or_else(|| anyhow::anyhow!("Repository '{}' is not a mapping", repo_name))?;

            let groups_key = serde_yaml::Value::String("groups".to_string());
            if let Some(groups) = repo_map.get_mut(&groups_key) {
                if let Some(groups_seq) = groups.as_sequence_mut() {
                    let group_value = serde_yaml::Value::String(group.to_string());
                    let original_len = groups_seq.len();
                    groups_seq.retain(|v| v != &group_value);

                    if groups_seq.len() < original_len {
                        Output::success(&format!("{}: removed from group '{}'", repo_name, group));
                        removed_count += 1;

                        // Remove empty groups array
                        if groups_seq.is_empty() {
                            repo_map.remove(&groups_key);
                        }
                    } else {
                        Output::info(&format!("{}: not in group '{}'", repo_name, group));
                        not_in_count += 1;
                    }
                } else {
                    Output::info(&format!("{}: not in group '{}'", repo_name, group));
                    not_in_count += 1;
                }
            } else {
                Output::info(&format!("{}: has no groups", repo_name));
                not_in_count += 1;
            }
        } else {
            Output::error(&format!("Repository '{}' not found in manifest", repo_name));
        }
    }

    // Write back
    let yaml = serde_yaml::to_string(&manifest)?;
    std::fs::write(&manifest_path, yaml)?;

    println!();
    if removed_count > 0 {
        Output::success(&format!(
            "Removed {} repo(s) from group '{}' (updated: {})",
            removed_count,
            group,
            manifest_path.display()
        ));
    }
    if not_in_count > 0 && removed_count == 0 {
        Output::info(&format!("No repos were in group '{}'", group));
    }

    Ok(())
}

/// Create a new group (informational - groups are created by adding repos)
pub fn run_group_create(_workspace_root: &PathBuf, name: &str) -> anyhow::Result<()> {
    Output::info("Groups are created implicitly when you add repos to them.");
    println!();
    Output::info(&format!(
        "To create group '{}', run: gr group add {} <repo-name>",
        name, name
    ));

    Ok(())
}

/// Find the manifest.yaml path
fn find_manifest_path(workspace_root: &PathBuf) -> anyhow::Result<PathBuf> {
    // Check .gitgrip/manifests/manifest.yaml first
    let gitgrip_path = workspace_root
        .join(".gitgrip")
        .join("manifests")
        .join("manifest.yaml");

    if gitgrip_path.exists() {
        return Ok(gitgrip_path);
    }

    // Check .repo/manifests/manifest.yaml
    let repo_path = workspace_root
        .join(".repo")
        .join("manifests")
        .join("manifest.yaml");

    if repo_path.exists() {
        return Ok(repo_path);
    }

    anyhow::bail!(
        "No manifest.yaml found. Expected at:\n  {}\n  {}",
        gitgrip_path.display(),
        repo_path.display()
    )
}
