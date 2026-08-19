//! Process-level outcome classification for CLI commands.
//!
//! `anyhow::Result` distinguishes success from failure, but not a command that
//! was operationally unable to run from one that deliberately refused an act.
//! Callers need that distinction without parsing rendered prose.

use thiserror::Error;

/// Exit code used when the command understood the request but refused the act.
pub const EXIT_REFUSED: u8 = 2;

/// An error whose process status and rendering behavior are part of the CLI contract.
#[derive(Debug, Error)]
#[error("{message}")]
pub struct CliOutcomeError {
    exit_code: u8,
    already_reported: bool,
    message: String,
}

impl CliOutcomeError {
    /// Refuse before any command-specific diagnostic has been rendered.
    pub fn refusal(message: impl Into<String>) -> Self {
        Self {
            exit_code: EXIT_REFUSED,
            already_reported: false,
            message: message.into(),
        }
    }

    /// Refuse after the command has already rendered the actionable diagnostic.
    pub fn reported_refusal(message: impl Into<String>) -> Self {
        Self {
            exit_code: EXIT_REFUSED,
            already_reported: true,
            message: message.into(),
        }
    }

    pub fn exit_code(&self) -> u8 {
        self.exit_code
    }

    pub fn already_reported(&self) -> bool {
        self.already_reported
    }
}

/// Resolve the process code without requiring callers to know concrete error types.
pub fn exit_code_for_error(error: &anyhow::Error) -> u8 {
    error
        .downcast_ref::<CliOutcomeError>()
        .map(CliOutcomeError::exit_code)
        .unwrap_or(1)
}

/// Whether the command already printed the diagnostic that explains this failure.
pub fn error_was_reported(error: &anyhow::Error) -> bool {
    error
        .downcast_ref::<CliOutcomeError>()
        .map(CliOutcomeError::already_reported)
        .unwrap_or(false)
}

/// Render an unreported error with the same Debug shape used by the previous
/// `Result<(), anyhow::Error>` process entry point.
pub fn render_unreported_error(error: &anyhow::Error) -> String {
    format!("Error: {error:?}")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn refusal_is_distinct_from_operational_failure() {
        let refused = anyhow::Error::from(CliOutcomeError::refusal("not ready"));
        let operational = anyhow::anyhow!("network failed");

        assert_eq!(exit_code_for_error(&refused), EXIT_REFUSED);
        assert_eq!(exit_code_for_error(&operational), 1);
    }

    #[test]
    fn only_reported_refusals_suppress_duplicate_rendering() {
        let pending = anyhow::Error::from(CliOutcomeError::refusal("bad selector"));
        let rendered = anyhow::Error::from(CliOutcomeError::reported_refusal("not ready"));

        assert!(!error_was_reported(&pending));
        assert!(error_was_reported(&rendered));
    }

    #[test]
    fn unreported_errors_keep_the_prior_debug_chain_shape() {
        let error = anyhow::anyhow!("inner failure").context("outer context");
        let rendered = render_unreported_error(&error);

        assert!(
            rendered.starts_with("Error: outer context\n\nCaused by:\n    inner failure"),
            "unexpected rendering: {rendered:?}"
        );
    }
}
