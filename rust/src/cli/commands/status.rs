//! Status command implementation

use crate::cli::output::{Output, Table};
use crate::core::manifest::Manifest;
use crate::core::repo::RepoInfo;
use crate::git::status::{get_repo_status, RepoStatus};
use std::path::PathBuf;

/// Run the status command
pub fn run_status(workspace_root: &PathBuf, manifest: &Manifest, verbose: bool) -> anyhow::Result<()> {
    Output::header("Repository Status");
    println!();

    // Get all repo info
    let repos: Vec<RepoInfo> = manifest
        .repos
        .iter()
        .filter_map(|(name, config)| RepoInfo::from_config(name, config, workspace_root))
        .collect();

    // Get status for all repos
    let statuses: Vec<RepoStatus> = repos.iter().map(get_repo_status).collect();

    // Count stats
    let total = statuses.len();
    let cloned = statuses.iter().filter(|s| s.exists).count();
    let with_changes = statuses.iter().filter(|s| !s.clean).count();

    // Display table
    let mut table = Table::new(vec!["Repo", "Branch", "Status"]);

    for status in &statuses {
        let status_str = format_status(status, verbose);
        table.add_row(vec![
            &Output::repo_name(&status.name),
            &Output::branch_name(&status.branch),
            &status_str,
        ]);
    }

    table.print();

    // Summary
    println!();
    println!(
        "  {}/{} cloned | {} with changes",
        cloned, total, with_changes
    );

    Ok(())
}

/// Format status for display
fn format_status(status: &RepoStatus, verbose: bool) -> String {
    if !status.exists {
        return "not cloned".to_string();
    }

    if status.clean {
        return "✓".to_string();
    }

    let mut parts = Vec::new();

    if status.staged > 0 {
        parts.push(format!("+{}", status.staged));
    }
    if status.modified > 0 {
        parts.push(format!("~{}", status.modified));
    }
    if status.untracked > 0 {
        parts.push(format!("?{}", status.untracked));
    }

    if verbose {
        if status.ahead > 0 {
            parts.push(format!("↑{}", status.ahead));
        }
        if status.behind > 0 {
            parts.push(format!("↓{}", status.behind));
        }
    }

    parts.join(" ")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_format_status_clean() {
        let status = RepoStatus {
            name: "test".to_string(),
            branch: "main".to_string(),
            clean: true,
            staged: 0,
            modified: 0,
            untracked: 0,
            ahead: 0,
            behind: 0,
            exists: true,
        };
        assert_eq!(format_status(&status, false), "✓");
    }

    #[test]
    fn test_format_status_changes() {
        let status = RepoStatus {
            name: "test".to_string(),
            branch: "main".to_string(),
            clean: false,
            staged: 2,
            modified: 3,
            untracked: 1,
            ahead: 0,
            behind: 0,
            exists: true,
        };
        assert_eq!(format_status(&status, false), "+2 ~3 ?1");
    }

    #[test]
    fn test_format_status_ahead_behind() {
        let status = RepoStatus {
            name: "test".to_string(),
            branch: "feat".to_string(),
            clean: false,
            staged: 1,
            modified: 0,
            untracked: 0,
            ahead: 3,
            behind: 1,
            exists: true,
        };
        assert_eq!(format_status(&status, true), "+1 ↑3 ↓1");
    }
}
