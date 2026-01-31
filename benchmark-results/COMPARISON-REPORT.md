# gitgrip Benchmark Comparison: Rust vs TypeScript

## Test Environment
- **Date:** Fri Jan 30 08:28:26 CST 2026
- **System:** Darwin arm64
- **Rust:** rustc 1.93.0 (254b59607 2026-01-19)
- **Node:** v22.22.0
- **Iterations:** 50

## Summary

| Benchmark | TypeScript | Rust (Criterion) | Speedup |
|-----------|-----------|------------------|---------|
| manifest_parse | 0.585ms | .023768ms | 24.6x |
| state_parse | 0.002ms | .001349ms | 1.4x |
| url_parse_github_ssh | 0.001ms | .000496ms | 2.0x |
| url_parse_azure_https | 0.001ms | .000553ms | 1.8x |
| manifest_validate | 0.001ms | .000289ms | 3.4x |
| path_join | 0.001ms | .000090ms | 11.1x |
| path_canonicalize_relative | 0.000ms | N/A | N/A |
| url_regex_github | 0.000ms | .000368ms | N/A |
| url_regex_gitlab | 0.000ms | .000430ms | N/A |
| file_hash_content | 0.005ms | .001157ms | 4.3x |
| git_status | 14.771ms | .213640ms | 69.1x |
| git_list_branches | 14.330ms | .251860ms | 56.8x |

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
Running TypeScript benchmarks (iterations: 50)...


--- Benchmark: manifest_parse ---
Iterations: 50
Min:    0.313ms
Max:    1.246ms
Avg:    0.585ms
P50:    0.522ms
P95:    1.008ms
StdDev: 0.206ms

--- Benchmark: state_parse ---
Iterations: 50
Min:    0.002ms
Max:    0.004ms
Avg:    0.002ms
P50:    0.002ms
P95:    0.002ms
StdDev: 0.000ms

--- Benchmark: url_parse_github_ssh ---
Iterations: 50
Min:    0.000ms
Max:    0.005ms
Avg:    0.001ms
P50:    0.000ms
P95:    0.001ms
StdDev: 0.001ms

--- Benchmark: url_parse_azure_https ---
Iterations: 50
Min:    0.001ms
Max:    0.001ms
Avg:    0.001ms
P50:    0.001ms
P95:    0.001ms
StdDev: 0.000ms

--- Benchmark: manifest_validate ---
Iterations: 50
Min:    0.000ms
Max:    0.009ms
Avg:    0.001ms
P50:    0.001ms
P95:    0.001ms
StdDev: 0.001ms

--- Benchmark: path_join ---
Iterations: 50
Min:    0.001ms
Max:    0.001ms
Avg:    0.001ms
P50:    0.001ms
P95:    0.001ms
StdDev: 0.000ms

--- Benchmark: path_canonicalize_relative ---
Iterations: 50
Min:    0.000ms
Max:    0.002ms
Avg:    0.000ms
P50:    0.000ms
P95:    0.001ms
StdDev: 0.000ms

--- Benchmark: url_regex_github ---
Iterations: 50
Min:    0.000ms
Max:    0.001ms
Avg:    0.000ms
P50:    0.000ms
P95:    0.001ms
StdDev: 0.000ms

--- Benchmark: url_regex_gitlab ---
Iterations: 50
Min:    0.000ms
Max:    0.000ms
Avg:    0.000ms
P50:    0.000ms
P95:    0.000ms
StdDev: 0.000ms

--- Benchmark: file_hash_content ---
Iterations: 50
Min:    0.003ms
Max:    0.119ms
Avg:    0.005ms
P50:    0.003ms
P95:    0.005ms
StdDev: 0.016ms

Setting up test git repository...

--- Benchmark: git_status ---
Iterations: 50
Min:    13.349ms
Max:    16.804ms
Avg:    14.771ms
P50:    14.713ms
P95:    15.830ms
StdDev: 0.760ms

--- Benchmark: git_list_branches ---
Iterations: 50
Min:    13.015ms
Max:    15.477ms
Avg:    14.330ms
P50:    14.225ms
P95:    15.364ms
StdDev: 0.614ms

