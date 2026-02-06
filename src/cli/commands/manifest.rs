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

/// Show manifest schema specification
pub fn run_manifest_schema(format: &str) -> anyhow::Result<()> {
    let schema = include_str!("../../../docs/manifest-schema.yaml");

    match format {
        "yaml" => {
            println!("{}", schema);
        }
        "json" => {
            // Parse YAML and convert to JSON
            let value: serde_yaml::Value = serde_yaml::from_str(schema)?;
            let json = serde_json::to_string_pretty(&value)?;
            println!("{}", json);
        }
        "markdown" | "md" => {
            print_schema_markdown();
        }
        _ => {
            anyhow::bail!("Unknown format: {}. Use yaml, json, or markdown.", format);
        }
    }

    Ok(())
}

/// Print schema as markdown documentation
fn print_schema_markdown() {
    println!(
        r#"# gitgrip Manifest Schema

## Overview

The manifest file (`manifest.yaml`) defines a multi-repository workspace configuration.
It is typically located at `.gitgrip/manifests/manifest.yaml`.

## Top-Level Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `version` | integer | Yes | Schema version (currently `1`) |
| `manifest` | object | No | Self-tracking manifest repo config |
| `repos` | object | Yes | Repository definitions |
| `settings` | object | No | Global workspace settings |
| `workspace` | object | No | Scripts, hooks, and environment |

## Repository Configuration

Each repository under `repos` supports:

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `url` | string | - | Git URL (SSH or HTTPS) |
| `path` | string | - | Local path relative to workspace |
| `default_branch` | string | `main` | Default branch name |
| `groups` | array | `[]` | Groups for selective operations |
| `reference` | boolean | `false` | Read-only reference repo |
| `copyfile` | array | - | Files to copy to workspace |
| `linkfile` | array | - | Symlinks to create |
| `platform` | object | auto | Platform type and base URL |

## Settings

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `pr_prefix` | string | `[cross-repo]` | Prefix for PR titles |
| `merge_strategy` | string | `all-or-nothing` | `all-or-nothing` or `independent` |

## Platform Types

- `github` - GitHub.com or GitHub Enterprise
- `gitlab` - GitLab.com or self-hosted
- `azure-devops` - Azure DevOps or Azure DevOps Server
- `bitbucket` - Bitbucket Cloud or Server

## Example

```yaml
version: 1

manifest:
  url: git@github.com:org/manifest.git
  default_branch: main

repos:
  frontend:
    url: git@github.com:org/frontend.git
    path: ./frontend
    groups: [core, web]

  backend:
    url: git@github.com:org/backend.git
    path: ./backend
    groups: [core, api]

settings:
  pr_prefix: "[multi-repo]"
  merge_strategy: all-or-nothing

workspace:
  scripts:
    build:
      command: "npm run build"
```
"#
    );
}
