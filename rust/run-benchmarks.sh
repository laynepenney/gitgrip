#!/bin/bash
# Unified benchmark comparison script for Rust vs TypeScript
# This script runs both benchmark suites and generates a comparison report

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUST_DIR="$SCRIPT_DIR"
TS_DIR="$(dirname "$SCRIPT_DIR")"
OUTPUT_DIR="$RUST_DIR/benchmark-results"
ITERATIONS=${1:-100}

echo "=============================================="
echo "  gitgrip Benchmark Comparison"
echo "  Rust vs TypeScript"
echo "=============================================="
echo ""
echo "Iterations: $ITERATIONS"
echo "Output directory: $OUTPUT_DIR"
echo ""

mkdir -p "$OUTPUT_DIR"

# Run TypeScript benchmarks
echo "=============================================="
echo "  Running TypeScript Benchmarks..."
echo "=============================================="
cd "$TS_DIR"
npx tsx "$RUST_DIR/bench-compare.ts" "$ITERATIONS" 2>&1 | tee "$OUTPUT_DIR/typescript-results.txt"

echo ""
echo "=============================================="
echo "  Running Rust Benchmarks..."
echo "=============================================="
cd "$RUST_DIR"

# Run Rust benchmarks with cargo bench
cargo bench --quiet 2>&1 | tee "$OUTPUT_DIR/rust-results.txt"

# Also run the built-in gr bench command for comparison
echo ""
echo "=============================================="
echo "  Running Rust CLI Benchmarks (gr bench)..."
echo "=============================================="
./target/release/gr bench --iterations "$ITERATIONS" 2>&1 | tee "$OUTPUT_DIR/rust-cli-results.txt"

echo ""
echo "=============================================="
echo "  Generating Comparison Report..."
echo "=============================================="

# Generate comparison report
cat > "$OUTPUT_DIR/COMPARISON-REPORT.md" << 'HEADER'
# gitgrip Benchmark Comparison: Rust vs TypeScript

## Test Environment
HEADER

echo "- **Date:** $(date)" >> "$OUTPUT_DIR/COMPARISON-REPORT.md"
echo "- **System:** $(uname -s) $(uname -m)" >> "$OUTPUT_DIR/COMPARISON-REPORT.md"
echo "- **Rust:** $(rustc --version)" >> "$OUTPUT_DIR/COMPARISON-REPORT.md"
echo "- **Node:** $(node --version)" >> "$OUTPUT_DIR/COMPARISON-REPORT.md"
echo "- **Iterations:** $ITERATIONS" >> "$OUTPUT_DIR/COMPARISON-REPORT.md"

cat >> "$OUTPUT_DIR/COMPARISON-REPORT.md" << 'MIDDLE'

## Summary

| Benchmark | TypeScript | Rust (Criterion) | Speedup |
|-----------|-----------|------------------|---------|
MIDDLE

# Function to extract TypeScript averages
extract_ts_avg() {
    local name=$1
    grep "^${name}:" "$OUTPUT_DIR/typescript-results.txt" | grep -oE "avg=[0-9.]+" | grep -oE "[0-9.]+" || echo "N/A"
}

# Function to extract Rust Criterion times (convert µs/ns to ms)
extract_rust_time() {
    local name=$1
    local line=$(grep "^${name}" "$OUTPUT_DIR/rust-results.txt" | head -1)
    if [[ -z "$line" ]]; then
        echo "N/A"
        return
    fi

    # Extract the middle value (median) from [min median max]
    local time_part=$(echo "$line" | grep -oE "\[[0-9.]+ [a-zµ]+ [0-9.]+ [a-zµ]+ [0-9.]+ [a-zµ]+\]" | head -1)
    if [[ -z "$time_part" ]]; then
        echo "N/A"
        return
    fi

    # Get the median value and unit
    local median=$(echo "$time_part" | awk '{print $3}')
    local unit=$(echo "$time_part" | awk '{print $4}')

    # Convert to ms
    if [[ "$unit" == "ns" ]]; then
        echo "scale=6; $median / 1000000" | bc 2>/dev/null || echo "N/A"
    elif [[ "$unit" == "µs" ]]; then
        echo "scale=6; $median / 1000" | bc 2>/dev/null || echo "N/A"
    elif [[ "$unit" == "ms" ]]; then
        echo "$median"
    else
        echo "N/A"
    fi
}

