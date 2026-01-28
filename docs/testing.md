# Testing gitgrip

## Manual Testing

### Setup Test Environment

```bash
mkdir ~/test-gitgrip && cd ~/test-gitgrip
npx gitgrip init <manifest-url>
```

### Create Test Manifest

Create a manifest repository with `manifest.yaml`:

```yaml
version: 1

repos:
  test-public:
    url: git@github.com:yourusername/test-public.git
    path: ./test-public
    default_branch: main
  test-private:
    url: git@github.com:yourusername/test-private.git
    path: ./test-private
    default_branch: main

settings:
  pr_prefix: "[cross-repo]"
  merge_strategy: all-or-nothing
```

### Test Commands

```bash
# Initialize workspace
npx gitgrip init <manifest-url>

# Check status
npx gitgrip status

# Create feature branch
npx gitgrip branch feature/test-1

# Check status again
npx gitgrip status

# Create cross-repo PR
npx gitgrip pr create --push --title "Test cross-repo PR"

# Check PR status
npx gitgrip pr status

# Merge PRs
npx gitgrip pr merge
```

### Test Repositories

Create test repositories:
   - `test-public` (public)
   - `test-private` (private)

### Debug Mode

```bash
DEBUG=* npx gitgrip status
```

## Automated Tests

```bash
pnpm test              # Run all tests
pnpm test:watch        # Watch mode
pnpm test -- --grep "manifest"  # Filter tests
```
