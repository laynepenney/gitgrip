import { simpleGit, SimpleGit, StatusResult } from 'simple-git';
import { access } from 'fs/promises';
import type { RepoInfo, RepoStatus, MultiRepoResult } from '../types.js';

/**
 * Get a SimpleGit instance for a repository
 */
export function getGitInstance(repoPath: string): SimpleGit {
  return simpleGit(repoPath);
}

/**
 * Check if a directory is a git repository
 */
export async function isGitRepo(path: string): Promise<boolean> {
  try {
    const git = getGitInstance(path);
    await git.revparse(['--git-dir']);
    return true;
  } catch {
    return false;
  }
}

/**
 * Check if a path exists
 */
export async function pathExists(path: string): Promise<boolean> {
  try {
    await access(path);
    return true;
  } catch {
    return false;
  }
}

/**
 * Clone a repository
 */
export async function cloneRepo(url: string, path: string, branch?: string): Promise<void> {
  const git = simpleGit();
  const options = branch ? ['--branch', branch] : [];
  await git.clone(url, path, options);
}

/**
 * Get the current branch name
 */
export async function getCurrentBranch(repoPath: string): Promise<string> {
  const git = getGitInstance(repoPath);
  const branch = await git.revparse(['--abbrev-ref', 'HEAD']);
  return branch.trim();
}

/**
 * Get repository status
 */
export async function getRepoStatus(repo: RepoInfo): Promise<RepoStatus> {
  const exists = await pathExists(repo.absolutePath);
  if (!exists) {
    return {
      name: repo.name,
      branch: '',
      clean: true,
      staged: 0,
      modified: 0,
      untracked: 0,
      ahead: 0,
      behind: 0,
      exists: false,
    };
  }

  const git = getGitInstance(repo.absolutePath);
  const status: StatusResult = await git.status();

  return {
    name: repo.name,
    branch: status.current ?? 'unknown',
    clean: status.isClean(),
    staged: status.staged.length,
    modified: status.modified.length,
    untracked: status.not_added.length,
    ahead: status.ahead,
    behind: status.behind,
    exists: true,
  };
}

/**
 * Get status for all repositories
 */
export async function getAllRepoStatus(repos: RepoInfo[]): Promise<RepoStatus[]> {
  const results = await Promise.all(repos.map((repo) => getRepoStatus(repo)));
  return results;
}

/**
 * Create a branch in a repository
 */
export async function createBranch(repoPath: string, branchName: string): Promise<void> {
  const git = getGitInstance(repoPath);
  await git.checkoutLocalBranch(branchName);
}

/**
 * Checkout a branch in a repository
 */
export async function checkoutBranch(repoPath: string, branchName: string): Promise<void> {
  const git = getGitInstance(repoPath);
  await git.checkout(branchName);
}

/**
 * Check if a branch exists locally
 */
export async function branchExists(repoPath: string, branchName: string): Promise<boolean> {
  const git = getGitInstance(repoPath);
  try {
    const branches = await git.branchLocal();
    return branches.all.includes(branchName);
  } catch {
    return false;
  }
}

/**
 * Check if a branch exists on remote
 */
export async function remoteBranchExists(repoPath: string, branchName: string, remote = 'origin'): Promise<boolean> {
  const git = getGitInstance(repoPath);
  try {
    const result = await git.listRemote(['--heads', remote, branchName]);
    return result.trim().length > 0;
  } catch {
    return false;
  }
}

/**
 * Pull latest changes from remote
 */
export async function pullLatest(repoPath: string, remote = 'origin'): Promise<void> {
  const git = getGitInstance(repoPath);
  await git.pull(remote);
}

/**
 * Fetch from remote
 */
export async function fetchRemote(repoPath: string, remote = 'origin'): Promise<void> {
  const git = getGitInstance(repoPath);
  await git.fetch(remote);
}

/**
 * Push branch to remote
 */
export async function pushBranch(
  repoPath: string,
  branchName: string,
  remote = 'origin',
  setUpstream = false
): Promise<void> {
  const git = getGitInstance(repoPath);
  const options = setUpstream ? ['-u', remote, branchName] : [remote, branchName];
  await git.push(options);
}

/**
 * Get list of changed files (staged and unstaged)
 */
