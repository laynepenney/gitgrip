//! gitgrip CLI entry point

use clap::{CommandFactory, Parser, Subcommand};
use clap_complete::{generate, Shell};

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
        /// Target directory
        #[arg(short, long)]
        path: Option<String>,
        /// Create workspace from existing local directories
        #[arg(long, conflicts_with = "url")]
        from_dirs: bool,
        /// Specific directories to scan (requires --from-dirs)
        #[arg(long, requires = "from_dirs")]
        dirs: Vec<String>,
        /// Interactive mode - preview and confirm before writing
        #[arg(short, long)]
        interactive: bool,
        /// Create manifest repository on detected platform (requires --from-dirs)
        #[arg(long, requires = "from_dirs")]
        create_manifest: bool,
        /// Name for manifest repository (default: workspace-manifest)
        #[arg(long, requires = "create_manifest")]
        manifest_name: Option<String>,
        /// Make manifest repository private (default: false)
        #[arg(long, requires = "create_manifest")]
        private: bool,
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
        /// Run in parallel
        #[arg(short, long)]
        parallel: bool,
        /// Only run in repos with changes
        #[arg(long)]
        changed: bool,
        /// Disable git command interception (use CLI for all commands)
        #[arg(long)]
        no_intercept: bool,
    },
    /// Rebase branches across repos
    Rebase {
        /// Target branch
        onto: Option<String>,
        /// Abort rebase in progress
        #[arg(long)]
        abort: bool,
        /// Continue rebase after resolving conflicts
        #[arg(long, name = "continue")]
        continue_rebase: bool,
    },
    /// Manage file links
    Link {
        /// Show link status
        #[arg(long)]
        status: bool,
        /// Apply/fix links
        #[arg(long)]
        apply: bool,
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
    Bench(gitgrip::cli::commands::bench::BenchArgs),
    /// Repository operations
    Repo {
        #[command(subcommand)]
        action: RepoCommands,
    },
    /// Generate shell completions
    Completions {
        /// Shell to generate completions for
        #[arg(value_enum)]
        shell: Shell,
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
        /// Preview without creating PR
        #[arg(long)]
        dry_run: bool,
    },
    /// Show PR status
    Status {
        /// Output JSON
        #[arg(long)]
        json: bool,
    },
    /// Merge pull requests
    Merge {
        /// Merge method (merge, squash, rebase)
        #[arg(short, long)]
        method: Option<String>,
        /// Force merge without readiness checks
        #[arg(short, long)]
        force: bool,
    },
    /// Check CI status
    Checks {
        /// Output JSON
        #[arg(long)]
        json: bool,
    },
    /// Show PR diff
    Diff {
        /// Show stat summary only
        #[arg(long)]
        stat: bool,
    },
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
        #[arg(short, long)]
        path: Option<String>,
        /// Default branch
        #[arg(short, long)]
        branch: Option<String>,
    },
    /// Remove a repository
    Remove {
        /// Repository name
        name: String,
        /// Delete files from disk
        #[arg(long)]
        delete: bool,
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
            let (workspace_root, manifest) = load_workspace()?;
            gitgrip::cli::commands::status::run_status(&workspace_root, &manifest, verbose)?;
        }
        Some(Commands::Sync { force }) => {
            let (workspace_root, manifest) = load_workspace()?;
            gitgrip::cli::commands::sync::run_sync(&workspace_root, &manifest, force)?;
        }
        Some(Commands::Branch {
            name,
            delete,
            include_manifest: _,
        }) => {
            let (workspace_root, manifest) = load_workspace()?;
            gitgrip::cli::commands::branch::run_branch(
                &workspace_root,
                &manifest,
                name.as_deref(),
                delete,
                None,
            )?;
        }
        Some(Commands::Checkout { name }) => {
            let (workspace_root, manifest) = load_workspace()?;
            gitgrip::cli::commands::checkout::run_checkout(&workspace_root, &manifest, &name)?;
        }
        Some(Commands::Add { files }) => {
            let (workspace_root, manifest) = load_workspace()?;
            gitgrip::cli::commands::add::run_add(&workspace_root, &manifest, &files)?;
        }
        Some(Commands::Diff { staged }) => {
            let (workspace_root, manifest) = load_workspace()?;
            gitgrip::cli::commands::diff::run_diff(&workspace_root, &manifest, staged)?;
        }
        Some(Commands::Commit { message, amend }) => {
            let (workspace_root, manifest) = load_workspace()?;
            let msg = message.unwrap_or_else(|| {
                eprintln!("Error: commit message required (-m)");
                std::process::exit(1);
            });
            gitgrip::cli::commands::commit::run_commit(&workspace_root, &manifest, &msg, amend)?;
        }
        Some(Commands::Push {
            set_upstream,
            force,
        }) => {
            let (workspace_root, manifest) = load_workspace()?;
            gitgrip::cli::commands::push::run_push(
                &workspace_root,
                &manifest,
                set_upstream,
                force,
            )?;
        }
        Some(Commands::Pr { action }) => {
            let (workspace_root, manifest) = load_workspace()?;
            match action {
                PrCommands::Create {
                    title,
                    push,
                    draft,
                    dry_run,
                } => {
                    gitgrip::cli::commands::pr::run_pr_create(
                        &workspace_root,
                        &manifest,
                        title.as_deref(),
                        draft,
                        push,
                        dry_run,
                    )
                    .await?;
                }
                PrCommands::Status { json } => {
                    gitgrip::cli::commands::pr::run_pr_status(&workspace_root, &manifest, json)
                        .await?;
                }
                PrCommands::Merge { method, force } => {
                    gitgrip::cli::commands::pr::run_pr_merge(
                        &workspace_root,
                        &manifest,
                        method.as_deref(),
                        force,
                    )
                    .await?;
                }
                PrCommands::Checks { json } => {
                    gitgrip::cli::commands::pr::run_pr_checks(&workspace_root, &manifest, json)
                        .await?;
                }
                PrCommands::Diff { stat } => {
                    gitgrip::cli::commands::pr::run_pr_diff(&workspace_root, &manifest, stat)
                        .await?;
                }
            }
        }
        Some(Commands::Init {
            url,
            path,
            from_dirs,
            dirs,
            interactive,
            create_manifest,
            manifest_name,
            private,
        }) => {
            gitgrip::cli::commands::init::run_init(
                url.as_deref(),
                path.as_deref(),
                from_dirs,
                &dirs,
                interactive,
                create_manifest,
                manifest_name.as_deref(),
                private,
            )
            .await?;
        }
        Some(Commands::Tree { action }) => {
            let (workspace_root, manifest) = load_workspace()?;
            match action {
                TreeCommands::Add { branch } => {
                    gitgrip::cli::commands::tree::run_tree_add(
                        &workspace_root,
                        &manifest,
                        &branch,
                    )?;
                }
                TreeCommands::List => {
                    gitgrip::cli::commands::tree::run_tree_list(&workspace_root)?;
                }
                TreeCommands::Remove { branch, force } => {
                    gitgrip::cli::commands::tree::run_tree_remove(&workspace_root, &branch, force)?;
                }
                TreeCommands::Lock { branch, reason } => {
                    gitgrip::cli::commands::tree::run_tree_lock(
                        &workspace_root,
                        &branch,
                        reason.as_deref(),
                    )?;
                }
                TreeCommands::Unlock { branch } => {
                    gitgrip::cli::commands::tree::run_tree_unlock(&workspace_root, &branch)?;
                }
            }
        }
        Some(Commands::Forall {
            command,
            parallel,
            changed,
            no_intercept,
        }) => {
            let (workspace_root, manifest) = load_workspace()?;
            gitgrip::cli::commands::forall::run_forall(
                &workspace_root,
                &manifest,
                &command,
                parallel,
                changed,
                no_intercept,
            )?;
        }
        Some(Commands::Rebase {
            onto,
            abort,
            continue_rebase,
        }) => {
            let (workspace_root, manifest) = load_workspace()?;
            gitgrip::cli::commands::rebase::run_rebase(
                &workspace_root,
                &manifest,
                onto.as_deref(),
                abort,
                continue_rebase,
            )?;
        }
        Some(Commands::Link { status, apply }) => {
            let (workspace_root, manifest) = load_workspace()?;
            gitgrip::cli::commands::link::run_link(&workspace_root, &manifest, status, apply)?;
        }
        Some(Commands::Run { name, list }) => {
            let (workspace_root, manifest) = load_workspace()?;
            gitgrip::cli::commands::run::run_run(
                &workspace_root,
                &manifest,
                name.as_deref(),
                list,
            )?;
        }
        Some(Commands::Env) => {
            let (workspace_root, manifest) = load_workspace()?;
            gitgrip::cli::commands::env::run_env(&workspace_root, &manifest)?;
        }
        Some(Commands::Repo { action }) => {
            let (workspace_root, manifest) = load_workspace()?;
            match action {
                RepoCommands::List => {
                    gitgrip::cli::commands::repo::run_repo_list(&workspace_root, &manifest)?;
                }
                RepoCommands::Add { url, path, branch } => {
                    gitgrip::cli::commands::repo::run_repo_add(
                        &workspace_root,
                        &url,
                        path.as_deref(),
                        branch.as_deref(),
                    )?;
                }
                RepoCommands::Remove { name, delete } => {
                    gitgrip::cli::commands::repo::run_repo_remove(&workspace_root, &name, delete)?;
                }
            }
        }
        Some(Commands::Bench(args)) => {
            gitgrip::cli::commands::bench::run(args).await?;
        }
        Some(Commands::Completions { shell }) => {
            let mut cmd = Cli::command();
            generate(shell, &mut cmd, "gr", &mut std::io::stdout());
        }
        None => {
            println!("gitgrip - Multi-repo workflow tool");
            println!("Run 'gr --help' for usage");
        }
    }

    Ok(())
}

