# gitgrip Rust Implementation

A Rust rewrite of gitgrip for improved performance. This implementation is being developed alongside the TypeScript version until feature parity is achieved.

## Quick Start

```bash
# Build
cargo build --release

# Run
./target/release/gr --help

# Run tests
cargo test

# Run benchmarks
cargo bench
```

## Features

All core gitgrip commands are implemented:

| Command | Status | Description |
|---------|--------|-------------|
| `gr init` | Complete | Initialize workspace from manifest URL |
| `gr sync` | Complete | Sync all repositories |
| `gr status` | Complete | Show status of all repos |
| `gr branch` | Complete | Create/delete branches across repos |
| `gr checkout` | Complete | Switch branches across repos |
| `gr add` | Complete | Stage changes across repos |
| `gr diff` | Complete | Show diff across repos |
| `gr commit` | Complete | Commit changes across repos |
| `gr push` | Complete | Push changes across repos |
| `gr pr create` | Complete | Create linked PRs |
| `gr pr status` | Complete | Show PR status |
| `gr pr merge` | Complete | Merge linked PRs |
| `gr pr checks` | Complete | Show CI check status |
| `gr pr diff` | Complete | Show PR diff |
| `gr tree add/list/remove` | Complete | Griptree (worktree) management |
| `gr forall` | Complete | Run command in each repo |
| `gr rebase` | Complete | Rebase across repos |
| `gr link` | Complete | Manage file links |
| `gr run` | Complete | Run workspace scripts |
| `gr env` | Complete | Show environment variables |
| `gr repo list/add/remove` | Complete | Manage repositories |
| `gr bench` | Complete | Run benchmarks |

## Project Structure

```
rust/
├── Cargo.toml              # Dependencies and build config
├── src/
│   ├── main.rs             # CLI entry point (clap)
│   ├── lib.rs              # Library root
│   ├── cli/
│   │   ├── mod.rs          # CLI module
│   │   ├── output.rs       # Colored output, spinners
│   │   └── commands/       # Command implementations
│   │       ├── add.rs
│   │       ├── branch.rs
│   │       ├── checkout.rs
│   │       ├── commit.rs
│   │       ├── diff.rs
│   │       ├── env.rs
│   │       ├── forall.rs
│   │       ├── init.rs
│   │       ├── link.rs
│   │       ├── pr/         # PR subcommands
│   │       ├── push.rs
│   │       ├── rebase.rs
│   │       ├── repo.rs
│   │       ├── run.rs
│   │       ├── status.rs
│   │       ├── sync.rs
│   │       └── tree.rs
│   ├── core/               # Business logic
│   │   ├── manifest.rs     # Manifest parsing
│   │   ├── state.rs        # State file
│   │   ├── repo.rs         # Repository info
│   │   └── griptree.rs     # Worktree config
│   ├── git/                # Git operations (git2)
│   │   ├── status.rs
│   │   ├── branch.rs
│   │   ├── remote.rs
│   │   └── cache.rs
│   ├── platform/           # Hosting platforms
│   │   ├── github.rs
│   │   ├── gitlab.rs       # Placeholder
│   │   └── azure.rs        # Placeholder
│   ├── files/              # File operations
│   └── util/               # Utilities
├── benches/
│   └── benchmarks.rs       # Criterion benchmarks
├── tests/                  # Integration tests
└── benchmark-results/      # Comparison reports
```

## Performance

The Rust implementation is significantly faster than TypeScript:

| Benchmark | TypeScript | Rust | Speedup |
|-----------|-----------|------|---------|
| manifest_parse | 0.431ms | 0.023ms | **~19x** |
| state_parse | 0.002ms | 0.001ms | ~1.5x |
| startup time | ~150ms | ~5ms | **~30x** |

See [benchmark-results/COMPARISON-REPORT.md](benchmark-results/COMPARISON-REPORT.md) for details.

### Running Benchmarks

```bash
# Full comparison (Rust + TypeScript)
./run-benchmarks.sh 100

# Rust only (Criterion)
cargo bench

# Rust CLI benchmarks
./target/release/gr bench -n 100

# TypeScript only
npx tsx bench-compare.ts 100
```

## Development

### Prerequisites

- Rust 1.75+ (for async traits)
- libgit2 (for git2 crate)

### Building

```bash
# Debug build
cargo build

# Release build (optimized)
cargo build --release

# Check without building
cargo check
```

### Testing

```bash
# Run all tests
cargo test

# Run specific test
cargo test test_manifest_parse

# Run with output
cargo test -- --nocapture
```

### Code Style

```bash
# Format code
cargo fmt

# Lint
cargo clippy
```

## Dependencies

| Crate | Version | Purpose |
|-------|---------|---------|
| tokio | 1.x | Async runtime |
| clap | 4.x | CLI parsing |
| serde | 1.x | Serialization |
| serde_yaml | 0.9 | YAML parsing |
| serde_json | 1.x | JSON parsing |
| git2 | 0.18 | Git operations |
| octocrab | 0.41 | GitHub API |
| reqwest | 0.12 | HTTP client |
| colored | 2.x | Terminal colors |
| indicatif | 0.17 | Progress bars |
| anyhow | 1.x | Error handling |
| thiserror | 2.x | Custom errors |
| chrono | 0.4 | Date/time |
| regex | 1.x | Regex matching |
| tracing | 0.1 | Logging |

## Migration Status

- [x] Phase 1: Foundation (manifest, state, repo types)
- [x] Phase 2: Git Operations (status, branch, remote)
- [x] Phase 3: Platform Adapters (GitHub complete, GitLab/Azure placeholders)
- [x] Phase 4: Core CLI Commands (status, sync, branch, checkout, add, diff, commit, push)
- [x] Phase 5: PR Workflow (create, status, merge, checks, diff)
- [x] Phase 6: Advanced Commands (init, tree, forall, rebase, link, run, env, repo)
- [x] Phase 7: Tests and Documentation (71 tests, benchmarks, README)

## Known Limitations

1. **GitLab/Azure DevOps**: Platform adapters are placeholders (GitHub only for now)
2. **Interactive prompts**: Some features that require user input use basic stdin
3. **Windows**: Not fully tested on Windows (symlink handling may differ)

## Contributing

1. Create a branch: `gr branch feat/my-feature`
2. Make changes and test: `cargo test`
3. Format and lint: `cargo fmt && cargo clippy`
4. Commit: `gr commit -m "feat: description"`
5. Create PR: `gr pr create -t "feat: description" --push`