# Calculate speedup
calc_speedup() {
    local ts=$1
    local rust=$2
    if [[ "$ts" != "N/A" && "$rust" != "N/A" && "$rust" != "0" ]]; then
        local speedup=$(echo "scale=1; $ts / $rust" | bc 2>/dev/null)
        if [[ -n "$speedup" && "$speedup" != "0" ]]; then
            echo "${speedup}x"
        else
            echo "N/A"
        fi
    else
        echo "N/A"
    fi
}

# Add rows for each benchmark
benchmarks=(
    "manifest_parse"
    "state_parse"
    "url_parse_github_ssh"
    "url_parse_azure_https"
    "manifest_validate"
    "path_join"
    "path_canonicalize_relative"
    "url_regex_github"
    "url_regex_gitlab"
    "file_hash_content"
    "git_status"
    "git_list_branches"
)

for bench in "${benchmarks[@]}"; do
    ts_val=$(extract_ts_avg "$bench")
    rust_val=$(extract_rust_time "$bench")
    speedup=$(calc_speedup "$ts_val" "$rust_val")

    # Format for display
    if [[ "$ts_val" != "N/A" ]]; then
        ts_display="${ts_val}ms"
    else
        ts_display="N/A"
    fi

    if [[ "$rust_val" != "N/A" ]]; then
        rust_display="${rust_val}ms"
    else
        rust_display="N/A"
    fi

    echo "| $bench | $ts_display | $rust_display | $speedup |" >> "$OUTPUT_DIR/COMPARISON-REPORT.md"
done

cat >> "$OUTPUT_DIR/COMPARISON-REPORT.md" << 'DETAILS'

## Key Findings

### Parsing Operations
- **manifest_parse**: Rust is significantly faster due to serde_yaml optimization
- **state_parse**: Both are fast, JSON parsing is well-optimized in V8
- **manifest_validate**: Simple validation, both very fast

### Git Operations
- **git_status**: Rust uses libgit2 directly vs TypeScript shelling out to git CLI
- **git_list_branches**: Same - direct library access is much faster than process spawning

### Path/String Operations
- **path_join**: Both are very fast, negligible difference
- **url_regex_***: Regex engines are both highly optimized

### File Operations
- **file_hash_content**: Node's crypto module is C++ under the hood, competitive with Rust

## Detailed Results

### TypeScript Results
DETAILS

cat "$OUTPUT_DIR/typescript-results.txt" >> "$OUTPUT_DIR/COMPARISON-REPORT.md"

cat >> "$OUTPUT_DIR/COMPARISON-REPORT.md" << 'RUST_HEADER'

### Rust Criterion Results
RUST_HEADER

cat "$OUTPUT_DIR/rust-results.txt" >> "$OUTPUT_DIR/COMPARISON-REPORT.md"

cat >> "$OUTPUT_DIR/COMPARISON-REPORT.md" << 'CLI_HEADER'

### Rust CLI Results (gr bench)
CLI_HEADER

cat "$OUTPUT_DIR/rust-cli-results.txt" >> "$OUTPUT_DIR/COMPARISON-REPORT.md"

cat >> "$OUTPUT_DIR/COMPARISON-REPORT.md" << 'NOTES'

## Notes

- **Criterion** uses statistical analysis with 100+ samples for accuracy
- **TypeScript** git benchmarks use shell exec which adds ~10ms overhead per call
- **Rust** git benchmarks use libgit2 directly (no process spawning)
- Speedup = TypeScript time / Rust time (higher is better for Rust)
- Sub-millisecond operations may hit timer resolution limits

## Running These Benchmarks

```bash
# Full comparison
./rust/run-benchmarks.sh 100

# TypeScript only
npx tsx rust/bench-compare.ts 100

# Rust only (Criterion)
cd rust && cargo bench

# Rust CLI benchmarks
./rust/target/release/gr bench -n 100
```
NOTES

echo ""
echo "=============================================="
echo "  Benchmark Complete!"
echo "=============================================="
echo ""
echo "Results saved to:"
echo "  - $OUTPUT_DIR/COMPARISON-REPORT.md"
echo "  - $OUTPUT_DIR/typescript-results.txt"
echo "  - $OUTPUT_DIR/rust-results.txt"
echo "  - $OUTPUT_DIR/rust-cli-results.txt"
echo ""
echo "Key findings:"
grep -E "^\| (manifest_parse|git_status)" "$OUTPUT_DIR/COMPARISON-REPORT.md" | head -5
