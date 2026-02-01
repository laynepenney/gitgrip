//! Telemetry, tracing, and metrics for gitgrip.
//!
//! This module provides observability infrastructure:
//! - Structured logging with spans via the `tracing` crate
//! - Metrics collection for git and platform operations
//! - Correlation IDs for request tracing
//!
//! # Feature Flags
//!
//! - `telemetry` (default): Full tracing spans and metrics
//! - `release-logs`: Strip debug/trace at compile time
//! - `max-perf`: Disable all tracing for maximum performance

mod correlation;
mod init;
pub mod metrics;
mod spans;

pub use correlation::{CorrelationId, CorrelationIdExt};
pub use init::{init_telemetry, TelemetryConfig, TelemetryGuard};
pub use metrics::{
    GitMetrics, Metrics, MetricsSnapshot, OperationMetrics, PlatformMetrics, GLOBAL_METRICS,
};
pub use spans::{GitSpan, PlatformSpan, SpanExt};
