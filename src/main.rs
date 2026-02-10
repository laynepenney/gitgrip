//! gitgrip CLI entry point

use clap::{CommandFactory, Parser, Subcommand};
use clap_complete::{generate, Shell};

#[derive(Parser)]
#[command(name = "gr")]
#[command(author, version, about = "Multi-repo workflow tool", long_about = None)]
struct Cli {
    /// Suppress output for repos with no relevant changes (saves tokens for AI tools)
    #[arg(short, long, global = true)]
    quiet: bool,

    /// Show verbose output including external commands being executed
    #[arg(short, long, global = true)]
    verbose: bool,

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
        #[arg(long, conflicts_with_all = ["url", "from_repo"])]
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
        /// Initialize from existing .repo/ directory (git-repo coexistence)
        #[arg(long, conflicts_with_all = ["from_dirs", "url"])]
        from_repo: bool,
    },
    /// Sync all repositories
    Sync {
        /// Force sync even with local changes
        #[arg(short, long)]
        force: bool,
        /// Hard reset reference repos to upstream (discard local changes)
        #[arg(long, alias = "reset-ref")]
        reset_refs: bool,
        /// Only sync repos in these groups
        #[arg(long, value_delimiter = ',')]
        group: Option<Vec<String>>,
        /// Sync repos sequentially (default: parallel)
        #[arg(long)]
        sequential: bool,
    },
    /// Show status of all repositories
    Status {
        /// Show detailed status
        #[arg(short, long)]
        verbose: bool,
        /// Only show repos in these groups
        #[arg(long, value_delimiter = ',')]
        group: Option<Vec<String>>,
        /// Output JSON (machine-readable)
        #[arg(long)]
        json: bool,
    },
    /// Create or switch branches across repos
    Branch {
        /// Branch name
        name: Option<String>,
        /// Delete branch
        #[arg(short, long)]
        delete: bool,
        /// Move recent commits to new branch (resets current branch to remote)
        #[arg(short, long)]
        r#move: bool,
        /// Only operate on specific repos
        #[arg(long, value_delimiter = ',')]
        repo: Option<Vec<String>>,
        /// Include manifest repo
        #[arg(long)]
        include_manifest: bool,
        /// Only operate on repos in these groups
        #[arg(long, value_delimiter = ',')]
        group: Option<Vec<String>>,
        /// Output JSON (machine-readable, list mode only)
        #[arg(long)]
        json: bool,
    },
    /// Checkout a branch across repos
    Checkout {
        /// Branch name
        name: Option<String>,
        /// Create branch if it doesn't exist
        #[arg(short = 'b', long)]
        create: bool,
        /// Checkout the griptree base branch for this worktree
        #[arg(long, conflicts_with = "create")]
        base: bool,
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
        /// Output JSON (machine-readable)
        #[arg(long)]
        json: bool,
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
    /// Clean up merged branches across repos
    Prune {
        /// Actually delete branches (default: dry-run)
        #[arg(long)]
        execute: bool,
        /// Also prune remote tracking refs
        #[arg(long)]
        remote: bool,
        /// Only prune repos in these groups
        #[arg(long, value_delimiter = ',')]
        group: Option<Vec<String>>,
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
    /// Search across all repos using git grep
    Grep {
        /// Search pattern
        pattern: String,
        /// Case insensitive
        #[arg(short = 'i', long)]
        ignore_case: bool,
        /// Run in parallel
        #[arg(short, long)]
        parallel: bool,
        /// File pattern (after --)
        #[arg(last = true)]
        pathspec: Vec<String>,
        /// Only search repos in these groups
        #[arg(long, value_delimiter = ',')]
        group: Option<Vec<String>>,
    },
    /// Run command in each repo
    Forall {
        /// Command to run
        #[arg(short, long)]
        command: String,
        /// Run in parallel
        #[arg(short, long)]
        parallel: bool,
        /// Run in ALL repos (default: only repos with changes)
        #[arg(short, long)]
        all: bool,
        /// Disable git command interception (use CLI for all commands)
        #[arg(long)]
        no_intercept: bool,
        /// Only run in repos in these groups
        #[arg(long, value_delimiter = ',')]
        group: Option<Vec<String>>,
    },
    /// Rebase branches across repos
    Rebase {
        /// Target branch
        onto: Option<String>,
        /// Use upstream tracking branch when no target is provided
        #[arg(long)]
        upstream: bool,
        /// Abort rebase in progress
        #[arg(long)]
        abort: bool,
        /// Continue rebase after resolving conflicts
        #[arg(long, name = "continue")]
        continue_rebase: bool,
    },
    /// Pull latest changes across repos
    Pull {
        /// Rebase instead of merge
        #[arg(long)]
        rebase: bool,
        /// Only pull repos in these groups
        #[arg(long, value_delimiter = ',')]
        group: Option<Vec<String>>,
        /// Sync repos sequentially (default: parallel)
        #[arg(long)]
        sequential: bool,
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
    /// Repository group operations
    Group {
        #[command(subcommand)]
        action: GroupCommands,
    },
    /// Run garbage collection across repos
    Gc {
        /// More thorough gc (slower)
        #[arg(long)]
        aggressive: bool,
        /// Only report .git sizes, don't gc
        #[arg(long)]
        dry_run: bool,
        /// Only operate on specific repos
        #[arg(long, value_delimiter = ',')]
        repo: Option<Vec<String>>,
        /// Only gc repos in these groups
        #[arg(long, value_delimiter = ',')]
        group: Option<Vec<String>>,
    },
    /// Cherry-pick commits across repos
    CherryPick {
        /// Commit SHA to cherry-pick
        #[arg(conflicts_with_all = ["abort", "continue"])]
        commit: Option<String>,
        /// Abort in-progress cherry-pick
        #[arg(long, conflicts_with = "continue")]
        abort: bool,
        /// Continue after conflict resolution
        #[arg(long, name = "continue", conflicts_with = "abort")]
        continue_pick: bool,
        /// Only operate on specific repos
        #[arg(long, value_delimiter = ',')]
        repo: Option<Vec<String>>,
        /// Only operate on repos in these groups
        #[arg(long, value_delimiter = ',')]
        group: Option<Vec<String>>,
    },
    /// CI/CD pipeline operations
    Ci {
        #[command(subcommand)]
        action: CiCommands,
    },
    /// Manifest operations (import, sync)
    Manifest {
        #[command(subcommand)]
        action: ManifestCommands,
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
        /// PR body/description
        #[arg(short, long)]
        body: Option<String>,
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
        /// Update branch from base if behind before merging
        #[arg(short = 'u', long)]
        update: bool,
        /// Enable auto-merge (merges when all checks pass)
        #[arg(long)]
        auto: bool,
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
    /// Return to the griptree base branch, sync, and optionally prune a branch
    Return {
        /// Override base branch (defaults to griptree config)
        #[arg(long)]
        base: Option<String>,
        /// Skip syncing after checkout
        #[arg(long)]
        no_sync: bool,
        /// Stash and restore local changes automatically
        #[arg(long)]
        autostash: bool,
        /// Prune this branch after returning
        #[arg(long)]
        prune: Option<String>,
        /// Prune the current branch (pre-return) after returning
        #[arg(long, conflicts_with = "prune")]
        prune_current: bool,
        /// Also prune the remote branch (origin)
        #[arg(long)]
        prune_remote: bool,
        /// Force delete local branches even if not merged
        #[arg(short, long)]
        force: bool,
    },
}

#[derive(Subcommand)]
enum GroupCommands {
    /// List all groups and their repos
    List,
    /// Add repo(s) to a group
    Add {
        /// Group name
        group: String,
        /// Repository names
        #[arg(required = true)]
        repos: Vec<String>,
    },
    /// Remove repo(s) from a group
    Remove {
        /// Group name
        group: String,
        /// Repository names
        #[arg(required = true)]
        repos: Vec<String>,
    },
    /// Create a new empty group (for documentation purposes)
    Create {
        /// Group name
        name: String,
    },
}

#[derive(Subcommand)]
enum CiCommands {
    /// Run a CI pipeline
    Run {
        /// Pipeline name
        name: String,
        /// Output JSON
        #[arg(long)]
        json: bool,
    },
    /// List available pipelines
    List {
        /// Output JSON
        #[arg(long)]
        json: bool,
    },
    /// Show status of last CI runs
    Status {
        /// Output JSON
        #[arg(long)]
        json: bool,
    },
}

#[derive(Subcommand)]
enum ManifestCommands {
    /// Convert git-repo XML manifest to gitgrip YAML
    Import {
        /// Path to XML manifest (e.g., .repo/manifests/default.xml)
        path: String,
        /// Output path for YAML manifest
        #[arg(short, long)]
        output: Option<String>,
    },
    /// Re-sync gitgrip YAML from .repo/ manifest after repo sync
    Sync,
    /// Show manifest schema specification
    Schema {
        /// Output format (yaml, json, markdown)
        #[arg(long, default_value = "yaml")]
        format: String,
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
    let cli = Cli::parse();

    // Initialize tracing — `--verbose` enables debug logging for gitgrip
    if cli.verbose {
        tracing_subscriber::fmt()
            .with_env_filter("gitgrip=debug")
            .with_target(false)
            .init();
    } else {
        tracing_subscriber::fmt()
            .with_env_filter(tracing_subscriber::EnvFilter::from_default_env())
            .init();
    }

    match cli.command {
        Some(Commands::Status {
            verbose,
            group,
            json,
        }) => {
            let (workspace_root, manifest) = load_gripspace()?;
            gitgrip::cli::commands::status::run_status(
                &workspace_root,
                &manifest,
                verbose,
                cli.quiet,
                group.as_deref(),
                json,
            )?;
        }
        Some(Commands::Sync {
            force,
            reset_refs,
            group,
            sequential,
        }) => {
            let (workspace_root, manifest) = load_gripspace()?;
            gitgrip::cli::commands::sync::run_sync(
                &workspace_root,
                &manifest,
                force,
                cli.quiet,
                group.as_deref(),
                sequential,
                reset_refs,
            )
            .await?;
        }
        Some(Commands::Branch {
            name,
            delete,
            r#move,
            repo,
            include_manifest: _,
            group,
            json,
        }) => {
            let (workspace_root, manifest) = load_gripspace()?;
            gitgrip::cli::commands::branch::run_branch(
                gitgrip::cli::commands::branch::BranchOptions {
                    workspace_root: &workspace_root,
                    manifest: &manifest,
                    name: name.as_deref(),
                    delete,
                    move_commits: r#move,
                    repos_filter: repo.as_deref(),
                    group_filter: group.as_deref(),
                    json,
                },
            )?;
        }
        Some(Commands::Checkout { name, create, base }) => {
            let (workspace_root, manifest) = load_gripspace()?;
            let branch = if base {
                let config =
                    gitgrip::core::griptree::GriptreeConfig::load_from_workspace(&workspace_root)?
                        .ok_or_else(|| anyhow::anyhow!("Not in a griptree workspace"))?;
                config.branch
            } else {
                name.ok_or_else(|| anyhow::anyhow!("Branch name is required"))?
            };

            gitgrip::cli::commands::checkout::run_checkout(
                &workspace_root,
                &manifest,
                &branch,
                create,
            )?;
        }
        Some(Commands::Add { files }) => {
            let (workspace_root, manifest) = load_gripspace()?;
            gitgrip::cli::commands::add::run_add(&workspace_root, &manifest, &files)?;
        }
        Some(Commands::Diff { staged, json }) => {
            let (workspace_root, manifest) = load_gripspace()?;
            gitgrip::cli::commands::diff::run_diff(&workspace_root, &manifest, staged, json)?;
        }
        Some(Commands::Commit { message, amend }) => {
            let (workspace_root, manifest) = load_gripspace()?;
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
            let (workspace_root, manifest) = load_gripspace()?;
            gitgrip::cli::commands::push::run_push(
                &workspace_root,
                &manifest,
                set_upstream,
                force,
                cli.quiet,
            )?;
        }
        Some(Commands::Prune {
            execute,
            remote,
            group,
        }) => {
            let (workspace_root, manifest) = load_gripspace()?;
            gitgrip::cli::commands::prune::run_prune(
                &workspace_root,
                &manifest,
                execute,
                remote,
                group.as_deref(),
            )?;
        }
        Some(Commands::Pr { action }) => {
            let (workspace_root, manifest) = load_gripspace()?;
            match action {
                PrCommands::Create {
                    title,
                    body,
                    push,
                    draft,
                    dry_run,
                } => {
                    gitgrip::cli::commands::pr::run_pr_create(
                        &workspace_root,
                        &manifest,
                        title.as_deref(),
                        body.as_deref(),
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
                PrCommands::Merge {
                    method,
                    force,
                    update,
                    auto,
                } => {
                    gitgrip::cli::commands::pr::run_pr_merge(
                        &workspace_root,
                        &manifest,
                        method.as_deref(),
                        force,
                        update,
                        auto,
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
            from_repo,
        }) => {
            gitgrip::cli::commands::init::run_init(gitgrip::cli::commands::init::InitOptions {
                url: url.as_deref(),
                path: path.as_deref(),
                from_dirs,
                dirs: &dirs,
                interactive,
                create_manifest,
                manifest_name: manifest_name.as_deref(),
                private,
                from_repo,
            })
            .await?;
        }
        Some(Commands::Tree { action }) => {
            let (workspace_root, manifest) = load_gripspace()?;
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
                TreeCommands::Return {
                    base,
                    no_sync,
                    autostash,
                    prune,
                    prune_current,
                    prune_remote,
                    force,
                } => {
                    gitgrip::cli::commands::tree::run_tree_return(
                        &workspace_root,
                        &manifest,
                        base.as_deref(),
                        no_sync,
                        autostash,
                        prune.as_deref(),
                        prune_current,
                        prune_remote,
                        force,
                    )
                    .await?;
                }
            }
        }
        Some(Commands::Grep {
            pattern,
            ignore_case,
            parallel,
            pathspec,
            group,
        }) => {
            let (workspace_root, manifest) = load_gripspace()?;
            gitgrip::cli::commands::grep::run_grep(
                &workspace_root,
                &manifest,
                &pattern,
                ignore_case,
                parallel,
                &pathspec,
                group.as_deref(),
            )?;
        }
        Some(Commands::Forall {
            command,
            parallel,
            all,
            no_intercept,
            group,
        }) => {
            let (workspace_root, manifest) = load_gripspace()?;
            gitgrip::cli::commands::forall::run_forall(
                &workspace_root,
                &manifest,
                &command,
                parallel,
                !all, // Default: only repos with changes (changed_only=true unless --all)
                no_intercept,
                group.as_deref(),
            )?;
        }
        Some(Commands::Rebase {
            onto,
            upstream,
            abort,
            continue_rebase,
        }) => {
            let (workspace_root, manifest) = load_gripspace()?;
            gitgrip::cli::commands::rebase::run_rebase(
                &workspace_root,
                &manifest,
                onto.as_deref(),
                upstream,
                abort,
                continue_rebase,
            )?;
        }
        Some(Commands::Pull {
            rebase,
            group,
            sequential,
        }) => {
            let (workspace_root, manifest) = load_gripspace()?;
            gitgrip::cli::commands::pull::run_pull(
                &workspace_root,
                &manifest,
                rebase,
                group.as_deref(),
                sequential,
                cli.quiet,
            )
            .await?;
        }
        Some(Commands::Link { status, apply }) => {
            let (workspace_root, manifest) = load_gripspace()?;
            gitgrip::cli::commands::link::run_link(&workspace_root, &manifest, status, apply)?;
        }
        Some(Commands::Run { name, list }) => {
            let (workspace_root, manifest) = load_gripspace()?;
            gitgrip::cli::commands::run::run_run(
                &workspace_root,
                &manifest,
                name.as_deref(),
                list,
            )?;
        }
        Some(Commands::Env) => {
            let (workspace_root, manifest) = load_gripspace()?;
            gitgrip::cli::commands::env::run_env(&workspace_root, &manifest)?;
        }
        Some(Commands::Repo { action }) => {
            let (workspace_root, manifest) = load_gripspace()?;
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
        Some(Commands::Group { action }) => {
            let (workspace_root, manifest) = load_gripspace()?;
            match action {
                GroupCommands::List => {
                    gitgrip::cli::commands::group::run_group_list(&workspace_root, &manifest)?;
                }
                GroupCommands::Add { group, repos } => {
                    gitgrip::cli::commands::group::run_group_add(&workspace_root, &group, &repos)?;
                }
                GroupCommands::Remove { group, repos } => {
                    gitgrip::cli::commands::group::run_group_remove(
                        &workspace_root,
                        &group,
                        &repos,
                    )?;
                }
                GroupCommands::Create { name } => {
                    gitgrip::cli::commands::group::run_group_create(&workspace_root, &name)?;
                }
            }
        }
        Some(Commands::Gc {
            aggressive,
            dry_run,
            repo,
            group,
        }) => {
            let (workspace_root, manifest) = load_gripspace()?;
            gitgrip::cli::commands::gc::run_gc(
                &workspace_root,
                &manifest,
                aggressive,
                dry_run,
                repo.as_deref(),
                group.as_deref(),
            )?;
        }
        Some(Commands::CherryPick {
            commit,
            abort,
            continue_pick,
            repo,
            group,
        }) => {
            let (workspace_root, manifest) = load_gripspace()?;
            gitgrip::cli::commands::cherry_pick::run_cherry_pick(
                &workspace_root,
                &manifest,
                commit.as_deref(),
                abort,
                continue_pick,
                repo.as_deref(),
                group.as_deref(),
            )?;
        }
        Some(Commands::Ci { action }) => {
            let (workspace_root, manifest) = load_gripspace()?;
            match action {
                CiCommands::Run { name, json } => {
                    gitgrip::cli::commands::ci::run_ci_run(
                        &workspace_root,
                        &manifest,
                        &name,
                        json,
                    )?;
                }
                CiCommands::List { json } => {
                    gitgrip::cli::commands::ci::run_ci_list(&manifest, json)?;
                }
                CiCommands::Status { json } => {
                    gitgrip::cli::commands::ci::run_ci_status(&workspace_root, json)?;
                }
            }
        }
        Some(Commands::Manifest { action }) => match action {
            ManifestCommands::Import { path, output } => {
                gitgrip::cli::commands::manifest::run_manifest_import(&path, output.as_deref())?;
            }
            ManifestCommands::Sync => {
                let (workspace_root, _manifest) = load_gripspace()?;
                gitgrip::cli::commands::manifest::run_manifest_sync(&workspace_root)?;
            }
            ManifestCommands::Schema { format } => {
                gitgrip::cli::commands::manifest::run_manifest_schema(&format)?;
            }
        },
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

/// Load the gripspace manifest
fn load_gripspace() -> anyhow::Result<(std::path::PathBuf, gitgrip::core::manifest::Manifest)> {
    let current = std::env::current_dir()?;

    // First, check if we're in a griptree (has .griptree pointer file)
    if let Some((griptree_path, pointer)) =
        gitgrip::core::griptree::GriptreePointer::find_in_ancestors(&current)
    {
        // In a griptree: prefer griptree-local space manifest, then fall back to main workspace.
        let griptree_manifest_path =
            gitgrip::core::manifest_paths::resolve_gripspace_manifest_path(&griptree_path);

        let content = if let Some(path) = griptree_manifest_path {
            std::fs::read_to_string(path)?
        } else {
            let main_workspace = std::path::PathBuf::from(&pointer.main_workspace);
            let main_manifest_path =
                gitgrip::core::manifest_paths::resolve_gripspace_manifest_path(&main_workspace);

            let main_path = main_manifest_path.ok_or_else(|| {
                anyhow::anyhow!(
                    "Griptree points to main workspace '{}' but no gripspace manifest was found",
                    pointer.main_workspace
                )
            })?;
            std::fs::read_to_string(main_path)?
        };

        let mut manifest = gitgrip::core::manifest::Manifest::parse(&content)?;
        // Resolve gripspace includes (merge inherited repos/scripts/env/hooks)
        let spaces_dir = gitgrip::core::manifest_paths::spaces_dir(&griptree_path);
        if spaces_dir.exists() {
            let _ = gitgrip::core::gripspace::resolve_all_gripspaces(&mut manifest, &spaces_dir);
        }
        // Return griptree path as workspace root - repos are located here, not in main workspace
        return Ok((griptree_path, manifest));
    }

    // Not in a griptree - find workspace root by looking for .gitgrip or .repo directory
    let mut search_path = current;
    loop {
        let gitgrip_dir = search_path.join(".gitgrip");
        if gitgrip_dir.exists() {
            if let Some(manifest_path) =
                gitgrip::core::manifest_paths::resolve_gripspace_manifest_path(&search_path)
            {
                let content = std::fs::read_to_string(&manifest_path)?;
                let mut manifest = gitgrip::core::manifest::Manifest::parse(&content)?;
                // Resolve gripspace includes (merge inherited repos/scripts/env/hooks)
                let spaces_dir = gitgrip::core::manifest_paths::spaces_dir(&search_path);
                if spaces_dir.exists() {
                    let _ = gitgrip::core::gripspace::resolve_all_gripspaces(
                        &mut manifest,
                        &spaces_dir,
                    );
                }
                return Ok((search_path, manifest));
            }
        }

        if let Some(repo_yaml) =
            gitgrip::core::manifest_paths::resolve_repo_manifest_path(&search_path)
        {
            let content = std::fs::read_to_string(repo_yaml)?;
            let mut manifest = gitgrip::core::manifest::Manifest::parse(&content)?;
            // Resolve gripspace includes (merge inherited repos/scripts/env/hooks)
            let spaces_dir = gitgrip::core::manifest_paths::spaces_dir(&search_path);
            if spaces_dir.exists() {
                let _ =
                    gitgrip::core::gripspace::resolve_all_gripspaces(&mut manifest, &spaces_dir);
            }
            return Ok((search_path, manifest));
        }

        // Fallback: parse .repo/manifest.xml directly (zero-config — just works)
        let repo_xml = search_path.join(".repo").join("manifest.xml");
        if repo_xml.exists() {
            let xml_manifest = gitgrip::core::repo_manifest::XmlManifest::parse_file(&repo_xml)?;
            let result = xml_manifest.to_manifest()?;
            return Ok((search_path, result.manifest));
        }

        match search_path.parent() {
            Some(parent) => search_path = parent.to_path_buf(),
            None => {
                anyhow::bail!("Not in a gitgrip workspace (no .gitgrip or .repo directory found)");
            }
        }
    }
}
