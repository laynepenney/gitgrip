//! Env command implementation
//!
//! Displays workspace environment variables.

use crate::cli::output::Output;
use crate::core::manifest::Manifest;
use std::path::PathBuf;

/// Run the env command
pub fn run_env(workspace_root: &PathBuf, manifest: &Manifest) -> anyhow::Result<()> {
    Output::header("Workspace Environment");
    println!();

    // Built-in environment variables
    println!("  GITGRIP_WORKSPACE={}", workspace_root.display());
    println!(
        "  GITGRIP_MANIFEST={}",
        workspace_root
            .join(".gitgrip/manifests/manifest.yaml")
            .display()
    );

    // Workspace-defined environment variables
    if let Some(ref workspace) = manifest.workspace {
        if let Some(ref env_vars) = workspace.env {
            println!();
            println!("Workspace variables:");
            for (key, value) in env_vars {
                println!("  {}={}", key, value);
            }
        }
    }

    Ok(())
}
