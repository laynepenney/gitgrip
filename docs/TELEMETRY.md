# Telemetry, Tracing, and Benchmarks

This document describes the observability infrastructure in gitgrip and provides guidelines for integrating telemetry into new features.

## Overview

gitgrip uses a lightweight observability stack suitable for CLI applications:

- **Tracing**: Structured logging with spans via the `tracing` crate
- **Metrics**: In-memory metrics collection for git and platform operations
- **Benchmarks**: Criterion-based benchmarks and built-in timing utilities

## Feature Flags and Performance

Telemetry can be controlled at compile time for optimal performance:

### Feature Flags

| Feature | Description | Use Case |
|---------|-------------|----------|
| `telemetry` (default) | Full tracing spans and metrics | Development, debugging |
| `release-logs` | Strip debug/trace at compile time | Production with logging |
| `max-perf` | Disable all tracing | Maximum performance |

### Build Configurations

```bash
# Development (full telemetry)
cargo build

# Production with info-level logging only
cargo build --release --features release-logs

# Maximum performance (no tracing overhead)
cargo build --release --no-default-features

# Or with max-perf for explicit disable
cargo build --release --features max-perf
```

### Performance Characteristics

| Configuration | Span Overhead | Memory | Recommended For |
|--------------|---------------|--------|-----------------|
| `telemetry` | ~50-100ns | Allocations per span | Dev, testing |
| `release-logs` | ~1-2ns | Near zero | Production |
| `max-perf` | 0ns | Zero | Performance-critical |

The `release-logs` feature uses `tracing`'s compile-time filtering to completely eliminate debug and trace macros from the binary, resulting in near-zero overhead while keeping info/warn/error logs.

## Architecture

```
src/telemetry/
├── mod.rs          # Module exports
├── correlation.rs  # Request correlation IDs
├── init.rs         # Telemetry initialization
├── metrics.rs      # Metrics collection (GitMetrics, PlatformMetrics)
└── spans.rs        # Span helpers (GitSpan, PlatformSpan)

benches/
└── benchmarks.rs   # Criterion benchmarks

src/util/
└── timing.rs       # Built-in timing utilities (Timer, BenchmarkResult)
```

## Quick Start

### Initialization

Telemetry is initialized automatically in `main.rs` using `tracing_subscriber`. For custom initialization:

```rust
use gitgrip::telemetry::{init_telemetry, TelemetryConfig};

fn main() -> anyhow::Result<()> {
    let config = TelemetryConfig::default();  // or ::development() / ::production()
    let _guard = init_telemetry(&config)?;

    // Application code...

    Ok(())
}
```

### Instrumenting Functions

Use `cfg_attr` with `#[instrument]` to make instrumentation conditional:

```rust
#[cfg(feature = "telemetry")]
use tracing::{debug, instrument};

// Instrumentation only active when telemetry feature is enabled
#[cfg_attr(feature = "telemetry", instrument(skip(repo), fields(remote, success)))]
pub fn fetch_remote(repo: &Repository, remote: &str) -> Result<(), GitError> {
    let start = Instant::now();

    // Do work...
    let result = do_work();
    let duration = start.elapsed();

    #[cfg(feature = "telemetry")]
    {
        GLOBAL_METRICS.record_git("fetch", duration, result.is_ok());
        debug!(remote, success = result.is_ok(), duration_ms = duration.as_millis() as u64, "Operation complete");
    }

    result
}
```

### Recording Metrics

Metrics are collected in `GLOBAL_METRICS`:

```rust
use gitgrip::telemetry::metrics::GLOBAL_METRICS;
use std::time::Duration;

// Record git operation
GLOBAL_METRICS.record_git("clone", duration, success);

// Record platform API call
GLOBAL_METRICS.record_platform("github", "create_pr", duration, success);

// Record cache hit/miss
GLOBAL_METRICS.record_cache(true);  // hit
GLOBAL_METRICS.record_cache(false); // miss

// Record generic operation
GLOBAL_METRICS.record_operation("manifest_parse", duration);
```

## Guidelines for New Features

### 1. Add Instrumentation to Key Functions

Every function that performs significant I/O or computation should be instrumented:

```rust
#[cfg_attr(feature = "telemetry", instrument(skip(self, input), fields(relevant_field)))]
async fn execute(&self, input: Value) -> Result<Output, Error> {
    // ...
}
```

**Skip large or sensitive data:**
- Use `skip(self)` to avoid serializing the entire struct
- Use `skip(input)` for potentially large inputs
- Never log secrets, API keys, or tokens

### 2. Record Meaningful Fields

Choose fields that help with debugging and monitoring:

```rust
// Good: Helps understand what happened
debug!(repo_path = %path.display(), "Cloning repository");
debug!(branch, remote, success, "Push complete");
debug!(pr_number, owner, repo, "PR created");

// Bad: Too much detail or sensitive
debug!(file_content = %content);  // Could be huge
debug!(token = %auth_token);      // Security risk
```

### 3. Use Appropriate Log Levels

| Level | Use For |
|-------|---------|
| `error!` | Unrecoverable failures |
| `warn!` | Recoverable issues, rate limits |
| `info!` | Significant events (command complete, PR created) |
| `debug!` | Detailed operation info (git command, API call) |
| `trace!` | Very verbose debugging (cache hits, parsing) |

### 4. Integrate with Metrics

For operations that should be monitored, record metrics:

```rust
use std::time::Instant;

let start = Instant::now();
let result = perform_operation().await;
let duration = start.elapsed();

#[cfg(feature = "telemetry")]
GLOBAL_METRICS.record_platform("github", "operation_name", duration, result.is_ok());
```