export async function getChangedFiles(repoPath: string): Promise<string[]> {
  const git = getGitInstance(repoPath);
  const status = await git.status();
  return [...status.staged, ...status.modified, ...status.not_added];
}

/**
 * Check if there are uncommitted changes
 */
export async function hasUncommittedChanges(repoPath: string): Promise<boolean> {
  const git = getGitInstance(repoPath);
  const status = await git.status();
  return !status.isClean();
}

/**
 * Get commits between current branch and base branch
 */
export async function getCommitsBetween(
  repoPath: string,
  baseBranch: string,
  headBranch?: string
): Promise<string[]> {
  const git = getGitInstance(repoPath);
  const head = headBranch ?? (await getCurrentBranch(repoPath));
  try {
    const log = await git.log({ from: baseBranch, to: head });
    return log.all.map((commit) => commit.hash);
  } catch {
    return [];
  }
}

/**
 * Check if branch has commits not in base
 */
export async function hasCommitsAhead(repoPath: string, baseBranch: string): Promise<boolean> {
  const commits = await getCommitsBetween(repoPath, baseBranch);
  return commits.length > 0;
}

/**
 * Run an operation across multiple repos
 */
export async function runOnAllRepos<T>(
  repos: RepoInfo[],
  operation: (repo: RepoInfo) => Promise<T>
): Promise<MultiRepoResult<T>[]> {
  const results = await Promise.all(
    repos.map(async (repo) => {
      try {
        const data = await operation(repo);
        return {
          repoName: repo.name,
          success: true,
          data,
        };
      } catch (error) {
        return {
          repoName: repo.name,
          success: false,
          error: error instanceof Error ? error.message : String(error),
        };
      }
    })
  );
  return results;
}

/**
 * Create branch in all repos
 */
export async function createBranchInAllRepos(
  repos: RepoInfo[],
  branchName: string
): Promise<MultiRepoResult<void>[]> {
  return runOnAllRepos(repos, async (repo) => {
    if (!(await pathExists(repo.absolutePath))) {
      throw new Error('Repository not cloned');
    }
    await createBranch(repo.absolutePath, branchName);
  });
}

/**
 * Checkout branch in all repos
 */
export async function checkoutBranchInAllRepos(
  repos: RepoInfo[],
  branchName: string
): Promise<MultiRepoResult<void>[]> {
  return runOnAllRepos(repos, async (repo) => {
    if (!(await pathExists(repo.absolutePath))) {
      throw new Error('Repository not cloned');
    }
    await checkoutBranch(repo.absolutePath, branchName);
  });
}

/**
 * Pull latest in all repos
 */
export async function pullAllRepos(repos: RepoInfo[]): Promise<MultiRepoResult<void>[]> {
  return runOnAllRepos(repos, async (repo) => {
    if (!(await pathExists(repo.absolutePath))) {
      throw new Error('Repository not cloned');
    }
    await pullLatest(repo.absolutePath);
  });
}

/**
 * Push branch in all repos that have it
 */
export async function pushAllRepos(
  repos: RepoInfo[],
  branchName: string,
  setUpstream = false
): Promise<MultiRepoResult<void>[]> {
  return runOnAllRepos(repos, async (repo) => {
    if (!(await pathExists(repo.absolutePath))) {
      throw new Error('Repository not cloned');
    }
    const currentBranch = await getCurrentBranch(repo.absolutePath);
    if (currentBranch !== branchName) {
      throw new Error(`Not on branch ${branchName}`);
    }
    await pushBranch(repo.absolutePath, branchName, 'origin', setUpstream);
  });
}

/**
 * Get the URL of a remote
 */
export async function getRemoteUrl(repoPath: string, remote = 'origin'): Promise<string | null> {
  const git = getGitInstance(repoPath);
  try {
    const remotes = await git.getRemotes(true);
    const found = remotes.find((r) => r.name === remote);
    return found?.refs?.fetch ?? null;
  } catch {
    return null;
  }
}

/**
 * Set the URL of a remote (creates it if it doesn't exist)
 */
export async function setRemoteUrl(repoPath: string, url: string, remote = 'origin'): Promise<void> {
  const git = getGitInstance(repoPath);
  const existingUrl = await getRemoteUrl(repoPath, remote);
  if (existingUrl === null) {
    await git.addRemote(remote, url);
  } else if (existingUrl !== url) {
    await git.remote(['set-url', remote, url]);
  }
}

