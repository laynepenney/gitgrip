//! Status command implementation

use crate::cli::output::{Output, Table};
use crate::core::manifest::Manifest;
use crate::core::repo::RepoInfo;
use crate::git::status::{get_repo_status, RepoStatus};
use std::path::PathBuf;

/// Run the status command
pub fn run_status(
    workspace_root: &PathBuf,
    manifest: &Manifest,
    verbose: bool,
) -> anyhow::Result<()> {
    Output::header("Repository Status");
    println!();

    // Get all repo info
    let repos: Vec<RepoInfo> = manifest
        .repos
        .iter()
        .filter_map(|(name, config)| RepoInfo::from_config(name, config, workspace_root))
        .collect();

    // Get status for all repos
    let statuses: Vec<(RepoStatus, &RepoInfo)> = repos
        .iter()
        .map(|repo| (get_repo_status(repo), repo))
        .collect();

    // Count stats
    let total = statuses.len();
    let cloned = statuses.iter().filter(|(s, _)| s.exists).count();
    let with_changes = statuses.iter().filter(|(s, _)| !s.clean).count();
    let ahead_count = statuses.iter().filter(|(s, _)| s.ahead_main > 0).count();

    // Display table
    let mut table = Table::new(vec!["Repo", "Branch", "Status", "vs main"]);

    for (status, repo) in &statuses {
        let status_str = format_status(status, verbose);
        let main_str = format_main_comparison(status, &repo.default_branch);
        table.add_row(vec![
            &Output::repo_name(&status.name),
            &Output::branch_name(&status.branch),
            &status_str,
            &main_str,
        ]);
    }

    table.print();

    // Summary
    println!();
    let ahead_suffix = if ahead_count > 0 {
        format!(" | {} ahead of main", ahead_count)
    } else {
        String::new()
    };
    println!(
        "  {}/{} cloned | {} with changes{}",
        cloned, total, with_changes, ahead_suffix
    );

    Ok(())
}

/// Format the vs main comparison column
fn format_main_comparison(status: &RepoStatus, default_branch: &str) -> String {
    // On default branch - no comparison needed
    if status.branch == default_branch {
        return "-".to_string();
    }

    if status.ahead_main == 0 && status.behind_main == 0 {
        return "\u{2713}".to_string(); // checkmark
    }

    let mut parts = Vec::new();
    if status.ahead_main > 0 {
        parts.push(format!("\u{2191}{}", status.ahead_main)); // up arrow
    }
    if status.behind_main > 0 {
        parts.push(format!("\u{2193}{}", status.behind_main)); // down arrow
    }
    parts.join(" ")
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
            ahead_main: 0,
            behind_main: 0,
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
            ahead_main: 0,
            behind_main: 0,
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
            ahead_main: 0,
            behind_main: 0,
            exists: true,
        };
        assert_eq!(format_status(&status, true), "+1 ↑3 ↓1");
    }

    #[test]
    fn test_format_main_comparison_on_main() {
        let status = RepoStatus {
            name: "test".to_string(),
            branch: "main".to_string(),
            clean: true,
            staged: 0,
            modified: 0,
            untracked: 0,
            ahead: 0,
            behind: 0,
            ahead_main: 0,
            behind_main: 0,
            exists: true,
        };
        assert_eq!(format_main_comparison(&status, "main"), "-");
    }

    #[test]
    fn test_format_main_comparison_ahead() {
        let status = RepoStatus {
            name: "test".to_string(),
            branch: "feat/test".to_string(),
            clean: true,
            staged: 0,
            modified: 0,
            untracked: 0,
            ahead: 0,
            behind: 0,
            ahead_main: 5,
            behind_main: 0,
            exists: true,
        };
        assert_eq!(format_main_comparison(&status, "main"), "↑5");
    }

    #[test]
    fn test_format_main_comparison_behind() {
        let status = RepoStatus {
            name: "test".to_string(),
            branch: "feat/test".to_string(),
            clean: true,
            staged: 0,
            modified: 0,
            untracked: 0,
            ahead: 0,
            behind: 0,
            ahead_main: 0,
            behind_main: 3,
            exists: true,
        };
        assert_eq!(format_main_comparison(&status, "main"), "↓3");
    }

    #[test]
    fn test_format_main_comparison_both() {
        let status = RepoStatus {
            name: "test".to_string(),
            branch: "feat/test".to_string(),
            clean: true,
            staged: 0,
            modified: 0,
            untracked: 0,
            ahead: 0,
            behind: 0,
            ahead_main: 2,
            behind_main: 5,
            exists: true,
        };
        assert_eq!(format_main_comparison(&status, "main"), "↑2 ↓5");
    }

    #[test]
    fn test_format_main_comparison_in_sync() {
        let status = RepoStatus {
            name: "test".to_string(),
            branch: "feat/test".to_string(),
            clean: true,
            staged: 0,
            modified: 0,
            untracked: 0,
            ahead: 0,
            behind: 0,
            ahead_main: 0,
            behind_main: 0,
            exists: true,
        };
        assert_eq!(format_main_comparison(&status, "main"), "✓");
    }
}
