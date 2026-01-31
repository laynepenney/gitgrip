import chalk from 'chalk';
import ora from 'ora';
import { loadManifest, getAllRepoInfo, getManifestRepoInfo } from '../../lib/manifest.js';
import { pathExists, getCurrentBranch, isGitRepo } from '../../lib/git.js';
import { getPlatformAdapter } from '../../lib/platform/index.js';
import type { RepoInfo } from '../../types.js';

interface DiffOptions {
  stat?: boolean;
}

interface PRDiffInfo {
  repoName: string;
  prNumber: number;
  diff: string;
}

/**
 * Count diff stats from a unified diff string
 */
function getDiffStats(diff: string): { files: number; additions: number; deletions: number } {
  const lines = diff.split('\n');
  let files = 0;
  let additions = 0;
  let deletions = 0;

  for (const line of lines) {
    if (line.startsWith('diff --git')) {
      files++;
    } else if (line.startsWith('+') && !line.startsWith('+++')) {
      additions++;
    } else if (line.startsWith('-') && !line.startsWith('---')) {
      deletions++;
    }
  }

  return { files, additions, deletions };
}

/**
 * Show diff for PRs across all repositories
 */
export async function prDiff(options: DiffOptions = {}): Promise<void> {
  const { manifest, rootDir } = await loadManifest();
  const repos = getAllRepoInfo(manifest, rootDir);

  // Filter to cloned repos
  const clonedRepos: RepoInfo[] = [];
  for (const repo of repos) {
    if (await pathExists(repo.absolutePath)) {
      clonedRepos.push(repo);
    }
  }

  if (clonedRepos.length === 0) {
    console.log(chalk.yellow('No repositories are cloned.'));
    return;
  }

  const spinner = ora('Fetching PR diffs...').start();

  try {
    // Find PRs and get their diffs
    const diffResults: (PRDiffInfo | null)[] = await Promise.all(
      clonedRepos.map(async (repo) => {
        const branch = await getCurrentBranch(repo.absolutePath);

        // Skip repos on default branch
        if (branch === repo.default_branch) {
          return null;
        }

        const platform = getPlatformAdapter(repo.platformType, repo.platform);
        const pr = await platform.findPRByBranch(repo.owner, repo.repo, branch);
        if (!pr) {
          return null;
        }

        // Get diff if platform supports it
        if (!platform.getPullRequestDiff) {
          return null;
        }

        const diff = await platform.getPullRequestDiff(repo.owner, repo.repo, pr.number);
        return {
          repoName: repo.name,
          prNumber: pr.number,
          diff,
        };
      })
    );

    // Check manifest too
    const manifestInfo = getManifestRepoInfo(manifest, rootDir);
    let manifestDiff: PRDiffInfo | null = null;
    if (manifestInfo && await isGitRepo(manifestInfo.absolutePath)) {
      const manifestBranch = await getCurrentBranch(manifestInfo.absolutePath);
      if (manifestBranch !== manifestInfo.default_branch) {
        const platform = getPlatformAdapter(manifestInfo.platformType, manifestInfo.platform);
        const pr = await platform.findPRByBranch(manifestInfo.owner, manifestInfo.repo, manifestBranch);
        if (pr && platform.getPullRequestDiff) {
          const diff = await platform.getPullRequestDiff(manifestInfo.owner, manifestInfo.repo, pr.number);
          manifestDiff = {
            repoName: manifestInfo.name,
            prNumber: pr.number,
            diff,
          };
        }
      }
    }

    spinner.stop();

    const allDiffs = diffResults.filter((d): d is PRDiffInfo => d !== null);
    if (manifestDiff) {
      allDiffs.push(manifestDiff);
    }

    if (allDiffs.length === 0) {
      console.log(chalk.yellow('No open PRs found.'));
      return;
    }

    // Display results
    if (options.stat) {
      // Show stat summary only
      console.log(chalk.blue('PR Diff Summary:\n'));

      let totalFiles = 0;
      let totalAdditions = 0;
      let totalDeletions = 0;

      for (const { repoName, prNumber, diff } of allDiffs) {
        const stats = getDiffStats(diff);
        totalFiles += stats.files;
        totalAdditions += stats.additions;
        totalDeletions += stats.deletions;

        console.log(chalk.bold(`${repoName} #${prNumber}`));
        console.log(`  ${chalk.cyan(stats.files + ' files')}, ${chalk.green('+' + stats.additions)}, ${chalk.red('-' + stats.deletions)}`);
        console.log('');
      }

      console.log(chalk.dim('─'.repeat(40)));
      console.log(chalk.bold('Total:'));
      console.log(`  ${chalk.cyan(totalFiles + ' files')}, ${chalk.green('+' + totalAdditions)}, ${chalk.red('-' + totalDeletions)}`);
    } else {
      // Show full diff
      for (const { repoName, prNumber, diff } of allDiffs) {
        console.log(chalk.blue.bold(`\n${'='.repeat(60)}`));
        console.log(chalk.blue.bold(`=== ${repoName} (#${prNumber}) ===`));
        console.log(chalk.blue.bold(`${'='.repeat(60)}\n`));
        console.log(diff);
      }
    }
  } catch (error) {
    spinner.fail('Failed to fetch PR diffs');
    console.error(chalk.red(error instanceof Error ? error.message : String(error)));
  }
}