/**
 * Set upstream tracking for the current branch
 */
export async function setUpstreamBranch(repoPath: string, remote = 'origin'): Promise<void> {
  const git = getGitInstance(repoPath);
  const branch = await getCurrentBranch(repoPath);
  await git.branch(['--set-upstream-to', `${remote}/${branch}`, branch]);
}

/**
 * Get the upstream tracking branch for a local branch
 * Returns null if no upstream is configured
 */
export async function getUpstreamBranch(repoPath: string, branch?: string): Promise<string | null> {
  const git = getGitInstance(repoPath);
  const localBranch = branch ?? (await getCurrentBranch(repoPath));
  try {
    const result = await git.raw(['config', '--get', `branch.${localBranch}.merge`]);
    // Result is like "refs/heads/feature-branch"
    const ref = result.trim();
    if (ref.startsWith('refs/heads/')) {
      return ref.replace('refs/heads/', '');
    }
    return ref || null;
  } catch {
    return null;
  }
}

/**
 * Check if the upstream branch for current branch still exists on remote
 */
export async function upstreamBranchExists(repoPath: string, remote = 'origin'): Promise<boolean> {
  const upstreamBranch = await getUpstreamBranch(repoPath);
  if (!upstreamBranch) {
    return false;
  }
  return remoteBranchExists(repoPath, upstreamBranch, remote);
}

/**
 * Safely pull latest, handling the case where upstream branch was deleted
 * Returns true if pull succeeded, false if had to recover (checkout default branch)
 *
 * IMPORTANT: Will NOT auto-switch branches if:
 * - Branch was never pushed (no upstream configured) - would lose local work
 * - Branch has local-only commits not on default branch - would lose commits
 */
export async function safePullLatest(
  repoPath: string,
  defaultBranch = 'main',
  remote = 'origin'
): Promise<{ pulled: boolean; recovered: boolean; message?: string }> {
  const git = getGitInstance(repoPath);
  const currentBranch = await getCurrentBranch(repoPath);

  // If we're on the default branch, just pull
  if (currentBranch === defaultBranch) {
    try {
      await git.pull(remote);
      return { pulled: true, recovered: false };
    } catch (error) {
      const errorMsg = error instanceof Error ? error.message : String(error);
      return { pulled: false, recovered: false, message: errorMsg };
    }
  }

  // Check if branch was ever pushed (has remote tracking configured)
  const upstreamBranch = await getUpstreamBranch(repoPath);
  const hasUpstreamConfig = upstreamBranch !== null;

  // Check if upstream branch still exists on remote
  const upstreamExists = await upstreamBranchExists(repoPath, remote);

  if (!upstreamExists) {
    // No upstream exists - need to determine if safe to switch

    if (!hasUpstreamConfig) {
      // Branch was never pushed - don't auto-switch, would lose local work
      return {
        pulled: false,
        recovered: false,
        message: `Branch '${currentBranch}' has no upstream configured. Push with 'gr push -u' first, or checkout '${defaultBranch}' manually.`
      };
    }

    // Upstream was configured but deleted - check for local-only commits
    // that would be lost if we switch to default branch
    const hasLocalOnlyCommits = await hasCommitsAhead(repoPath, defaultBranch);
    if (hasLocalOnlyCommits) {
      return {
        pulled: false,
        recovered: false,
        message: `Branch '${currentBranch}' has local commits not in '${defaultBranch}'. Push your changes or merge manually.`
      };
    }

    // Safe to switch - upstream was deleted and no local-only work would be lost
    try {
      await git.checkout(defaultBranch);
      await git.pull(remote);
      return {
        pulled: true,
        recovered: true,
        message: `Switched from '${currentBranch}' to '${defaultBranch}' (upstream branch was deleted)`
      };
    } catch (error) {
      const errorMsg = error instanceof Error ? error.message : String(error);
      return { pulled: false, recovered: false, message: errorMsg };
    }
  }

  // Upstream exists, normal pull
  try {
    await git.pull(remote);
    return { pulled: true, recovered: false };
  } catch (error) {
    const errorMsg = error instanceof Error ? error.message : String(error);
    return { pulled: false, recovered: false, message: errorMsg };
  }
}
