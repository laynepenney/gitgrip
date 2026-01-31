import chalk from 'chalk';
import ora from 'ora';
import { loadManifest, getAllRepoInfo, getManifestRepoInfo } from '../../lib/manifest.js';
import { pathExists, getCurrentBranch, isGitRepo } from '../../lib/git.js';
import { getPlatformAdapter } from '../../lib/platform/index.js';
import type { RepoInfo } from '../../types.js';
import type { StatusCheckResult } from '../../lib/platform/types.js';

interface ChecksOptions {
  json?: boolean;
  watch?: boolean;
}

interface PRCheckInfo {
  repoName: string;
  prNumber: number;
  checks: StatusCheckResult;
}

/**
 * Show CI check status for PRs across all repositories
 */
export async function prChecks(options: ChecksOptions = {}): Promise<void> {
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

  const spinner = ora('Fetching check status...').start();

  try {
    // Find PRs and their check status for each repo
    const checkResults: (PRCheckInfo | null)[] = await Promise.all(
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

        // Get PR details for head SHA
        const prDetails = await platform.getPullRequest(repo.owner, repo.repo, pr.number);
        const checks = await platform.getStatusChecks(repo.owner, repo.repo, prDetails.head.sha);

        return {
          repoName: repo.name,
          prNumber: pr.number,
          checks,
        };
      })
    );

    // Check manifest too
    const manifestInfo = getManifestRepoInfo(manifest, rootDir);
    let manifestChecks: PRCheckInfo | null = null;
    if (manifestInfo && await isGitRepo(manifestInfo.absolutePath)) {
      const manifestBranch = await getCurrentBranch(manifestInfo.absolutePath);
      if (manifestBranch !== manifestInfo.default_branch) {
        const platform = getPlatformAdapter(manifestInfo.platformType, manifestInfo.platform);
        const pr = await platform.findPRByBranch(manifestInfo.owner, manifestInfo.repo, manifestBranch);
        if (pr) {
          const prDetails = await platform.getPullRequest(manifestInfo.owner, manifestInfo.repo, pr.number);
          const checks = await platform.getStatusChecks(manifestInfo.owner, manifestInfo.repo, prDetails.head.sha);
          manifestChecks = {
            repoName: manifestInfo.name,
            prNumber: pr.number,
            checks,
          };
        }
      }
    }

    spinner.stop();

    const allChecks = checkResults.filter((c): c is PRCheckInfo => c !== null);
    if (manifestChecks) {
      allChecks.push(manifestChecks);
    }

    if (allChecks.length === 0) {
      console.log(chalk.yellow('No open PRs found.'));
      return;
    }

    // JSON output
    if (options.json) {
      console.log(JSON.stringify(allChecks, null, 2));
      return;
    }

    // Display results
    console.log(chalk.blue('PR Checks:\n'));

    for (const { repoName, prNumber, checks } of allChecks) {
      const overallIcon = checks.state === 'success'
        ? chalk.green('✓')
        : checks.state === 'failure'
          ? chalk.red('✗')
          : chalk.yellow('●');

      console.log(`${overallIcon} ${chalk.bold(repoName)} #${prNumber}`);

      if (checks.statuses.length === 0) {
        console.log(chalk.dim('    No checks configured'));
      } else {
        for (const status of checks.statuses) {
          let icon: string;
          let stateText: string;
          switch (status.state) {
            case 'success':
              icon = chalk.green('✓');
              stateText = chalk.green('pass');
              break;
            case 'failure':
              icon = chalk.red('✗');
              stateText = chalk.red('fail');
              break;
            case 'pending':
              icon = chalk.yellow('●');
              stateText = chalk.yellow('pending');
              break;
            default:
              icon = chalk.dim('○');
              stateText = chalk.dim(status.state);
          }
          console.log(`    ${icon} ${status.context.padEnd(30)} ${stateText}`);
        }
      }
      console.log('');
    }

    // Summary
    const passed = allChecks.filter(c => c.checks.state === 'success').length;
    const failed = allChecks.filter(c => c.checks.state === 'failure').length;
    const pending = allChecks.filter(c => c.checks.state === 'pending').length;

    console.log(chalk.dim('─'.repeat(50)));
    console.log(`Summary: ${chalk.green(passed + ' passed')}, ${chalk.red(failed + ' failed')}, ${chalk.yellow(pending + ' pending')}`);

    if (failed > 0) {
      console.log(chalk.dim('\nSome checks are failing. Fix issues before merging.'));
    } else if (pending > 0) {
      console.log(chalk.dim('\nSome checks are still running. Wait for completion.'));
    } else {
      console.log(chalk.green('\nAll checks passed! Ready to merge.'));
    }
  } catch (error) {
    spinner.fail('Failed to fetch check status');
    console.error(chalk.red(error instanceof Error ? error.message : String(error)));
  }
}