=== Summary ===
manifest_parse: avg=0.585ms, p50=0.522ms, p95=1.008ms (n=50)
state_parse: avg=0.002ms, p50=0.002ms, p95=0.002ms (n=50)
url_parse_github_ssh: avg=0.001ms, p50=0.000ms, p95=0.001ms (n=50)
url_parse_azure_https: avg=0.001ms, p50=0.001ms, p95=0.001ms (n=50)
manifest_validate: avg=0.001ms, p50=0.001ms, p95=0.001ms (n=50)
path_join: avg=0.001ms, p50=0.001ms, p95=0.001ms (n=50)
path_canonicalize_relative: avg=0.000ms, p50=0.000ms, p95=0.001ms (n=50)
url_regex_github: avg=0.000ms, p50=0.000ms, p95=0.001ms (n=50)
url_regex_gitlab: avg=0.000ms, p50=0.000ms, p95=0.000ms (n=50)
file_hash_content: avg=0.005ms, p50=0.003ms, p95=0.005ms (n=50)
git_status: avg=14.771ms, p50=14.713ms, p95=15.830ms (n=50)
git_list_branches: avg=14.330ms, p50=14.225ms, p95=15.364ms (n=50)

### Rust Criterion Results

running 87 tests
iiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiii 87/87

test result: ok. 0 passed; 0 failed; 87 ignored; 0 measured; 0 filtered out; finished in 0.00s


running 0 tests

test result: ok. 0 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.00s


running 0 tests

test result: ok. 0 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.00s

Gnuplot not found, using plotters backend
Benchmarking manifest_parse
Benchmarking manifest_parse: Warming up for 3.0000 s
Benchmarking manifest_parse: Collecting 100 samples in estimated 5.0444 s (212k iterations)
Benchmarking manifest_parse: Analyzing
manifest_parse          time:   [23.702 µs 23.768 µs 23.837 µs]
                        change: [-7.4103% -5.4503% -3.6555%] (p = 0.00 < 0.05)
                        Performance has improved.
Found 5 outliers among 100 measurements (5.00%)
  1 (1.00%) low mild
  3 (3.00%) high mild
  1 (1.00%) high severe

Benchmarking state_parse
Benchmarking state_parse: Warming up for 3.0000 s
Benchmarking state_parse: Collecting 100 samples in estimated 5.0015 s (3.7M iterations)
Benchmarking state_parse: Analyzing
state_parse             time:   [1.3457 µs 1.3492 µs 1.3525 µs]
                        change: [-5.1620% -4.0750% -3.0585%] (p = 0.00 < 0.05)
                        Performance has improved.
Found 1 outliers among 100 measurements (1.00%)
  1 (1.00%) high mild

Benchmarking url_parse_github_ssh
Benchmarking url_parse_github_ssh: Warming up for 3.0000 s
Benchmarking url_parse_github_ssh: Collecting 100 samples in estimated 5.0012 s (9.9M iterations)
Benchmarking url_parse_github_ssh: Analyzing
url_parse_github_ssh    time:   [493.44 ns 496.23 ns 499.65 ns]
                        change: [-13.310% -12.045% -10.873%] (p = 0.00 < 0.05)
                        Performance has improved.
Found 2 outliers among 100 measurements (2.00%)
  1 (1.00%) high mild
  1 (1.00%) high severe

Benchmarking url_parse_azure_https
Benchmarking url_parse_azure_https: Warming up for 3.0000 s
Benchmarking url_parse_azure_https: Collecting 100 samples in estimated 5.0021 s (9.1M iterations)
Benchmarking url_parse_azure_https: Analyzing
url_parse_azure_https   time:   [551.31 ns 553.14 ns 554.94 ns]
                        change: [+0.2279% +0.6470% +1.0476%] (p = 0.00 < 0.05)
                        Change within noise threshold.
Found 3 outliers among 100 measurements (3.00%)
  3 (3.00%) high mild

Benchmarking manifest_validate
Benchmarking manifest_validate: Warming up for 3.0000 s
Benchmarking manifest_validate: Collecting 100 samples in estimated 5.0006 s (19M iterations)
Benchmarking manifest_validate: Analyzing
manifest_validate       time:   [286.20 ns 289.98 ns 293.36 ns]
                        change: [+3.9347% +5.0604% +6.3260%] (p = 0.00 < 0.05)
                        Performance has regressed.

Benchmarking git_status
Benchmarking git_status: Warming up for 3.0000 s
Benchmarking git_status: Collecting 100 samples in estimated 5.6544 s (25k iterations)
Benchmarking git_status: Analyzing
git_status              time:   [207.04 µs 213.64 µs 226.95 µs]
                        change: [+0.6700% +2.3305% +5.1939%] (p = 0.02 < 0.05)
                        Change within noise threshold.
