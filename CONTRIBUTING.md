# Contributing to gitgrip

Thank you for your interest in contributing to gitgrip!

## Getting Started

1. Fork the repository
2. Clone your fork:
   ```bash
   git clone git@github.com:yourusername/gitgrip.git
   cd gitgrip
   ```
3. Install dependencies:
   ```bash
   pnpm install
   ```
4. Build the project:
   ```bash
   pnpm build
   ```

## Project Structure

```
gitgrip/
├── src/
│   ├── index.ts          # CLI entry point
│   ├── types.ts          # TypeScript interfaces
│   ├── commands/         # CLI commands
│   └── lib/              # Core libraries
├── dist/                 # Compiled output
├── docs/                 # Documentation
└── tests/                # Test files
```

## Development Workflow

1. Create a feature branch
2. Make your changes
3. Run tests: `pnpm test`
4. Run linting: `pnpm lint`
5. Submit a pull request

## Code Style

- TypeScript strict mode
- Async/await for I/O
- Use `chalk` for colored output
- Use `ora` for spinners

## Testing

```bash
pnpm test              # Run all tests
pnpm test:watch        # Watch mode
```

## Questions?

Open an issue or discussion on GitHub.
