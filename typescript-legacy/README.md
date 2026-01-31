# gitgrip (TypeScript - Legacy)

> **DEPRECATED**: This is the legacy TypeScript implementation. The primary implementation is now in Rust at the repository root. See the [main README](../README.md) for installation and usage.

## Installation (Legacy)

```bash
npm install -g gitgrip
```

## Development

```bash
pnpm install
pnpm build
pnpm test
```

## Migration to Rust

The Rust implementation provides:
- Better performance
- Additional commands (`gr pr checks`, `gr pr diff`, `gr rebase`)
- Improved error handling
- Cross-platform binaries

Install the Rust version:
```bash
# From crates.io
cargo install gitgrip

# From Homebrew
brew tap laynepenney/tap
brew install gitgrip

# From source
git clone https://github.com/laynepenney/gitgrip.git
cd gitgrip
cargo install --path .
```