Found 11 outliers among 100 measurements (11.00%)
  7 (7.00%) high mild
  4 (4.00%) high severe

Benchmarking git_list_branches
Benchmarking git_list_branches: Warming up for 3.0000 s
Benchmarking git_list_branches: Collecting 100 samples in estimated 6.0840 s (25k iterations)
Benchmarking git_list_branches: Analyzing
git_list_branches       time:   [245.30 µs 251.86 µs 261.41 µs]
                        change: [+17.668% +48.644% +94.175%] (p = 0.00 < 0.05)
                        Performance has regressed.
Found 20 outliers among 100 measurements (20.00%)
  3 (3.00%) high mild
  17 (17.00%) high severe

Benchmarking file_hash_content
Benchmarking file_hash_content: Warming up for 3.0000 s
Benchmarking file_hash_content: Collecting 100 samples in estimated 5.0020 s (4.3M iterations)
Benchmarking file_hash_content: Analyzing
file_hash_content       time:   [1.1546 µs 1.1574 µs 1.1608 µs]
                        change: [+2.7029% +3.0399% +3.3910%] (p = 0.00 < 0.05)
                        Performance has regressed.
Found 5 outliers among 100 measurements (5.00%)
  4 (4.00%) high mild
  1 (1.00%) high severe

Benchmarking path_join
Benchmarking path_join: Warming up for 3.0000 s
Benchmarking path_join: Collecting 100 samples in estimated 5.0003 s (56M iterations)
Benchmarking path_join: Analyzing
path_join               time:   [89.422 ns 90.091 ns 90.819 ns]
                        change: [+4.1320% +4.7712% +5.4731%] (p = 0.00 < 0.05)
                        Performance has regressed.

Benchmarking path_canonicalize_relative
Benchmarking path_canonicalize_relative: Warming up for 3.0000 s
Benchmarking path_canonicalize_relative: Collecting 100 samples in estimated 5.0001 s (58M iterations)
Benchmarking path_canonicalize_relative: Analyzing
path_canonicalize_relative
                        time:   [88.481 ns 88.869 ns 89.274 ns]
                        change: [+4.4006% +4.9297% +5.4272%] (p = 0.00 < 0.05)
                        Performance has regressed.
Found 3 outliers among 100 measurements (3.00%)
  3 (3.00%) high mild

Benchmarking url_regex_github
Benchmarking url_regex_github: Warming up for 3.0000 s
Benchmarking url_regex_github: Collecting 100 samples in estimated 5.0000 s (15M iterations)
Benchmarking url_regex_github: Analyzing
url_regex_github        time:   [363.38 ns 368.93 ns 373.84 ns]
                        change: [+7.8217% +9.0516% +10.501%] (p = 0.00 < 0.05)
                        Performance has regressed.

Benchmarking url_regex_gitlab
Benchmarking url_regex_gitlab: Warming up for 3.0000 s
Benchmarking url_regex_gitlab: Collecting 100 samples in estimated 5.0010 s (11M iterations)
Benchmarking url_regex_gitlab: Analyzing
url_regex_gitlab        time:   [429.15 ns 430.50 ns 431.91 ns]
                        change: [+1.7590% +2.1264% +2.4797%] (p = 0.00 < 0.05)
                        Performance has regressed.
Found 1 outliers among 100 measurements (1.00%)
  1 (1.00%) high mild


### Rust CLI Results (gr bench)
Running benchmarks (iterations: 50)...


--- Benchmark: manifest_parse ---
Iterations: 50
Min:    0.009ms
Max:    0.015ms
Avg:    0.010ms
P50:    0.009ms
P95:    0.011ms
StdDev: 0.001ms

--- Benchmark: state_parse ---
Iterations: 50
Min:    0.000ms
Max:    0.002ms
Avg:    0.000ms
P50:    0.000ms
P95:    0.000ms
StdDev: 0.000ms

--- Benchmark: url_parse ---
Iterations: 50
Min:    0.001ms
Max:    0.001ms
Avg:    0.001ms
P50:    0.001ms
P95:    0.001ms
StdDev: 0.000ms

=== Summary ===
manifest_parse: avg=0.010ms, p50=0.009ms, p95=0.011ms (n=50)
state_parse: avg=0.000ms, p50=0.000ms, p95=0.000ms (n=50)
url_parse: avg=0.001ms, p50=0.001ms, p95=0.001ms (n=50)

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
