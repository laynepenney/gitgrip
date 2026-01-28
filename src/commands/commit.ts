import chalk from 'chalk';
import ora from 'ora';
import { loadManifest, getAllRepoInfo, getManifestRepoInfo } from '../lib/manifest.js';
import { pathExists, getGitInstance, hasUncommittedChanges, isGitRepo } from '../lib/git.js';
import type { RepoInfo } from '../types.js';

interface CommitOptions {
  message: string;
  all?: boolean;
}

interface CommitResult {
  repo: RepoInfo;
  success: boolean;
  committed: boolean;
  error?: string;
}

/**
 * Check if a repo has staged changes
 */
async function hasStagedChanges(repoPath: string): Promise<boolean> {
  const git = getGitInstance(repoPath);
  const status = await git.status();
  return status.staged.length > 0;
}

/**
 * Stage all changes in a repo
 */
async function stageAll(repoPath: string): Promise<void> {
  const git = getGitInstance(repoPath);
  await git.add('-A');
}

/**
 * Commit staged changes in a repo
 */
async function commitChanges(repoPath: string, message: string): Promise<void> {
  const git = getGitInstance(repoPath);
  await git.commit(message);
}

/**
 * Commit staged changes across all repositories
 */
export async function commit(options: CommitOptions): Promise<void> {
  const { message, all = false } = options;

  if (!message) {
    console.error(chalk.red('Commit message is required. Use -m "message"'));
    process.exit(1);
  }

  const { manifest, rootDir } = await loadManifest();
  let repos: RepoInfo[] = getAllRepoInfo(manifest, rootDir);

  // Include manifest repo if it exists
  const manifestInfo = getManifestRepoInfo(manifest, rootDir);
  if (manifestInfo && await isGitRepo(manifestInfo.absolutePath)) {
    repos = [...repos, manifestInfo];
  }

  const results: CommitResult[] = [];
  let hasChanges = false;

  console.log(chalk.blue('Checking repositories for changes...\n'));

  for (const repo of repos) {
    const exists = await pathExists(repo.absolutePath);

    if (!exists) {
      continue;
    }

    // If --all flag, stage all changes first
    if (all) {
      const hasChangesToStage = await hasUncommittedChanges(repo.absolutePath);
      if (hasChangesToStage) {
        await stageAll(repo.absolutePath);
      }
    }

    // Check if there are staged changes
    const hasStaged = await hasStagedChanges(repo.absolutePath);

    if (!hasStaged) {
      continue;
    }

    hasChanges = true;
    const spinner = ora(`Committing ${repo.name}...`).start();

    try {
      await commitChanges(repo.absolutePath, message);
      spinner.succeed(`${repo.name}: committed`);
      results.push({ repo, success: true, committed: true });
    } catch (error) {
      const errorMsg = error instanceof Error ? error.message : String(error);
      spinner.fail(`${repo.name}: ${errorMsg}`);
      results.push({ repo, success: false, committed: false, error: errorMsg });
    }
  }

  if (!hasChanges) {
    console.log(chalk.yellow('No staged changes to commit in any repository.'));
    if (!all) {
      console.log(chalk.dim('Use --all to stage and commit all changes, or stage changes with git add first.'));
    }
    return;
  }

  // Summary
  console.log('');
  const committed = results.filter((r) => r.committed).length;
  const failed = results.filter((r) => !r.success).length;

  if (failed === 0) {
    console.log(chalk.green(`Committed in ${committed} repository(s).`));
  } else {
    console.log(chalk.yellow(`Committed in ${committed} repository(s). ${failed} failed.`));
  }
}
