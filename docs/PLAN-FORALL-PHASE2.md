# forall Phase 2: Complete Git Command Interception

## Goal

Intercept all common read-only git commands in `gr forall` for 20-50x speedup.

## Current State (Phase 1 Done)

```rust
// Already intercepted:
git status [--porcelain|-s]
git branch [-a]
git rev-parse HEAD
git rev-parse --abbrev-ref HEAD
```

## Phase 2 Implementation Plan

### 1. Pipe Support (~2 hours)

**What**: `git status | grep modified`, `git log | head -5`

**How**:
```rust
fn parse_piped_command(cmd: &str) -> Option<(GitCommand, String)> {
    let pipe_pos = cmd.find('|')?;
    let git_part = cmd[..pipe_pos].trim();
    let pipe_part = cmd[pipe_pos + 1..].trim();
    let git_cmd = try_parse_git_command(git_part)?;
    Some((git_cmd, pipe_part.to_string()))
}

fn execute_piped(repo_path: &Path, git_cmd: &GitCommand, pipe_to: &str) -> Result<String> {
    let git_output = execute_git_command(repo_path, git_cmd)?;

    let mut child = Command::new("sh")
        .arg("-c")
        .arg(pipe_to)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .spawn()?;

    child.stdin.take().unwrap().write_all(git_output.as_bytes())?;
    let output = child.wait_with_output()?;
    Ok(String::from_utf8_lossy(&output.stdout).to_string())
}
```

**Test cases**:
- `git status | grep modified`
- `git branch | wc -l`
- `git log --oneline | head -5`

---

### 2. Redirect Support (~1 hour)

**What**: `git log > log.txt`, `git status >> status.txt`

**How**:
```rust
fn parse_redirected_command(cmd: &str) -> Option<(GitCommand, String, bool)> {
    if let Some(pos) = cmd.find(">>") {
        let git_part = cmd[..pos].trim();
        let file = cmd[pos + 2..].trim();
        return Some((try_parse_git_command(git_part)?, file.to_string(), true));
    }
    if let Some(pos) = cmd.find('>') {
        let git_part = cmd[..pos].trim();
        let file = cmd[pos + 1..].trim();
        return Some((try_parse_git_command(git_part)?, file.to_string(), false));
    }
    None
}
```

---

### 3. git log --oneline (~1 hour)

**What**: `git log --oneline`, `git log --oneline -n 10`, `git log --oneline -5`

**How**:
```rust
GitCommand::LogOneline { count: usize }

fn execute_log_oneline(repo: &Repository, count: usize) -> Result<String> {
    let mut revwalk = repo.revwalk()?;
    revwalk.push_head()?;

    let mut output = String::new();
    for oid in revwalk.take(count) {
        let oid = oid?;
        let commit = repo.find_commit(oid)?;
        let short = &oid.to_string()[..7];
        let msg = commit.summary().unwrap_or("");
        output.push_str(&format!("{} {}\n", short, msg));
    }
    Ok(output)
}
```

**Patterns**:
- `git log --oneline` → count=10 (default)
- `git log --oneline -n 5` → count=5
- `git log --oneline -5` → count=5
- `git log -1 --oneline` → count=1

---

### 4. git diff variants (~2 hours)

**What**: `git diff`, `git diff --stat`, `git diff --name-only`, `git diff --cached`

**How**:
```rust
GitCommand::Diff { staged: bool, format: DiffFormat }

enum DiffFormat {
    Patch,      // default
    Stat,       // --stat
    NameOnly,   // --name-only
    NameStatus, // --name-status
}

fn execute_diff(repo: &Repository, staged: bool, format: DiffFormat) -> Result<String> {
    let diff = if staged {
        let head = repo.head()?.peel_to_tree()?;
        repo.diff_tree_to_index(Some(&head), None, None)?
    } else {
        repo.diff_index_to_workdir(None, None)?
    };

    match format {
        DiffFormat::Patch => format_patch(&diff),
        DiffFormat::Stat => format_stat(&diff),
        DiffFormat::NameOnly => format_name_only(&diff),
        DiffFormat::NameStatus => format_name_status(&diff),
    }
}
```

---

### 5. git ls-files (~30 min)

**What**: `git ls-files`, `git ls-files -m`