### 5. Add Benchmarks for Performance-Critical Code

For new commands or performance-sensitive code, add benchmarks:

```rust
// benches/benchmarks.rs
use criterion::{criterion_group, criterion_main, Criterion};
use std::hint::black_box;

fn bench_my_operation(c: &mut Criterion) {
    let mut group = c.benchmark_group("my_feature");

    group.bench_function("operation_name", |b| {
        b.iter(|| {
            black_box(my_operation(args))
        });
    });

    group.finish();
}

criterion_group!(benches, bench_my_operation);
criterion_main!(benches);
```

## Configuration

### Log Levels

Control log verbosity via `RUST_LOG` environment variable:

```bash
# Show only warnings and errors
RUST_LOG=warn gr status

# Show info level for gitgrip, warnings for everything else
RUST_LOG=gitgrip=info,warn gr status

# Debug mode for development
RUST_LOG=gitgrip=debug gr status

# Trace everything (very verbose)
RUST_LOG=trace gr status
```

### TelemetryConfig Options

```rust
TelemetryConfig {
    default_level: Level::INFO,       // Default log level
    include_span_events: false,       // Log span enter/exit
    include_file_line: false,         // Include source location
    include_target: true,             // Include module path
    ansi_colors: true,                // Terminal colors
    compact: true,                    // Compact log format
    filter_directive: None,           // Custom filter
}
```

## Metrics API

### GitMetrics

Tracked for git operations (clone, fetch, push, pull):

```rust
pub struct GitMetrics {
    pub invocations: u64,
    pub successes: u64,
    pub failures: u64,
    pub total_duration: Duration,
    pub min_duration: Duration,
    pub max_duration: Duration,
    pub histogram: Histogram,
}
```

### PlatformMetrics

Tracked for platform API calls (GitHub, GitLab, Azure DevOps):

```rust
pub struct PlatformMetrics {
    pub invocations: u64,
    pub successes: u64,
    pub failures: u64,
    pub rate_limits: u64,
    pub total_duration: Duration,
    pub histogram: Histogram,
}
```

### MetricsSnapshot

Get a point-in-time snapshot of all metrics:

```rust
let snapshot = GLOBAL_METRICS.snapshot();
println!("{}", snapshot.format_report());
```

### Histogram

Latency distribution tracking with percentiles:

```rust
let metrics = snapshot.git.get("clone").unwrap();
println!("p50: {:?}", metrics.histogram.p50());
println!("p99: {:?}", metrics.histogram.p99());
```

## Running Benchmarks

### Criterion Benchmarks

```bash
# Run all benchmarks
cargo bench

# Run specific benchmark
cargo bench --bench benchmarks

# Generate HTML report
cargo bench -- --plotting-backend plotters
```

### Measuring Telemetry Overhead

To compare performance with and without telemetry:

```bash
# With telemetry (default) - measures metrics recording overhead
cargo bench --bench benchmarks -- telemetry_overhead

# Without telemetry - measures baseline (zero overhead)
cargo bench --bench benchmarks --no-default-features -- telemetry_overhead
```

**Expected Results:**

| Operation | With Telemetry | Without Telemetry |
|-----------|---------------|-------------------|
| `record_git_metric` | ~50-100ns | 0ns (compiled out) |
| `record_platform_metric` | ~50-100ns | 0ns (compiled out) |
| `record_cache_metric` | ~20-50ns | 0ns (compiled out) |
| `metrics_snapshot` | ~1-5µs | N/A |

The overhead is minimal (~100ns per operation) and completely eliminated when building with `--no-default-features` or `--features max-perf`.

### Built-in Timing

gitgrip includes timing utilities in `src/util/timing.rs`:

```rust
use gitgrip::util::timing::{benchmark, Timer};

// Simple timer
let timer = Timer::start("operation");
// ... do work ...
timer.stop_and_print();

// Benchmark with statistics
let result = benchmark("operation", 100, || {
    // operation to benchmark
});
result.print();
```

### Workspace Benchmarks

The `gr bench` command runs workspace-level benchmarks:

```bash
# Run all benchmarks
gr bench

# Run specific benchmark
gr bench manifest-load -n 10

# List available benchmarks
gr bench --list
```

## Example: Full Feature Integration

Here's a complete example of integrating telemetry into a new git operation:

```rust
use std::time::Instant;

#[cfg(feature = "telemetry")]
use crate::telemetry::metrics::GLOBAL_METRICS;
#[cfg(feature = "telemetry")]
use tracing::{debug, instrument, warn};

/// Clone a repository
#[cfg_attr(feature = "telemetry", instrument(skip(url), fields(url, path, success)))]
pub fn clone_repo(url: &str, path: &std::path::Path) -> Result<(), GitError> {
    let start = Instant::now();

    #[cfg(feature = "telemetry")]
    debug!(url, path = %path.display(), "Starting clone");

    let result = git2::Repository::clone(url, path);
    let duration = start.elapsed();
    let success = result.is_ok();

    #[cfg(feature = "telemetry")]
    {
        GLOBAL_METRICS.record_git("clone", duration, success);
        if success {
            debug!(url, duration_ms = duration.as_millis() as u64, "Clone complete");
        } else {
            warn!(url, error = ?result.as_ref().err(), "Clone failed");
        }
    }

    result.map(|_| ()).map_err(|e| GitError::CloneFailed(e.to_string()))
}
```

## Future Enhancements

The telemetry system is designed to be extended:

- **OpenTelemetry export**: Add OTLP exporter for distributed tracing
- **Prometheus metrics**: Export metrics in Prometheus format
- **JSON logging**: Structured JSON output for log aggregation
- **Sampling**: Configurable sampling for high-volume operations
