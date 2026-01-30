//! gitgrip CLI entry point

use clap::{Parser, Subcommand};

#[derive(Parser)]
#[command(name = "gr")]
#[command(author, version, about = "Multi-repo workflow tool", long_about = None)]
struct Cli {
    #[command(subcommand)]
    command: Option<Commands>,
}

#[derive(Subcommand)]
enum Commands {
    /// Initialize a new workspace
    Init {
        /// Manifest URL
        url: Option<String>,
    },
    /// Sync all repositories
    Sync {
        /// Force sync even with local changes
        #[arg(short, long)]
        force: bool,
    },
    /// Show status of all repositories
    Status {
        /// Show detailed status
        #[arg(short, long)]
        verbose: bool,
    },
    /// Create or switch branches across repos
    Branch {
        /// Branch name
        name: Option<String>,
        /// Delete branch
        #[arg(short, long)]
        delete: bool,
        /// Include manifest repo
        #[arg(long)]
        include_manifest: bool,
    },
    /// Checkout a branch across repos
    Checkout {
        /// Branch name
        name: String,
    },
    /// Stage changes across repos
    Add {
        /// Files to add (. for all)
        #[arg(default_value = ".")]
        files: Vec<String>,
    },
    /// Show diff across repos
    Diff {
        /// Show staged changes
        #[arg(long)]
        staged: bool,
    },
    /// Commit changes across repos
    Commit {
        /// Commit message
        #[arg(short, long)]
        message: Option<String>,
        /// Amend previous commit
        #[arg(long)]
        amend: bool,
    },
    /// Push changes across repos
    Push {
        /// Set upstream
        #[arg(short = 'u', long)]
        set_upstream: bool,
        /// Force push
        #[arg(short, long)]
        force: bool,
    },
    /// Pull request operations
    Pr {
        #[command(subcommand)]
        action: PrCommands,
    },
    /// Griptree (worktree) operations
    Tree {
        #[command(subcommand)]
        action: TreeCommands,
    },
    /// Run command in each repo
    Forall {
        /// Command to run
        #[arg(short, long)]
        command: String,
    },
    /// Rebase branches across repos
    Rebase {
        /// Target branch
        onto: Option<String>,
    },
    /// Manage file links
    Link {
        /// Show link status
        #[arg(long)]
        status: bool,
    },
    /// Run workspace scripts
    Run {
        /// Script name
        name: Option<String>,
        /// List available scripts
        #[arg(long)]
        list: bool,
    },
    /// Show environment variables
    Env,
    /// Run benchmarks
    Bench {
        /// Specific benchmark to run
        name: Option<String>,
        /// Number of iterations
        #[arg(short, long, default_value = "10")]
        iterations: u32,
    },
    /// Repository operations
    Repo {
        #[command(subcommand)]
        action: RepoCommands,
    },
}

#[derive(Subcommand)]
enum PrCommands {
    /// Create a pull request
    Create {
        /// PR title
        #[arg(short, long)]
        title: Option<String>,
        /// Push before creating
        #[arg(long)]
        push: bool,
        /// Create as draft
        #[arg(long)]
        draft: bool,
    },
    /// Show PR status
    Status,
    /// Merge pull requests
    Merge {
        /// Merge method (merge, squash, rebase)
        #[arg(short, long)]
        method: Option<String>,
    },
    /// Check CI status
    Checks,
    /// Show PR diff
    Diff,
}

#[derive(Subcommand)]
enum TreeCommands {
    /// Add a new griptree
    Add {
        /// Branch name
        branch: String,
    },
    /// List griptrees
    List,
    /// Remove a griptree
    Remove {
        /// Branch name
        branch: String,
        /// Force removal
        #[arg(short, long)]
        force: bool,
    },
    /// Lock a griptree
    Lock {
        /// Branch name
        branch: String,
        /// Lock reason
        #[arg(short, long)]
        reason: Option<String>,
    },
    /// Unlock a griptree
    Unlock {
        /// Branch name
        branch: String,
    },
}

#[derive(Subcommand)]
enum RepoCommands {
    /// List repositories
    List,
    /// Add a repository
    Add {
        /// Repository URL
        url: String,
        /// Local path
        path: Option<String>,
    },
    /// Remove a repository
    Remove {
        /// Repository name
        name: String,
    },
}

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    // Initialize tracing
    tracing_subscriber::fmt()
        .with_env_filter(tracing_subscriber::EnvFilter::from_default_env())
        .init();

    let cli = Cli::parse();

    match cli.command {
        Some(Commands::Status { verbose }) => {
            println!("Status command (verbose: {})", verbose);
            println!("Not yet implemented - Phase 4");
        }
        Some(Commands::Bench { name, iterations }) => {
            run_benchmarks(name.as_deref(), iterations).await?;
        }
        Some(_) => {
            println!("Command not yet implemented");
        }
        None => {
            println!("gitgrip - Multi-repo workflow tool");
            println!("Run 'gr --help' for usage");
        }
    }

    Ok(())
}

async fn run_benchmarks(name: Option<&str>, iterations: u32) -> anyhow::Result<()> {
    use gitgrip::util::timing::{benchmark, BenchmarkResult};

    println!("Running benchmarks (iterations: {})...\n", iterations);

    let mut results: Vec<BenchmarkResult> = Vec::new();

    // Benchmark: Manifest parsing
    if name.is_none() || name == Some("manifest") {
        let yaml = r#"
version: 1
repos:
  app:
    url: git@github.com:user/app.git
    path: app
    default_branch: main
  lib:
    url: git@github.com:user/lib.git
    path: lib
settings:
  pr_prefix: "[multi-repo]"
  merge_strategy: all-or-nothing
"#;
        let result = benchmark("manifest_parse", iterations, || {
            let _ = gitgrip::core::manifest::Manifest::parse(yaml);
        });
        result.print();
        results.push(result);
    }

    // Benchmark: State file parsing
    if name.is_none() || name == Some("state") {
        let json = r#"{
            "currentManifestPr": 42,
            "branchToPr": {"feat/test": 42},
            "prLinks": {"42": []}
        }"#;
        let result = benchmark("state_parse", iterations, || {
            let _ = gitgrip::core::state::StateFile::parse(json);
        });
        result.print();
        results.push(result);
    }

    // Benchmark: URL parsing
    if name.is_none() || name == Some("url") {
        use gitgrip::core::manifest::RepoConfig;
        use gitgrip::core::repo::RepoInfo;
        use std::path::PathBuf;

        let config = RepoConfig {
            url: "git@github.com:user/repo.git".to_string(),
            path: "repo".to_string(),
            default_branch: "main".to_string(),
            copyfile: None,
            linkfile: None,
            platform: None,
        };
        let workspace = PathBuf::from("/workspace");

        let result = benchmark("url_parse", iterations, || {
            let _ = RepoInfo::from_config("repo", &config, &workspace);
        });
        result.print();
        results.push(result);
    }

    // Summary
    println!("\n=== Summary ===");
    for result in &results {
        println!("{}", result.to_comparison_string());
    }

    Ok(())
}
