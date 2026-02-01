//! Span helpers for git and platform operations.
//!
//! Provides ergonomic wrappers for creating and recording tracing spans.

#[cfg(feature = "telemetry")]
use tracing::Span;

/// Helper for git operation spans.
pub struct GitSpan;

impl GitSpan {
    /// Create a span for a git operation.
    #[cfg(feature = "telemetry")]
    pub fn new(operation: &str, repo_path: &str) -> Span {
        tracing::info_span!(
            "git_operation",
            operation = %operation,
            repo_path = %repo_path,
            success = tracing::field::Empty,
            duration_ms = tracing::field::Empty
        )
    }

    #[cfg(not(feature = "telemetry"))]
    pub fn new(_operation: &str, _repo_path: &str) -> NoOpSpan {
        NoOpSpan
    }
}

/// Helper for platform API operation spans.
pub struct PlatformSpan;

impl PlatformSpan {
    /// Create a span for a platform API operation.
    #[cfg(feature = "telemetry")]
    pub fn new(platform: &str, operation: &str, owner: &str, repo: &str) -> Span {
        tracing::info_span!(
            "platform_api",
            platform = %platform,
            operation = %operation,
            owner = %owner,
            repo = %repo,
            success = tracing::field::Empty,
            duration_ms = tracing::field::Empty
        )
    }

    #[cfg(not(feature = "telemetry"))]
    pub fn new(_platform: &str, _operation: &str, _owner: &str, _repo: &str) -> NoOpSpan {
        NoOpSpan
    }
}

/// No-op span when telemetry is disabled.
#[derive(Clone)]
#[allow(dead_code)]
pub struct NoOpSpan;

#[allow(dead_code)]
impl NoOpSpan {
    /// No-op record.
    pub fn record<T>(&self, _field: &str, _value: T) {}

    /// No-op enter.
    pub fn enter(&self) -> NoOpGuard {
        NoOpGuard
    }
}

/// No-op guard when telemetry is disabled.
#[allow(dead_code)]
pub struct NoOpGuard;

/// Extension trait for spans.
pub trait SpanExt {
    /// Record success status on the span.
    fn record_success(&self, success: bool);

    /// Record duration in milliseconds on the span.
    fn record_duration_ms(&self, duration_ms: f64);
}

#[cfg(feature = "telemetry")]
impl SpanExt for Span {
    fn record_success(&self, success: bool) {
        self.record("success", success);
    }

    fn record_duration_ms(&self, duration_ms: f64) {
        self.record("duration_ms", duration_ms);
    }
}

#[cfg(not(feature = "telemetry"))]
impl SpanExt for NoOpSpan {
    fn record_success(&self, _success: bool) {}
    fn record_duration_ms(&self, _duration_ms: f64) {}
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_git_span_creation() {
        let _span = GitSpan::new("clone", "/path/to/repo");
        // Just verify it compiles and doesn't panic
    }

    #[test]
    fn test_platform_span_creation() {
        let _span = PlatformSpan::new("github", "create_pr", "owner", "repo");
        // Just verify it compiles and doesn't panic
    }

    #[cfg(not(feature = "telemetry"))]
    #[test]
    fn test_noop_span() {
        let span = NoOpSpan;
        span.record("field", "value");
        span.record_success(true);
        span.record_duration_ms(100.0);
    }
}