/// Load the workspace manifest
fn load_workspace() -> anyhow::Result<(std::path::PathBuf, gitgrip::core::manifest::Manifest)> {
    let current = std::env::current_dir()?;

    // First, check if we're in a griptree (has .griptree pointer file)
    if let Some((griptree_path, pointer)) =
        gitgrip::core::griptree::GriptreePointer::find_in_ancestors(&current)
    {
        // We're in a griptree - prioritize loading manifest from griptree's own manifests directory
        // Fall back to main workspace if griptree doesn't have its own manifest
        let griptree_manifest_path = griptree_path
            .join(".gitgrip")
            .join("manifests")
            .join("manifest.yaml");

        let content = if griptree_manifest_path.exists() {
            std::fs::read_to_string(&griptree_manifest_path)?
        } else {
            // Fall back to main workspace's manifest
            let main_workspace = std::path::PathBuf::from(&pointer.main_workspace);
            let main_manifest_path = main_workspace
                .join(".gitgrip")
                .join("manifests")
                .join("manifest.yaml");

            if !main_manifest_path.exists() {
                anyhow::bail!(
                    "Griptree points to main workspace '{}' but manifest not found at '{}' or '{}'",
                    pointer.main_workspace,
                    griptree_manifest_path.display(),
                    main_manifest_path.display()
                );
            }
            std::fs::read_to_string(&main_manifest_path)?
        };

        let manifest = gitgrip::core::manifest::Manifest::parse(&content)?;
        // Return griptree path as workspace root - repos are located here, not in main workspace
        return Ok((griptree_path, manifest));
    }

    // Not in a griptree - find workspace root by looking for .gitgrip directory
    let mut search_path = current;
    loop {
        let gitgrip_dir = search_path.join(".gitgrip");
        if gitgrip_dir.exists() {
            let manifest_path = gitgrip_dir.join("manifests").join("manifest.yaml");
            if manifest_path.exists() {
                let content = std::fs::read_to_string(&manifest_path)?;
                let manifest = gitgrip::core::manifest::Manifest::parse(&content)?;
                return Ok((search_path, manifest));
            }
        }

        match search_path.parent() {
            Some(parent) => search_path = parent.to_path_buf(),
            None => {
                anyhow::bail!("Not in a gitgrip workspace (no .gitgrip directory found)");
            }
        }
    }
}
