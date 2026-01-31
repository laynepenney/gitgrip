# Contributing to gitgrip

Thank you for your interest in contributing to gitgrip!

## Getting Started

1. Fork the repository
2. Clone your fork:
   ```bash
   git clone git@github.com:yourusername/gitgrip.git
   cd gitgrip
   ```
3. Build the project:
   ```bash
   cargo build
   ```
4. Run tests:
   ```bash
   cargo test
   ```

## Project Structure

```
gitgrip/
├── src/
│   ├── main.rs           # CLI entry point (clap)
│   ├── lib.rs            # Library exports
│   ├── cli/              # CLI command implementations
│   │   └── commands/     # Individual commands (init, sync, status, etc.)
│   ├── core/             # Core library (manifest, workspace, config)
│   ├── git/              # Git operations (git2 bindings)
│   ├── platform/         # Multi-platform support (GitHub, GitLab, Azure)
│   └── util/             # Utilities (output, timing)
├── tests/                # Integration tests
├── benches/              # Benchmarks
└── typescript-legacy/    # Legacy TypeScript version (deprecated)
```

## Development Workflow

1. Create a feature branch:
   ```bash
   git checkout -b feat/my-feature
   ```
2. Make your changes
3. Run tests: `cargo test`
4. Run linting: `cargo clippy`
5. Format code: `cargo fmt`
6. Submit a pull request

## Code Style

- Follow Rust idioms and conventions
- Use `anyhow` for error handling in binaries
- Use `thiserror` for library error types
- Use `colored` for terminal colors
- Use `indicatif` for progress bars and spinners
- Add tests for new functionality

## Testing

```bash
cargo test                 # Run all tests
cargo test <name>          # Run specific test
cargo test -- --nocapture  # Show output
```

## Benchmarks

```bash
cargo bench                # Run benchmarks
```

## Building

```bash
cargo build                # Debug build
cargo build --release      # Release build
```

## Questions?

Open an issue or discussion on GitHub.
