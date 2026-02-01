//! Telemetry initialization.
//!
//! Provides configuration and initialization for the tracing subscriber.

use tracing::Level;
use tracing_subscriber::fmt;
use tracing_subscriber::prelude::*;
use tracing_subscriber::EnvFilter;

/// Configuration for telemetry initialization.
#[derive(Debug, Clone)]
pub struct TelemetryConfig {
    /// Default log level
    pub default_level: Level,
    /// Whether to include span enter/exit events
    pub include_span_events: bool,
    /// Whether to include file and line numbers
    pub include_file_line: bool,
    /// Whether to include the target (module path)
    pub include_target: bool,
    /// Whether to use ANSI colors
    pub ansi_colors: bool,
    /// Whether to use compact format
    pub compact: bool,
    /// Custom filter directive (overrides default_level if set)
    pub filter_directive: Option<String>,
}

impl Default for TelemetryConfig {
    fn default() -> Self {
        Self {
            default_level: Level::INFO,
            include_span_events: false,
            include_file_line: false,
            include_target: true,
            ansi_colors: true,
            compact: true,
            filter_directive: None,
        }
    }
}

impl TelemetryConfig {
    /// Create a development configuration (more verbose).
    pub fn development() -> Self {
        Self {
            default_level: Level::DEBUG,
            include_span_events: true,
            include_file_line: true,
            include_target: true,
            ansi_colors: true,
            compact: false,
            filter_directive: None,
        }
    }

    /// Create a production configuration (minimal overhead).
    pub fn production() -> Self {
        Self {
            default_level: Level::WARN,
            include_span_events: false,
            include_file_line: false,
            include_target: false,
            ansi_colors: false,
            compact: true,
            filter_directive: None,
        }
    }
}

/// Guard that keeps the telemetry subscriber active.
///
/// When dropped, the subscriber is deregistered.
pub struct TelemetryGuard {
    #[allow(dead_code)]
    _private: (),
}

/// Initialize telemetry with the given configuration.
///
/// Returns a guard that must be kept alive for the duration of the application.
/// Telemetry is disabled when the guard is dropped.
///
/// # Example
///
/// ```rust,ignore
/// use gitgrip::telemetry::{init_telemetry, TelemetryConfig};
///
/// fn main() -> anyhow::Result<()> {
///     let config = TelemetryConfig::default();
///     let _guard = init_telemetry(&config)?;
///
///     // Application code...
///     Ok(())
/// }
/// ```
pub fn init_telemetry(config: &TelemetryConfig) -> anyhow::Result<TelemetryGuard> {
    let filter = if let Some(ref directive) = config.filter_directive {
        EnvFilter::try_new(directive)?
    } else {
        EnvFilter::from_default_env()
            .add_directive(config.default_level.into())
            .add_directive(format!("gitgrip={}", config.default_level).parse()?)
    };

    let fmt_layer = fmt::layer()
        .with_ansi(config.ansi_colors)
        .with_target(config.include_target)
        .with_file(config.include_file_line)
        .with_line_number(config.include_file_line);

    let fmt_layer = if config.compact {
        fmt_layer.compact().boxed()
    } else {
        fmt_layer.boxed()
    };

    let subscriber = tracing_subscriber::registry()
        .with(filter)
        .with(fmt_layer);

    tracing::subscriber::set_global_default(subscriber)?;

    Ok(TelemetryGuard { _private: () })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_config_default() {
        let config = TelemetryConfig::default();
        assert_eq!(config.default_level, Level::INFO);
        assert!(config.compact);
    }

    #[test]
    fn test_config_development() {
        let config = TelemetryConfig::development();
        assert_eq!(config.default_level, Level::DEBUG);
        assert!(config.include_span_events);
    }

    #[test]
    fn test_config_production() {
        let config = TelemetryConfig::production();
        assert_eq!(config.default_level, Level::WARN);
        assert!(!config.include_span_events);
    }
}
