import chalk from 'chalk';
import ora from 'ora';
import { loadManifest, getAllRepoInfo, getManifestRepoInfo } from '../lib/manifest.js';
import { pathExists, getGitInstance, hasUncommittedChanges, isGitRepo } from '../lib/git.js';
import type { RepoInfo } from '../types.js';

interface CommitOptions {
  message?: string;
  all?: boolean;
  amend?: boolean;
  noEdit?: boolean;
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
 * Amend the most recent commit
 */
async function amendCommit(repoPath: string, message?: string): Promise<void> {
  const git = getGitInstance(repoPath);
  if (message) {
    await git.commit(message, ['--amend']);
  } else {
    await git.commit('', ['--amend', '--no-edit']);
  }
}

/**
 * Check if a repo has any commits
 */
async function hasCommits(repoPath: string): Promise<boolean> {
  const git = getGitInstance(repoPath);
  try {
    await git.revparse(['HEAD']);
    return true;
  } catch {
    return false;
  }
}

interface RepoCommitInfo {
  repo: RepoInfo;
  hasStaged: boolean;
}

/**
 * Commit staged changes across all repositories
 * Uses two-phase parallel approach for better performance
 */
export async function commit(options: CommitOptions): Promise<void> {
  const { message, all = false, amend = false, noEdit = false } = options;

  if (!message && !amend) {
    console.error(chalk.red('Commit message is required. Use -m "message"'));
    process.exit(1);
  }

  if (amend && !message && !noEdit) {
    console.error(chalk.red('Use --no-edit to amend without changing the message, or -m to provide a new message.'));
    process.exit(1);
  }

  const { manifest, rootDir } = await loadManifest();
  let repos: RepoInfo[] = getAllRepoInfo(manifest, rootDir);

  // Include manifest repo if it exists
  const manifestInfo = getManifestRepoInfo(manifest, rootDir);
  if (manifestInfo && await isGitRepo(manifestInfo.absolutePath)) {
    repos = [...repos, manifestInfo];
  }

  console.log(chalk.blue('Checking repositories for changes...\n'));

  // Phase 1: Check status and optionally stage changes in parallel
  const repoInfoResults = await Promise.all(
    repos.map(async (repo): Promise<RepoCommitInfo | null> => {
      const exists = await pathExists(repo.absolutePath);
      if (!exists) {
        return null;
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
      return { repo, hasStaged };
    })
  );

  // Filter to repos with staged changes (or any repo for amend with noEdit)
  let reposToCommit: RepoCommitInfo[];
  if (amend && noEdit) {
    // For amend --no-edit without staged changes, we still want to amend repos that have commits
    reposToCommit = repoInfoResults.filter(
      (info): info is RepoCommitInfo => info !== null && (info.hasStaged || !message)
    );
  } else {
    reposToCommit = repoInfoResults.filter(
      (info): info is RepoCommitInfo => info !== null && info.hasStaged
    );
  }

  if (reposToCommit.length === 0) {
    if (amend) {
      console.log(chalk.yellow('No staged changes to amend. Stage changes first with git add.'));
    } else {
      console.log(chalk.yellow('No staged changes to commit in any repository.'));
      if (!all) {
        console.log(chalk.dim('Use --all to stage and commit all changes, or stage changes with git add first.'));
      }
    }
    return;
  }

  // Phase 2: Commit (or amend) in parallel
  const results = await Promise.all(
    reposToCommit.map(async ({ repo }): Promise<CommitResult> => {
      const actionText = amend ? 'Amending' : 'Committing';
      const spinner = ora(`${actionText} ${repo.name}...`).start();

      try {
        if (amend) {
          // Check if repo has commits to amend
          if (!await hasCommits(repo.absolutePath)) {
            spinner.warn(`${repo.name}: no commits to amend`);
            return { repo, success: true, committed: false };
          }
          await amendCommit(repo.absolutePath, message);
          spinner.succeed(`${repo.name}: amended`);
        } else {
          await commitChanges(repo.absolutePath, message!);
          spinner.succeed(`${repo.name}: committed`);
        }
        return { repo, success: true, committed: true };
      } catch (error) {
        const errorMsg = error instanceof Error ? error.message : String(error);
        spinner.fail(`${repo.name}: ${errorMsg}`);
        return { repo, success: false, committed: false, error: errorMsg };
      }
    })
  );

  // Summary
  console.log('');
  const committed = results.filter((r) => r.committed).length;
  const failed = results.filter((r) => !r.success).length;
  const actionPast = amend ? 'Amended' : 'Committed';

  if (failed === 0) {
    console.log(chalk.green(`${actionPast} in ${committed} repository(s).`));
  } else {
    console.log(chalk.yellow(`${actionPast} in ${committed} repository(s). ${failed} failed.`));
  }
}
