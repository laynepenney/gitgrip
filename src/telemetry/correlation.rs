//! Correlation ID generation for request tracing.
//!
//! Generates unique IDs to correlate related operations across
//! git commands, platform API calls, and multi-repo operations.

use std::sync::atomic::{AtomicU64, Ordering};
use std::time::{SystemTime, UNIX_EPOCH};

/// Counter for unique IDs within a session
static COUNTER: AtomicU64 = AtomicU64::new(0);

/// A unique correlation ID for tracing related operations.
#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub struct CorrelationId(String);

impl CorrelationId {
    /// Generate a new unique correlation ID.
    ///
    /// Format: `{timestamp_ms}-{counter}`
    pub fn new() -> Self {
        let timestamp = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap_or_default()
            .as_millis();
        let counter = COUNTER.fetch_add(1, Ordering::Relaxed);
        Self(format!("{timestamp}-{counter}"))
    }

    /// Create a correlation ID from an existing string.
    pub fn from_string(s: impl Into<String>) -> Self {
        Self(s.into())
    }

    /// Get the ID as a string slice.
    pub fn as_str(&self) -> &str {
        &self.0
    }
}

impl Default for CorrelationId {
    fn default() -> Self {
        Self::new()
    }
}

impl std::fmt::Display for CorrelationId {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}", self.0)
    }
}

/// Extension trait for adding correlation IDs to tracing spans.
pub trait CorrelationIdExt {
    /// Record a correlation ID on the current span.
    fn record_correlation_id(&self, id: &CorrelationId);
}

#[cfg(feature = "telemetry")]
impl CorrelationIdExt for tracing::Span {
    fn record_correlation_id(&self, id: &CorrelationId) {
        self.record("correlation_id", id.as_str());
    }
}

#[cfg(not(feature = "telemetry"))]
impl<T> CorrelationIdExt for T {
    fn record_correlation_id(&self, _id: &CorrelationId) {
        // No-op when telemetry is disabled
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_correlation_id_unique() {
        let id1 = CorrelationId::new();
        let id2 = CorrelationId::new();
        assert_ne!(id1, id2);
    }

    #[test]
    fn test_correlation_id_display() {
        let id = CorrelationId::from_string("test-123");
        assert_eq!(format!("{id}"), "test-123");
    }
}
