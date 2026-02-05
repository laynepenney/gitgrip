//! Command logging utilities for verbose output.

use std::process::Command;
use tracing::debug;

/// Log a command just before execution.
///
/// Emits a `tracing::debug!` event with the program name, arguments, and
/// working directory. Visible when running with `--verbose` (which sets
/// `gitgrip=debug`) or via `RUST_LOG=gitgrip::util::cmd=debug`.
pub fn log_cmd(cmd: &Command) {
    let program = cmd.get_program().to_string_lossy();
    let args: Vec<_> = cmd.get_args().map(|a| a.to_string_lossy()).collect();
    let cwd = cmd
        .get_current_dir()
        .map(|p| p.display().to_string())
        .unwrap_or_default();
    debug!(
        target: "gitgrip::cmd",
        %program,
        ?args,
        %cwd,
        "exec"
    );
}
