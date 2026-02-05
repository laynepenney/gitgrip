//! Manifest operations (import, sync)
//!
//! Handles conversion between git-repo XML manifests and gitgrip YAML manifests.

use crate::cli::output::Output;
use crate::core::repo_manifest::XmlManifest;
use std::path::Path;

/// Import a git-repo XML manifest and convert to gitgrip YAML
pub fn run_manifest_import(path: &str, output_path: Option<&str>) -> anyhow::Result<()> {
    let xml_path = Path::new(path);
    if !xml_path.exists() {
        anyhow::bail!("XML manifest not found: {}", path);
    }

    Output::header("Importing git-repo manifest...");
    println!();

    let xml_manifest = XmlManifest::parse_file(xml_path)?;
    let result = xml_manifest.to_manifest()?;

    // Print summary
    Output::info(&format!(
        "{} total projects, {} Gerrit (skipped), {} non-Gerrit (imported)",
        result.total_projects, result.gerrit_skipped, result.non_gerrit_imported
    ));

    for (platform, count) in &result.platform_counts {
        Output::info(&format!("  {}: {} repos", platform, count));
    }

    // Serialize to YAML
    let yaml = serde_yaml::to_string(&result.manifest)?;

    // Write output
    let dest = output_path.unwrap_or("manifest.yaml");
    std::fs::write(dest, &yaml)?;

    println!();
    Output::success(&format!("Written: {}", dest));

    Ok(())
}

/// Re-sync gitgrip YAML from .repo/ manifest XML
pub fn run_manifest_sync(workspace_root: &std::path::PathBuf) -> anyhow::Result<()> {
    // Find the XML manifest
    let repo_dir = workspace_root.join(".repo");
    let xml_path = repo_dir.join("manifest.xml");

    if !xml_path.exists() {
        anyhow::bail!("No .repo/manifest.xml found. Are you in a repo-managed workspace?");
    }

    Output::header("Syncing manifest from .repo/...");
    println!();

    let xml_manifest = XmlManifest::parse_file(&xml_path)?;
    let result = xml_manifest.to_manifest()?;

    Output::info(&format!(
        "{} total projects, {} Gerrit (skipped), {} non-Gerrit (imported)",
        result.total_projects, result.gerrit_skipped, result.non_gerrit_imported
    ));

    // Write to .repo/manifests/manifest.yaml
    let yaml = serde_yaml::to_string(&result.manifest)?;
    let manifests_dir = repo_dir.join("manifests");
    let yaml_path = manifests_dir.join("manifest.yaml");
    std::fs::write(&yaml_path, &yaml)?;

    println!();
    Output::success(&format!("Updated: {}", yaml_path.display()));

    Ok(())
}
