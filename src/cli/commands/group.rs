//! Group command implementation
//!
//! Lists all defined groups and their member repositories.

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
