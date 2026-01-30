# gitgrip Benchmark Strategy

This document outlines the approach for implementing comprehensive benchmarks across all gitgrip commands.

## Benchmark Categories

### 1. Micro-benchmarks (Criterion)
Fast, isolated operations that don't require external resources.

**Location:** `benches/benchmarks.rs`

| Benchmark | Description | Target |
|-----------|-------------|--------|
| `manifest_parse` | YAML manifest parsing | <50µs |
| `state_parse` | JSON state file parsing | <5µs |
| `url_parse_*` | Git URL parsing (SSH, HTTPS) | <1µs |
| `manifest_validate` | Manifest validation | <1µs |
| `git_status` | Git status check | <500µs |

### 2. Command Benchmarks (CLI)
Full command execution benchmarks via `gr bench`.

**Location:** Built into `src/main.rs`

Currently implemented:
- `manifest_parse` - Manifest parsing
- `state_parse` - State file parsing
- `url_parse` - URL parsing

### 3. Integration Benchmarks (New)
End-to-end command performance in realistic scenarios.

**Location:** `benches/commands.rs` (to be created)

## Adding Benchmarks for New Features

When implementing a new feature, follow this checklist:

### 1. Identify Benchmarkable Operations

- **Pure functions**: Parsing, validation, transformation
- **I/O operations**: File reads/writes, git operations
- **Command execution**: Full command timing

### 2. Add Micro-benchmarks (if applicable)

```rust
// In benches/benchmarks.rs
fn bench_new_operation(c: &mut Criterion) {
    let test_data = setup_test_data();

    c.bench_function("operation_name", |b| {
        b.iter(|| your_operation(black_box(&test_data)))
    });
}
```

### 3. Add Command Timing (for all commands)

Every command implementation should include timing instrumentation:

```rust
use crate::util::timing::Timer;

pub fn run_command(...) -> anyhow::Result<()> {
    let _timer = Timer::new("command_name");  // Auto-logs on drop

    // Command implementation
}
```

### 4. Add CLI Benchmark (for performance-critical commands)

In `main.rs`, add to the benchmark command:

```rust
if name.is_none() || name == Some("command_name") {
    let result = benchmark("command_name", iterations, || {
        // Benchmark code
    });
    result.print();
    results.push(result);
}
```

## Performance Targets

| Category | Target | Rationale |
|----------|--------|-----------|
| Startup time | <10ms | Snappy CLI feel |
| Status check (per repo) | <100ms | Quick feedback |
| Manifest parse | <1ms | Called on every command |
| PR operations | <2s | Network bound, but cached |

## Running Benchmarks

### Development
```bash
# Quick check during development
cargo bench -- --quick

# Full benchmark run
cargo bench

# CLI benchmarks
./target/release/gr bench -n 100
```

### CI/CD
```bash
# Compare against baseline
cargo bench -- --save-baseline main
cargo bench -- --baseline main

# Generate report
cargo criterion --message-format=json > bench-results.json
```

### Comparison with TypeScript
```bash
./run-benchmarks.sh 100
cat benchmark-results/COMPARISON-REPORT.md
```

## Benchmark Results Storage

- **Criterion reports**: `target/criterion/`
- **CLI results**: `benchmark-results/`
- **Historical data**: Tracked in CI artifacts

## Template: Adding Benchmarks to a New Command

1. **Create timing points:**
```rust
// In your command module
let timer = Timer::new("my_command");

// At key points, log intermediate timings
timer.checkpoint("loaded_manifest");
timer.checkpoint("processed_repos");
```

2. **Add Criterion benchmark (if pure operation):**
```rust
// In benches/benchmarks.rs
fn bench_my_operation(c: &mut Criterion) {
    c.bench_function("my_operation", |b| {
        b.iter(|| operation_to_benchmark())
    });
}

// Add to criterion_group!
```

3. **Add CLI benchmark (if command-level):**
```rust
// In main.rs run_benchmarks()
if name.is_none() || name == Some("my_command") {
    // Setup test scenario
    let result = benchmark("my_command", iterations, || {
        // Benchmark the operation
    });
    result.print();
    results.push(result);
}
```

4. **Document expected performance:**
- Add target to this file
- Update README with any new benchmarks
- Add to PR description

## Future Improvements

- [ ] Add command-level benchmarks for all 17 commands
- [ ] Implement continuous performance tracking in CI
- [ ] Add memory usage benchmarks
- [ ] Add concurrent operation benchmarks
- [ ] Create visual performance dashboard
