//! Benchmark core operations

use std::time::Instant;

use anyhow::Result;
use clap::Args;
use colored::Colorize;

use crate::core::manifest::{Manifest, RepoConfig};
use crate::core::repo::RepoInfo;
use crate::core::state::StateFile;

#[derive(Args, Debug)]
pub struct BenchArgs {
    /// Specific benchmark to run (omit to run all)
    #[arg()]
    pub operation: Option<String>,

    /// List available benchmarks
    #[arg(short, long)]
    pub list: bool,

    /// Number of iterations
    #[arg(short = 'n', long, default_value = "10")]
    pub iterations: usize,

    /// Number of warmup iterations
    #[arg(short, long, default_value = "2")]
    pub warmup: usize,

    /// Output as JSON
    #[arg(long)]
    pub json: bool,
}

/// Benchmark result
#[derive(Debug, serde::Serialize)]
pub struct BenchmarkResult {
    pub name: String,
    pub iterations: usize,
    pub min: f64,
    pub max: f64,
    pub avg: f64,
    pub p50: f64,
    pub p95: f64,
    pub std_dev: f64,
}

/// Available benchmarks
struct Benchmark {
    name: &'static str,
    description: &'static str,
}

const BENCHMARKS: &[Benchmark] = &[
    Benchmark {
        name: "manifest-parse",
        description: "Parse manifest YAML",
    },
    Benchmark {
        name: "state-parse",
        description: "Parse state JSON file",
    },
    Benchmark {
        name: "url-parse",
        description: "Parse git URL to RepoInfo",
    },
];

/// Sample manifest YAML for benchmarking
const SAMPLE_MANIFEST: &str = r#"
version: 1
repos:
  app:
    url: git@github.com:user/app.git
    path: app
    default_branch: main
  lib:
    url: git@github.com:user/lib.git
    path: lib
  common:
    url: git@github.com:user/common.git
    path: common
    default_branch: develop
settings:
  pr_prefix: "[multi-repo]"
  merge_strategy: all-or-nothing
"#;

/// Sample state JSON for benchmarking
const SAMPLE_STATE: &str = r#"{
    "currentManifestPr": 42,
    "branchToPr": {
        "feat/test": 42,
        "feat/another": 43,
        "fix/bug": 44
    },
    "prLinks": {
        "42": [
            {
                "repoName": "app",
                "owner": "user",
                "repo": "app",
                "number": 100,
                "url": "https://github.com/user/app/pull/100",
                "state": "open",
                "approved": true,
                "checksPass": true,
                "mergeable": true
            },
            {
                "repoName": "lib",
                "owner": "user",
                "repo": "lib",
                "number": 101,
                "url": "https://github.com/user/lib/pull/101",
                "state": "open",
                "approved": false,
                "checksPass": true,
                "mergeable": true
            }
        ]
    }
}"#;

/// List available benchmarks
fn list_benchmarks() {
    println!("{}\n", "Available Benchmarks".blue());

    let max_name_len = BENCHMARKS.iter().map(|b| b.name.len()).max().unwrap_or(0);

    for bench in BENCHMARKS {
        println!(
            "  {}{}",
            bench.name.cyan(),
            " ".repeat(max_name_len - bench.name.len() + 2),
        );
        println!("      {}", bench.description);
    }

    println!();
    println!("{}", "Run a specific benchmark:".dimmed());
    println!("{}", "  gr bench manifest-parse".dimmed());
    println!("{}", "  gr bench state-parse -n 100".dimmed());
    println!();
    println!("{}", "Run all benchmarks:".dimmed());
    println!("{}", "  gr bench".dimmed());
}

/// Calculate statistics from durations
fn calculate_stats(durations: &[f64]) -> (f64, f64, f64, f64, f64, f64) {
    if durations.is_empty() {
        return (0.0, 0.0, 0.0, 0.0, 0.0, 0.0);
    }

    let mut sorted = durations.to_vec();
    sorted.sort_by(|a, b| a.partial_cmp(b).unwrap());

    let n = sorted.len();
    let min = sorted[0];
    let max = sorted[n - 1];
    let sum: f64 = sorted.iter().sum();
    let avg = sum / n as f64;

    // Percentiles
    let p50_idx = (n as f64 * 0.5).floor() as usize;
    let p95_idx = (n as f64 * 0.95).floor() as usize;
    let p50 = sorted[p50_idx.min(n - 1)];
    let p95 = sorted[p95_idx.min(n - 1)];

    // Standard deviation
    let variance: f64 = sorted.iter().map(|x| (x - avg).powi(2)).sum::<f64>() / n as f64;
    let std_dev = variance.sqrt();

    (min, max, avg, p50, p95, std_dev)
}

