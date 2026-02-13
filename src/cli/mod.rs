//! CLI layer
//!
//! Command-line interface using clap.

pub mod commands;
pub mod context;
pub mod output;
pub mod repo_iter;

pub use context::WorkspaceContext;
pub use output::Output;
