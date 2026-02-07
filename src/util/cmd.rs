//! Command logging utilities for verbose output.

use once_cell::sync::Lazy;
use regex::Regex;
use std::borrow::Cow;
use std::process::Command;
use tracing::debug;

/// Regex to match credentials in URLs (e.g., `https://user:token@host/...`)
static CRED_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(r"://[^@/]+@").expect("credential regex must compile")
});

/// Replace embedded credentials in a string with `***`.
fn sanitize_credentials(input: &str) -> Cow<'_, str> {
    CRED_RE.replace_all(input, "://***@")
}

/// Log a command just before execution.
///
/// Emits a `tracing::debug!` event with the program name, arguments, and
/// working directory. Visible when running with `--verbose` (which sets
/// `gitgrip=debug`) or via `RUST_LOG=gitgrip::util::cmd=debug`.
///
/// Credentials embedded in URLs (e.g., `https://user:token@host`) are
/// automatically masked before logging.
pub fn log_cmd(cmd: &Command) {
    let program = cmd.get_program().to_string_lossy();
    let args: Vec<_> = cmd
        .get_args()
        .map(|a| sanitize_credentials(&a.to_string_lossy()).into_owned())
        .collect();
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

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_sanitize_https_with_credentials() {
        let input = "https://user:ghp_token123@github.com/org/repo.git";
        assert_eq!(
            sanitize_credentials(input),
            "https://***@github.com/org/repo.git"
        );
    }

    #[test]
    fn test_sanitize_ssh_unchanged() {
        let input = "git@github.com:org/repo.git";
        assert_eq!(sanitize_credentials(input), input);
    }

    #[test]
    fn test_sanitize_plain_string_unchanged() {
        let input = "just a normal argument";
        assert_eq!(sanitize_credentials(input), input);
    }

    #[test]
    fn test_sanitize_https_without_credentials() {
        let input = "https://github.com/org/repo.git";
        assert_eq!(sanitize_credentials(input), input);
    }
}
