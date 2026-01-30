# gix Migration Plan: Should gitoxide Be Default?

## The Question

Based on benchmarks showing gix is 40% faster for multi-repo operations, should we make gix the default instead of git2?

## Benchmark Summary

| Operation (5 repos) | git2 | gix | Winner |
|---------------------|------|-----|--------|
| `gr status` | 1.78 ms | **1.28 ms** | gix 40% faster |
| `forall git status` | 1.64 ms | **1.14 ms** | gix 40% faster |
| Single repo status | **151 µs** | 307 µs | git2 2x faster |
| Branch listing | 241 µs | **29 ns** | gix 8,300x faster |

## Who Uses gitgrip?

**Target users**: Teams managing multiple related repositories
- Microservices architectures (5-20 repos)
- Monorepo alternatives (3-10 repos)
- Related projects (frontend/backend/shared-lib)
- Platform teams (core + plugins)

**If you have 1-2 repos, you don't need gitgrip.** The tool exists specifically for multi-repo coordination. Therefore:

> **Most gitgrip users will have 3+ repos** - exactly where gix excels.

## gix Maturity Assessment

| Aspect | Status | Notes |
|--------|--------|-------|
| Repo open | ✅ Stable | Works well |
| Branch operations | ✅ Stable | Extremely fast |
| HEAD/ref resolution | ✅ Stable | Works well |
| Status API | ⚠️ Maturing | Basic support, improving |
| Clone | ✅ Stable | Works |
| Fetch/Pull | ⚠️ Maturing | May need CLI fallback |
| Push | ⚠️ Maturing | May need CLI fallback |
| Merge/Rebase | ❌ Limited | Use CLI |

**Key insight**: gitgrip's hot path is `gr status` (runs constantly), which primarily needs:
- Repo open ✅
- Get current branch ✅
- Check for changes ⚠️ (workable)

The slower operations (clone, push, pull) are infrequent and can fall back to CLI without impacting UX.

## Recommendation: Hybrid Approach

### Phase 1: gix for Read Operations (Now)

Make gix the default for **read-only operations**:
- `open_repo()` - gix
- `get_current_branch()` - gix
- `list_branches()` - gix
- `has_changes()` - gix (or CLI fallback)

Keep git2/CLI for **write operations**:
- `clone_repo()` - CLI
- `push_branch()` - CLI
- `pull_latest()` - CLI
- `checkout_branch()` - git2 or CLI
- `create_branch()` - git2 or CLI

### Phase 2: Full gix (When Status API Matures)

Once gix's status/index API stabilizes:
- Move `has_changes()` to pure gix
- Evaluate gix for checkout/branch create
- Remove git2 dependency entirely (pure Rust!)

### Implementation

```rust
// Cargo.toml - make gix default
[features]
default = ["gitoxide"]
git2-backend = ["git2"]  # Keep for fallback
gitoxide = ["gix"]

// In code - use gix for reads, CLI for writes
pub fn get_current_branch(repo_path: &Path) -> Result<String, GitError> {
    #[cfg(feature = "gitoxide")]
    {
        let repo = gix::open(repo_path)?;
        // Fast path with gix
    }
    #[cfg(not(feature = "gitoxide"))]
    {
        // Fallback to git2
    }
}

pub fn push_branch(...) -> Result<(), GitError> {
    // Always use CLI for reliability
    Command::new("git").args(["push", ...])
}
```

## Migration Path

### v0.5.x (Current)
- git2 default
- gix optional (`--features gitoxide`)
- Benchmarks prove gix advantage

### v0.6.0 (Next)
- gix default for read operations
- git2 available as `--features git2-backend`
- CLI fallback for immature gix APIs
- **forall git command interception** (see below)

### v0.7.0 (Future)
- Evaluate full gix adoption
- Remove git2 if gix status API is ready
- Pure Rust binary (no C dependencies!)

## forall Optimization: Git Command Interception

### Problem

`gr forall -c "git status"` currently spawns N git processes (one per repo), which is **100x slower** than using gix directly.

| Command | Current (CLI) | With Interception (gix) | Speedup |
|---------|---------------|-------------------------|---------|
| `forall -c "git status"` | 118 ms | ~1.1 ms | **107x** |
| `forall -c "git branch"` | ~100 ms | ~0.9 ms | **111x** |

### Solution

Parse the forall command and intercept known git commands:

```rust
fn run_forall_command(repos: &[RepoInfo], command: &str) -> Result<()> {
    // Try to intercept git commands for speed
    if let Some(optimized) = try_intercept_git_command(command) {
        return run_optimized(repos, optimized);
    }

    // Fall back to shell execution
    run_shell_command(repos, command)
}

fn try_intercept_git_command(command: &str) -> Option<GitCommand> {
    let parts: Vec<&str> = command.split_whitespace().collect();

    match parts.as_slice() {
        ["git", "status"] => Some(GitCommand::Status { porcelain: false }),
        ["git", "status", "--porcelain"] => Some(GitCommand::Status { porcelain: true }),
        ["git", "status", "-s"] => Some(GitCommand::Status { porcelain: true }),
        ["git", "branch"] => Some(GitCommand::ListBranches),
        ["git", "branch", "-a"] => Some(GitCommand::ListAllBranches),
        ["git", "rev-parse", "HEAD"] => Some(GitCommand::GetHead),
        ["git", "rev-parse", "--abbrev-ref", "HEAD"] => Some(GitCommand::GetBranch),
        ["git", "diff", "--stat"] => Some(GitCommand::DiffStat),
        _ => None, // Not interceptable, use shell
    }
}
```

### Interceptable Commands

| Pattern | Intercept | gix Operation |
|---------|-----------|---------------|
| `git status` | ✅ | `repo.status()` or head_id check |
| `git status --porcelain` | ✅ | Format as porcelain |
| `git status -s` | ✅ | Same as --porcelain |
| `git branch` | ✅ | `repo.references().local_branches()` |
| `git branch -a` | ✅ | Include remote branches |
| `git rev-parse HEAD` | ✅ | `repo.head_id()` |
| `git rev-parse --abbrev-ref HEAD` | ✅ | `repo.head_name()` |
| `git diff --stat` | ⚠️ | May need CLI fallback |
| `git log ...` | ❌ | Too complex, use CLI |
| `git status \| grep ...` | ❌ | Piped, use CLI |
| `npm test` | ❌ | Not git, use CLI |

### Bypass Flag

Add `--no-intercept` flag for users who need exact git output:

```bash
gr forall -c "git status"              # Uses gix (fast)
gr forall --no-intercept -c "git status"  # Uses git CLI (exact output)
```

### Implementation Priority

1. `git status` / `git status --porcelain` - Most common
2. `git rev-parse --abbrev-ref HEAD` - Used for branch checks
3. `git branch` - Common listing operation
4. Others as needed

## Benefits of gix Default

1. **40% faster** for typical gitgrip workloads
2. **Pure Rust** - easier cross-compilation, no libgit2 build issues
3. **Async-ready** - gix supports async, enabling future parallelization
4. **Active development** - gitoxide is actively improved

## Risks

1. **gix API churn** - May need code updates as gix evolves
2. **Edge cases** - Less battle-tested than git2
3. **Status API gaps** - May need CLI fallback for some status checks

## Decision

**Yes, gix should become the default** for gitgrip because:

1. gitgrip users have 3+ repos (by definition)
2. gix is 40% faster for multi-repo operations
3. The hot path (`gr status`) uses operations gix handles well
4. Write operations can use CLI (already battle-tested)
5. Pure Rust distribution is a significant win

**Timeline**: Target gix-default in v0.6.0 after validating the hybrid approach works reliably.
