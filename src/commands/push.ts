import chalk from 'chalk';
import ora from 'ora';
import { loadManifest, getAllRepoInfo, getManifestRepoInfo } from '../lib/manifest.js';
import { pathExists, getCurrentBranch, pushBranch, getGitInstance, isGitRepo } from '../lib/git.js';
import type { RepoInfo } from '../types.js';

interface PushOptions {
  setUpstream?: boolean;
  force?: boolean;
}

interface PushResult {
  repo: RepoInfo;
  success: boolean;
  pushed: boolean;
  branch?: string;
  error?: string;
}

/**
 * Check if current branch has commits ahead of remote
 */
async function hasCommitsAheadOfRemote(repoPath: string): Promise<boolean> {
  const git = getGitInstance(repoPath);
  try {
    const status = await git.status();
    return status.ahead > 0;
  } catch {
    // If we can't determine, assume we might need to push
    return true;
  }
}

/**
 * Check if branch has an upstream configured
 */
async function hasUpstream(repoPath: string): Promise<boolean> {
  const git = getGitInstance(repoPath);
  try {
    const branch = await getCurrentBranch(repoPath);
    const result = await git.raw(['config', '--get', `branch.${branch}.remote`]);
    return result.trim().length > 0;
  } catch {
    return false;
  }
}

/**
 * Push current branch to remote across all repositories
 */
export async function push(options: PushOptions = {}): Promise<void> {
  const { setUpstream = false, force = false } = options;

  const { manifest, rootDir } = await loadManifest();
  let repos: RepoInfo[] = getAllRepoInfo(manifest, rootDir);

  // Include manifest repo if it exists
  const manifestInfo = getManifestRepoInfo(manifest, rootDir);
  if (manifestInfo && await isGitRepo(manifestInfo.absolutePath)) {
    repos = [...repos, manifestInfo];
  }

  const results: PushResult[] = [];
  let hasCommits = false;

  console.log(chalk.blue('Checking repositories for commits to push...\n'));

  for (const repo of repos) {
    const exists = await pathExists(repo.absolutePath);

    if (!exists) {
      continue;
    }

    const branch = await getCurrentBranch(repo.absolutePath);
    const hasUpstreamConfigured = await hasUpstream(repo.absolutePath);

    // Check if there are commits to push
    const needsPush = await hasCommitsAheadOfRemote(repo.absolutePath);

    // Also push if no upstream and --set-upstream is specified
    const needsUpstreamPush = !hasUpstreamConfigured && setUpstream;

    if (!needsPush && !needsUpstreamPush) {
      continue;
    }

    hasCommits = true;
    const spinner = ora(`Pushing ${repo.name} (${branch})...`).start();

    try {
      const git = getGitInstance(repo.absolutePath);
      const pushOptions: string[] = [];

      if (setUpstream || !hasUpstreamConfigured) {
        pushOptions.push('-u', 'origin', branch);
      } else {
        pushOptions.push('origin', branch);
      }

      if (force) {
        pushOptions.unshift('--force');
      }

      await git.push(pushOptions);
      spinner.succeed(`${repo.name} (${chalk.cyan(branch)}): pushed`);
      results.push({ repo, success: true, pushed: true, branch });
    } catch (error) {
      const errorMsg = error instanceof Error ? error.message : String(error);
      spinner.fail(`${repo.name}: ${errorMsg}`);
      results.push({ repo, success: false, pushed: false, branch, error: errorMsg });
    }
  }

  if (!hasCommits) {
    console.log(chalk.yellow('No commits to push in any repository.'));
    return;
  }

  // Summary
  console.log('');
  const pushed = results.filter((r) => r.pushed).length;
  const failed = results.filter((r) => !r.success).length;

  if (failed === 0) {
    console.log(chalk.green(`Pushed ${pushed} repository(s).`));
  } else {
    console.log(chalk.yellow(`Pushed ${pushed} repository(s). ${failed} failed.`));
  }
}