```rust
fn execute_ls_files(repo: &Repository, modified_only: bool) -> Result<String> {
    let index = repo.index()?;

    if modified_only {
        let statuses = repo.statuses(None)?;
        return Ok(statuses.iter()
            .filter(|e| e.status().is_wt_modified())
            .filter_map(|e| e.path().map(String::from))
            .collect::<Vec<_>>()
            .join("\n"));
    }

    Ok(index.iter()
        .filter_map(|e| String::from_utf8(e.path).ok())
        .collect::<Vec<_>>()
        .join("\n"))
}
```

---

### 6. git tag (~30 min)

**What**: `git tag`, `git tag -l`

```rust
fn execute_tag_list(repo: &Repository) -> Result<String> {
    let mut tags = Vec::new();
    repo.tag_foreach(|_, name| {
        if let Ok(name) = std::str::from_utf8(name) {
            let name = name.strip_prefix("refs/tags/").unwrap_or(name);
            tags.push(name.to_string());
        }
        true
    })?;
    tags.sort();
    Ok(tags.join("\n"))
}
```

---

### 7. git remote -v (~30 min)

```rust
fn execute_remote_verbose(repo: &Repository) -> Result<String> {
    let mut output = String::new();
    for name in repo.remotes()?.iter().flatten() {
        if let Ok(remote) = repo.find_remote(name) {
            let url = remote.url().unwrap_or("");
            output.push_str(&format!("{}\t{} (fetch)\n", name, url));
            output.push_str(&format!("{}\t{} (push)\n", name, remote.pushurl().unwrap_or(url)));
        }
    }
    Ok(output)
}
```

---

### 8. git stash list (~30 min)

```rust
fn execute_stash_list(repo: &Repository) -> Result<String> {
    let mut output = String::new();
    repo.stash_foreach(|idx, msg, _| {
        output.push_str(&format!("stash@{{{}}}: {}\n", idx, msg));
        true
    })?;
    Ok(output)
}
```

---

### 9. git blame (~1 hour)

```rust
fn execute_blame(repo: &Repository, file_path: &str) -> Result<String> {
    let blame = repo.blame_file(Path::new(file_path), None)?;
    let content = std::fs::read_to_string(repo.workdir().unwrap().join(file_path))?;
    let lines: Vec<&str> = content.lines().collect();

    let mut output = String::new();
    for (i, hunk) in blame.iter().enumerate() {
        let oid = hunk.final_commit_id();
        let sig = hunk.final_signature();
        let short = &oid.to_string()[..8];
        let author = sig.name().unwrap_or("?");
        let line = lines.get(i).unwrap_or(&"");

        output.push_str(&format!("{} ({:>12} {:>4}) {}\n",
            short, author, i + 1, line));
    }
    Ok(output)
}
```

---

## Implementation Order

| # | Task | Time | Dependencies |
|---|------|------|--------------|
| 1 | Refactor: Add GitCommand enum variants | 30m | - |
| 2 | Pipe support | 2h | #1 |
| 3 | Redirect support | 1h | #1 |
| 4 | git log --oneline | 1h | #1 |
| 5 | git diff variants | 2h | #1 |
| 6 | git ls-files | 30m | #1 |
| 7 | git tag | 30m | #1 |
| 8 | git remote -v | 30m | #1 |
| 9 | git stash list | 30m | #1 |
| 10 | git blame | 1h | #1 |
| 11 | Tests | 2h | All |
| 12 | Benchmarks | 1h | All |
| **Total** | | **~13h** | |

---

## Success Criteria

1. All listed commands intercepted and working
2. Pipe/redirect support working
3. Tests passing for each command
4. Benchmark showing 20-50x speedup
5. `--no-intercept` flag still works as escape hatch

---

## Commands After Phase 2

```rust
// Phase 1 (done)
git status [--porcelain|-s]
git branch [-a|-r]
git rev-parse HEAD
git rev-parse --abbrev-ref HEAD

// Phase 2 (this plan)
git log --oneline [-n N]
git diff [--staged|--cached] [--stat|--name-only|--name-status]
git ls-files [-m]
git tag [-l]
git remote [-v]
git stash list
git blame FILE
git ... | COMMAND
git ... > FILE
git ... >> FILE
```
