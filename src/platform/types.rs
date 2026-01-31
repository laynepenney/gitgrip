//! Shared types for hosting platforms

use serde::{Deserialize, Serialize};

pub use crate::core::manifest::PlatformType;

/// Pull request state
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, Default)]
#[serde(rename_all = "lowercase")]
pub enum PRState {
    #[default]
    Open,
    Closed,
    Merged,
}

impl std::fmt::Display for PRState {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            PRState::Open => write!(f, "open"),
            PRState::Closed => write!(f, "closed"),
            PRState::Merged => write!(f, "merged"),
        }
    }
}

/// PR head reference information
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PRHead {
    /// Branch reference name
    #[serde(rename = "ref")]
    pub ref_name: String,
    /// Commit SHA
    pub sha: String,
}

/// PR base reference information
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PRBase {
    /// Branch reference name
    #[serde(rename = "ref")]
    pub ref_name: String,
}

/// Normalized pull request data across platforms
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PullRequest {
    /// PR number
    pub number: u64,
    /// PR URL
    pub url: String,
    /// PR title
    pub title: String,
    /// PR body/description
    pub body: String,
    /// PR state
    pub state: PRState,
    /// Whether the PR has been merged
    pub merged: bool,
    /// Whether the PR can be merged (null if unknown)
    pub mergeable: Option<bool>,
    /// Head branch info
    pub head: PRHead,
    /// Base branch info
    pub base: PRBase,
}

/// Options for creating a PR
#[derive(Debug, Clone, Default)]
pub struct PRCreateOptions {
    /// PR title
    pub title: String,
    /// PR body/description
    pub body: Option<String>,
    /// Base branch (target)
    pub base: Option<String>,
    /// Create as draft PR
    pub draft: Option<bool>,
}

/// Merge method for PRs
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub enum MergeMethod {
    #[default]
    Merge,
    Squash,
    Rebase,
}

impl std::fmt::Display for MergeMethod {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            MergeMethod::Merge => write!(f, "merge"),
            MergeMethod::Squash => write!(f, "squash"),
            MergeMethod::Rebase => write!(f, "rebase"),
        }
    }
}

/// Options for merging a PR
#[derive(Debug, Clone, Default)]
pub struct PRMergeOptions {
    /// Merge method
    pub method: Option<MergeMethod>,
    /// Delete branch after merge
    pub delete_branch: Option<bool>,
}

/// Result of creating a PR
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PRCreateResult {
    /// PR number
    pub number: u64,
    /// PR URL
    pub url: String,
}

/// PR review information
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PRReview {
    /// Review state (e.g., "APPROVED", "CHANGES_REQUESTED")
    pub state: String,
    /// Reviewer username
    pub user: String,
}

/// Status check state
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, Default)]
#[serde(rename_all = "lowercase")]
pub enum CheckState {
    #[default]
    Pending,
    Success,
    Failure,
}

impl std::fmt::Display for CheckState {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            CheckState::Pending => write!(f, "pending"),
            CheckState::Success => write!(f, "success"),
            CheckState::Failure => write!(f, "failure"),
        }
    }
}

/// Individual status check
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct StatusCheck {
    /// Check context/name
    pub context: String,
    /// Check state
    pub state: String,
}

/// Combined status check result
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct StatusCheckResult {
    /// Overall state
    pub state: CheckState,
    /// Individual statuses
    pub statuses: Vec<StatusCheck>,
}

/// Detailed check status information
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CheckStatusDetails {
    /// Overall state
    pub state: CheckState,
    /// Number of passed checks
    pub passed: u32,
    /// Number of failed checks
    pub failed: u32,
    /// Number of pending checks
    pub pending: u32,
    /// Number of skipped checks
    pub skipped: u32,
    /// Total number of checks
    pub total: u32,
}

/// Allowed merge methods for a repository
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AllowedMergeMethods {
    /// Allow merge commits
    pub merge: bool,
    /// Allow squash merges
    pub squash: bool,
    /// Allow rebase merges
    pub rebase: bool,
}

impl Default for AllowedMergeMethods {
    fn default() -> Self {
        Self {
            merge: true,
            squash: true,
            rebase: true,
        }
    }
}

/// Parsed repository information from URL
#[derive(Debug, Clone)]
pub struct ParsedRepoInfo {
    /// Owner/namespace
    pub owner: String,
    /// Repository name
    pub repo: String,
    /// Project name (Azure DevOps only)
    pub project: Option<String>,
    /// Detected platform type
    pub platform: Option<PlatformType>,
}

/// Azure DevOps specific context
#[derive(Debug, Clone)]
pub struct AzureDevOpsContext {
    /// Organization name
    pub organization: String,
    /// Project name
    pub project: String,
    /// Repository name
    pub repository: String,
}
