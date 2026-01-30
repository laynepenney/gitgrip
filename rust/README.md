# gitgrip Rust Implementation

A high-performance Rust implementation of gitgrip, the multi-repo workflow tool. This version achieves feature parity with the TypeScript implementation while providing significant performance improvements.

## Installation

### From Source

```bash
# Clone and build
git clone https://github.com/laynepenney/gitgrip.git
cd gitgrip/rust
cargo build --release

# Install to ~/.cargo/bin
cargo install --path .
```

### From crates.io (coming soon)

```bash
cargo install gitgrip
```

### From GitHub Releases (coming soon)

Pre-built binaries for Linux, macOS, and Windows will be available on the [releases page](https://github.com/laynepenney/gitgrip/releases).

## Quick Start

```bash
# Initialize a workspace from a manifest
gr init https://github.com/org/manifest.git

# Check status of all repos
gr status

# Create a branch across all repos
gr branch feat/my-feature

# Make changes, then commit and push
gr add .
gr commit -m "feat: add new feature"
gr push -u

# Create linked PRs
gr pr create -t "feat: add new feature"
```

## Commands

All gitgrip commands are fully implemented:

| Command | Description |
|---------|-------------|
| `gr init <url>` | Initialize workspace from manifest URL |
| `gr sync` | Sync all repositories |
| `gr status` | Show status of all repos |
| `gr branch <name>` | Create/delete branches across repos |
| `gr checkout <name>` | Switch branches across repos |
| `gr add <files>` | Stage changes across repos |
| `gr diff` | Show diff across repos |
| `gr commit -m <msg>` | Commit changes across repos |
| `gr push [-u] [-f]` | Push changes (with upstream/force options) |
| `gr pr create` | Create linked PRs |
| `gr pr status` | Show PR status |
| `gr pr merge` | Merge linked PRs |
| `gr pr checks` | Show CI check status |
| `gr pr diff` | Show PR diff |
| `gr tree add/list/remove` | Griptree (worktree) management |
| `gr forall -c <cmd>` | Run command in each repo |
| `gr rebase` | Rebase across repos |
| `gr link` | Manage file links |
| `gr run <script>` | Run workspace scripts |
| `gr env` | Show environment variables |
| `gr repo list/add/remove` | Manage repositories |
| `gr bench` | Run performance benchmarks |

## Platform Support

gitgrip supports multiple git hosting platforms:

| Platform | Status | Features |
|----------|--------|----------|
| **GitHub** | Full | PRs, reviews, checks, merge |
| **GitLab** | Full | MRs, approvals, pipelines, merge |
| **Azure DevOps** | Full | PRs, policies, builds, merge |

Platform is auto-detected from repository URLs. Override in manifest:

```yaml
repos:
  myrepo:
    url: git@custom-gitlab.com:org/repo.git
    platform:
      type: gitlab
      base_url: https://custom-gitlab.com
```

## Performance

The Rust implementation is significantly faster than TypeScript:

| Benchmark | TypeScript | Rust | Speedup |
|-----------|-----------|------|---------|
| manifest_parse | 0.431ms | 0.023ms | **~19x** |
| state_parse | 0.002ms | 0.001ms | ~1.5x |
| startup time | ~150ms | ~5ms | **~30x** |

### Running Benchmarks

```bash
# Rust CLI benchmarks
gr bench                    # Run all benchmarks
gr bench --list             # List available benchmarks
gr bench manifest-parse -n 100  # Run specific benchmark

# Criterion benchmarks (detailed)
cargo bench

# Compare with TypeScript
./run-benchmarks.sh 100
```

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
│   │       ├── bench.rs
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
│   │   ├── github.rs       # GitHub/GitHub Enterprise
│   │   ├── gitlab.rs       # GitLab/self-hosted
│   │   └── azure.rs        # Azure DevOps
│   ├── files/              # File operations
│   └── util/               # Utilities
├── benches/                # Criterion benchmarks
├── tests/                  # Integration tests
└── benchmark-results/      # Comparison reports
```

## Development

### Prerequisites

- Rust 1.80+ (stable)
- libgit2 (for git2 crate)

On macOS:
```bash
brew install libgit2
```

On Ubuntu/Debian:
```bash
apt install libgit2-dev
```

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
# Run all tests (108 tests)
cargo test

# Run specific test
cargo test test_manifest_parse

# Run with output
cargo test -- --nocapture

# Run tests for a specific module
cargo test platform::github
```

### Code Style

```bash
# Format code
cargo fmt

# Lint
cargo clippy

# Check both
cargo fmt --check && cargo clippy -- -D warnings
```

## Dependencies

| Crate | Version | Purpose |
|-------|---------|---------|
| tokio | 1.x | Async runtime |
| clap | 4.x | CLI parsing |
| serde | 1.x | Serialization |
| serde_yaml | 0.9 | YAML parsing |
| serde_json | 1.x | JSON parsing |
| git2 | 0.19 | Git operations |
| octocrab | 0.41 | GitHub API |
| reqwest | 0.12 | HTTP client |
| colored | 2.x | Terminal colors |
| indicatif | 0.17 | Progress bars |
| anyhow | 1.x | Error handling |
| thiserror | 1.x | Custom errors |
| chrono | 0.4 | Date/time |
| regex | 1.x | Regex matching |
| tracing | 0.1 | Logging |

## Migration Status

All phases complete:

- [x] Phase 1: Foundation (manifest, state, repo types)
- [x] Phase 2: Git Operations (status, branch, remote, cache)
- [x] Phase 3: Platform Adapters (GitHub, GitLab, Azure DevOps)
- [x] Phase 4: Core CLI Commands (status, sync, branch, checkout, add, diff, commit, push)
- [x] Phase 5: PR Workflow (create, status, merge, checks, diff)
- [x] Phase 6: Advanced Commands (init, tree, forall, rebase, link, run, env, repo, bench)
- [x] Phase 7: Tests and Polish (108 unit tests, benchmarks, documentation)

## Known Limitations

1. **Interactive prompts**: Some features use basic stdin rather than rich terminal UI
2. **Windows**: Not fully tested on Windows (symlink handling may differ)
3. **E2E tests**: Integration/E2E test coverage is still being expanded

## Contributing

1. Create a branch: `gr branch feat/my-feature`
2. Make changes and test: `cargo test`
3. Format and lint: `cargo fmt && cargo clippy`
4. Commit: `gr commit -m "feat: description"`
5. Create PR: `gr pr create -t "feat: description" --push`

### Pull Request Checklist

- [ ] All tests pass (`cargo test`)
- [ ] Code is formatted (`cargo fmt --check`)
- [ ] No clippy warnings (`cargo clippy -- -D warnings`)
- [ ] Documentation updated if needed
- [ ] Commit messages follow conventional commits

## License

MIT
