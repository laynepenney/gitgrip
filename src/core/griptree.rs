//! Griptree (worktree) management
//!
//! Griptrees are isolated parallel workspaces for different branches.

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use std::path::PathBuf;
use thiserror::Error;

/// Errors that can occur with griptree operations
#[derive(Error, Debug)]
pub enum GriptreeError {
    #[error("Failed to read griptree config: {0}")]
    IoError(#[from] std::io::Error),

    #[error("Failed to parse griptree config: {0}")]
    ParseError(#[from] serde_json::Error),

    #[error("Griptree is locked: {0}")]
    Locked(String),

    #[error("Griptree not found: {0}")]
    NotFound(String),
}

/// Griptree status
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum GriptreeStatus {
    /// Active and in use
    Active,
    /// Branch was deleted, griptree is orphaned
    Orphan,
    /// Legacy griptree (pre-config format)
    Legacy,
}

/// Griptree configuration (stored in .gitgrip/griptrees/<branch>/config.json)
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct GriptreeConfig {
    /// Branch name this griptree is for
    pub branch: String,
    /// Absolute path to griptree directory
    pub path: String,
    /// ISO timestamp when created
    pub created_at: DateTime<Utc>,
    /// User who created it
    #[serde(skip_serializing_if = "Option::is_none")]
    pub created_by: Option<String>,
    /// Prevents accidental removal
    #[serde(default)]
    pub locked: bool,
    /// ISO timestamp when locked
    #[serde(skip_serializing_if = "Option::is_none")]
    pub locked_at: Option<DateTime<Utc>>,
    /// Reason for locking
    #[serde(skip_serializing_if = "Option::is_none")]
    pub locked_reason: Option<String>,
}

impl GriptreeConfig {
    /// Create a new griptree config
    pub fn new(branch: &str, path: &str) -> Self {
        Self {
            branch: branch.to_string(),
            path: path.to_string(),
            created_at: Utc::now(),
            created_by: std::env::var("USER").ok(),
            locked: false,
            locked_at: None,
            locked_reason: None,
        }
    }

    /// Load config from a file
    pub fn load(path: &PathBuf) -> Result<Self, GriptreeError> {
        let content = std::fs::read_to_string(path)?;
        let config: GriptreeConfig = serde_json::from_str(&content)?;
        Ok(config)
    }

    /// Save config to a file
    pub fn save(&self, path: &PathBuf) -> Result<(), GriptreeError> {
        let json = serde_json::to_string_pretty(self)?;
        if let Some(parent) = path.parent() {
            std::fs::create_dir_all(parent)?;
        }
        std::fs::write(path, json)?;
        Ok(())
    }

    /// Lock the griptree
    pub fn lock(&mut self, reason: Option<&str>) {
        self.locked = true;
        self.locked_at = Some(Utc::now());
        self.locked_reason = reason.map(|s| s.to_string());
    }

    /// Unlock the griptree
    pub fn unlock(&mut self) {
        self.locked = false;
        self.locked_at = None;
        self.locked_reason = None;
    }
}

/// Pointer file stored in the griptree directory (.griptree)
/// This file indicates that the current directory is a griptree and points
/// back to the main workspace.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct GriptreePointer {
    /// Absolute path to main workspace
    pub main_workspace: String,
    /// Branch name
    pub branch: String,
    /// Whether the griptree is locked (optional for backwards compat)
    #[serde(default)]
    pub locked: bool,
    /// When the griptree was created (optional for backwards compat)
    #[serde(skip_serializing_if = "Option::is_none")]
    pub created_at: Option<DateTime<Utc>>,
}

impl GriptreePointer {
    /// Load pointer from a .griptree file
    pub fn load(path: &std::path::Path) -> Result<Self, GriptreeError> {
        let content = std::fs::read_to_string(path)?;
        let pointer: GriptreePointer = serde_json::from_str(&content)?;
        Ok(pointer)
    }

    /// Find a .griptree pointer file by searching current and parent directories
    pub fn find_in_ancestors(start: &std::path::Path) -> Option<(std::path::PathBuf, Self)> {
        let mut current = start.to_path_buf();
        loop {
            let pointer_path = current.join(".griptree");
            if pointer_path.exists() {
                if let Ok(pointer) = Self::load(&pointer_path) {
                    return Some((current, pointer));
                }
            }

            match current.parent() {
                Some(parent) => current = parent.to_path_buf(),
                None => return None,
            }
        }
    }
}

/// Per-repo worktree info
#[derive(Debug, Clone)]
pub struct TreeRepoInfo {
    /// Repository name
    pub name: String,
    /// Worktree path
    pub path: PathBuf,
    /// Branch name
    pub branch: String,
    /// Worktree exists
    pub exists: bool,
}

/// Full griptree information
#[derive(Debug, Clone)]
pub struct TreeInfo {
    /// Branch name
    pub branch: String,
    /// Griptree path
    pub path: PathBuf,
    /// Whether it's locked
    pub locked: bool,
    /// Per-repo worktree info
    pub repos: Vec<TreeRepoInfo>,
    /// Griptree status
    pub status: Option<GriptreeStatus>,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_new_griptree_config() {
        let config = GriptreeConfig::new("feat/test", "/path/to/griptree");
        assert_eq!(config.branch, "feat/test");
        assert_eq!(config.path, "/path/to/griptree");
        assert!(!config.locked);
    }

    #[test]
    fn test_lock_unlock() {
        let mut config = GriptreeConfig::new("feat/test", "/path");

        config.lock(Some("Important work in progress"));
        assert!(config.locked);
        assert!(config.locked_at.is_some());
        assert_eq!(
            config.locked_reason,
            Some("Important work in progress".to_string())
        );

        config.unlock();
        assert!(!config.locked);
        assert!(config.locked_at.is_none());
        assert!(config.locked_reason.is_none());
    }

    #[test]
    fn test_serialize_griptree_config() {
        let config = GriptreeConfig::new("main", "/workspace");
        let json = serde_json::to_string(&config).unwrap();
        assert!(json.contains("\"branch\":\"main\""));
    }
}