/// Format duration in milliseconds
fn format_duration(ms: f64) -> String {
    if ms < 0.001 {
        format!("{:.0}ns", ms * 1_000_000.0)
    } else if ms < 1.0 {
        format!("{:.0}µs", ms * 1000.0)
    } else if ms < 1000.0 {
        format!("{:.2}ms", ms)
    } else if ms < 60000.0 {
        format!("{:.2}s", ms / 1000.0)
    } else {
        let minutes = (ms / 60000.0).floor();
        let seconds = (ms % 60000.0) / 1000.0;
        format!("{:.0}m {:.1}s", minutes, seconds)
    }
}

/// Run a benchmark operation once
fn run_benchmark_operation(name: &str) -> Result<()> {
    match name {
        "manifest-parse" => {
            let _ = Manifest::parse(SAMPLE_MANIFEST)?;
            Ok(())
        }
        "state-parse" => {
            let _ = StateFile::parse(SAMPLE_STATE)?;
            Ok(())
        }
        "url-parse" => {
            let config = RepoConfig {
                url: "git@github.com:user/repo.git".to_string(),
                path: "repo".to_string(),
                default_branch: "main".to_string(),
                copyfile: None,
                linkfile: None,
                platform: None,
            };
            let workspace = std::path::PathBuf::from("/workspace");
            let _ = RepoInfo::from_config("repo", &config, &workspace);
            Ok(())
        }
        _ => Err(anyhow::anyhow!(
            "Unknown benchmark: {}. Use --list to see available benchmarks.",
            name
        )),
    }
}

/// Run a single benchmark with warmup and iterations
fn run_single_benchmark(
    name: &str,
    iterations: usize,
    warmup: usize,
) -> Result<BenchmarkResult> {
    let mut durations = Vec::with_capacity(iterations);

    // Warmup runs
    for _ in 0..warmup {
        run_benchmark_operation(name)?;
    }

    // Actual benchmark runs
    for _ in 0..iterations {
        let start = Instant::now();
        run_benchmark_operation(name)?;
        let elapsed = start.elapsed();
        durations.push(elapsed.as_secs_f64() * 1000.0); // Convert to ms
    }

    let (min, max, avg, p50, p95, std_dev) = calculate_stats(&durations);

    Ok(BenchmarkResult {
        name: name.to_string(),
        iterations,
        min,
        max,
        avg,
        p50,
        p95,
        std_dev,
    })
}

/// Format benchmark results as a table
fn format_results(results: &[BenchmarkResult]) -> String {
    let mut lines = Vec::new();

    lines.push("Benchmark Results".to_string());
    lines.push("═════════════════".to_string());
    lines.push(String::new());

    // Header
    lines.push("Operation        │ Iter │      Min │      Max │      Avg │      P95".to_string());
    lines.push("─────────────────┼──────┼──────────┼──────────┼──────────┼──────────".to_string());

    // Rows
    for result in results {
        let name = format!("{:16}", result.name);
        let iter = format!("{:4}", result.iterations);
        let min = format!("{:>8}", format_duration(result.min));
        let max = format!("{:>8}", format_duration(result.max));
        let avg = format!("{:>8}", format_duration(result.avg));
        let p95 = format!("{:>8}", format_duration(result.p95));
        lines.push(format!(
            "{} │ {} │ {} │ {} │ {} │ {}",
            name, iter, min, max, avg, p95
        ));
    }

    lines.join("\n")
}

/// Benchmark core operations
pub async fn run(args: BenchArgs) -> Result<()> {
    // List mode
    if args.list {
        list_benchmarks();
        return Ok(());
    }

    let mut results = Vec::new();

    if let Some(ref operation) = args.operation {
        // Run single benchmark
        if !args.json {
            println!("{}\n", format!("Running benchmark: {}", operation).blue());
            println!(
                "{}\n",
                format!("Iterations: {}, Warmup: {}", args.iterations, args.warmup).dimmed()
            );
        }

        let result = run_single_benchmark(operation, args.iterations, args.warmup)?;
        results.push(result);
    } else {
        // Run all benchmarks
        if !args.json {
            println!("{}\n", "Running all benchmarks".blue());
            println!(
                "{}\n",
                format!("Iterations: {}, Warmup: {}", args.iterations, args.warmup).dimmed()
            );
        }

        for bench in BENCHMARKS {
            if !args.json {
                print!("  {}...", bench.name);
            }

            match run_single_benchmark(bench.name, args.iterations, args.warmup) {
                Ok(result) => {
                    results.push(result);
                    if !args.json {
                        println!("{}", " done".green());
                    }
                }
                Err(e) => {
                    if !args.json {
                        println!("{}", format!(" failed: {}", e).red());
                    }
                }
            }
        }

        if !args.json {
            println!();
        }
    }

    // Output results
    if args.json {
        println!("{}", serde_json::to_string_pretty(&results)?);
    } else {
        println!("{}", format_results(&results));
    }

    Ok(())
}
