//! Hosting platform adapters
//!
//! Provides a unified interface for GitHub, GitLab, and Azure DevOps.

pub mod types;

// Platform adapters will be added in Phase 3
// pub mod github;
// pub mod gitlab;
// pub mod azure;

pub use types::*;
