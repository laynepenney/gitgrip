import chalk from 'chalk';
import ora from 'ora';
import inquirer from 'inquirer';
import { loadManifest, getAllRepoInfo, getManifestRepoInfo } from '../../lib/manifest.js';
import { pathExists, getCurrentBranch, isGitRepo } from '../../lib/git.js';
import { getPlatformAdapter } from '../../lib/platform/index.js';
import { getLinkedPRInfo } from '../../lib/linker.js';
import type { LinkedPR, PRMergeOptions, RepoInfo, CheckStatusDetails } from '../../types.js';

/**
 * Format check status details for display
 */
function formatCheckStatus(details?: CheckStatusDetails): string {
  if (!details) {
    return 'checks not passing';
  }

  if (details.total === 0) {
    return 'no checks';
  }

  // If all checks are skipped, indicate that
  if (details.skipped === details.total) {
    return 'checks skipped';
  }

  // Build a summary
  const parts: string[] = [];
  if (details.failed > 0) {
    parts.push(`${details.failed} failed`);
  }
  if (details.pending > 0) {
    parts.push(`${details.pending} pending`);
  }
  if (details.skipped > 0) {
    parts.push(`${details.skipped} skipped`);
  }
  if (details.passed > 0 && parts.length > 0) {
    parts.push(`${details.passed} passed`);
  }

  if (parts.length === 0) {
    return details.state === 'success' ? 'checks passed' : 'checks not passing';
  }

  return parts.join(', ');
}

interface MergeOptions {
  method?: 'merge' | 'squash' | 'rebase';
  deleteBranch?: boolean;
  force?: boolean;
}

/**
 * Merge all PRs for current branch
 */
export async function mergePRs(options: MergeOptions = {}): Promise<void> {
  const { manifest, rootDir } = await loadManifest();
  const repos = getAllRepoInfo(manifest, rootDir);

  // Check if any repos are cloned
  const clonedRepos = [];
  for (const repo of repos) {
    if (await pathExists(repo.absolutePath)) {
      clonedRepos.push(repo);
    }
  }

  if (clonedRepos.length === 0) {
    console.log(chalk.yellow('No repositories are cloned.'));
    return;
  }

  const spinner = ora('Checking PR status...').start();

  try {
    // Find all PRs for each repo based on its own current branch
    const prResults: ({ pr: LinkedPR & { branch: string }; repo: RepoInfo } | null)[] = await Promise.all(
      clonedRepos.map(async (repo) => {
        const branch = await getCurrentBranch(repo.absolutePath);

        // Skip repos on their default branch (no PR expected)
        if (branch === repo.default_branch) {
          return null;
        }

        const platform = getPlatformAdapter(repo.platformType, repo.platform);
        const pr = await platform.findPRByBranch(repo.owner, repo.repo, branch);
        if (!pr) {
          return null;
        }

        const prInfo = await getLinkedPRInfo(repo, pr.number);
        return { pr: { ...prInfo, branch }, repo };
      })
    );

    // Check for manifest PR too
    const manifestInfo = getManifestRepoInfo(manifest, rootDir);
    let manifestPREntry: { pr: LinkedPR & { branch: string }; repo: RepoInfo } | null = null;
    if (manifestInfo && await isGitRepo(manifestInfo.absolutePath)) {
      const manifestBranch = await getCurrentBranch(manifestInfo.absolutePath);
      if (manifestBranch !== manifestInfo.default_branch) {
        const platform = getPlatformAdapter(manifestInfo.platformType, manifestInfo.platform);
        const pr = await platform.findPRByBranch(manifestInfo.owner, manifestInfo.repo, manifestBranch);
        if (pr) {
          const prInfo = await getLinkedPRInfo(manifestInfo, pr.number);
          manifestPREntry = { pr: { ...prInfo, branch: manifestBranch }, repo: manifestInfo };
        }
      }
    }

    const prsToMerge = prResults.filter((entry): entry is { pr: LinkedPR & { branch: string }; repo: RepoInfo } => entry !== null);
    if (manifestPREntry) {
      prsToMerge.push(manifestPREntry);
    }
    spinner.stop();

    if (prsToMerge.length === 0) {
      console.log(chalk.yellow('No open PRs found.'));
      return;
    }

    // Determine the branch name for display
    const branches = [...new Set(prsToMerge.map(entry => entry.pr.branch))];
    const branchDisplay = branches.length === 1 ? branches[0] : `${branches.length} branches`;

    console.log(chalk.blue(`Merging PRs for branch: ${chalk.cyan(branchDisplay)}\n`));

    // Check if all PRs are ready
    const notReady = prsToMerge.filter(
      (entry) => entry.pr.state !== 'open' || !entry.pr.approved || !entry.pr.checksPass || !entry.pr.mergeable
    );

    if (notReady.length > 0 && !options.force) {
      console.log(chalk.yellow('Some PRs are not ready to merge:\n'));

      for (const entry of notReady) {
        const issues: string[] = [];
        if (entry.pr.state !== 'open') issues.push(`state: ${entry.pr.state}`);
        if (!entry.pr.approved) issues.push('not approved');
        if (!entry.pr.checksPass) issues.push(formatCheckStatus(entry.pr.checkDetails));
        if (!entry.pr.mergeable) issues.push('not mergeable');

        const platformLabel = entry.pr.platformType && entry.pr.platformType !== 'github' ? ` (${entry.pr.platformType})` : '';
        console.log(`  ${entry.pr.repoName}${chalk.dim(platformLabel)} #${entry.pr.number}: ${chalk.dim(issues.join(', '))}`);
      }

      console.log('');
      console.log(chalk.dim('Use --force to merge anyway (not recommended).'));
      return;
    }

    // Show what will be merged
    console.log('PRs to merge:');
    for (const entry of prsToMerge) {
      const statusIcon = entry.pr.approved && entry.pr.checksPass ? chalk.green('✓') : chalk.yellow('⚠');
      const platformLabel = entry.pr.platformType && entry.pr.platformType !== 'github' ? ` (${entry.pr.platformType})` : '';
      console.log(`  ${statusIcon} ${entry.pr.repoName}${chalk.dim(platformLabel)} #${entry.pr.number}`);
    }
    console.log('');

    // Confirm unless --force
    if (!options.force) {
      const { confirm } = await inquirer.prompt([
        {
          type: 'confirm',
          name: 'confirm',
          message: `Merge ${prsToMerge.length} PRs?`,
          default: false,
        },
      ]);

      if (!confirm) {
        console.log('Cancelled.');
        return;
      }
    }

    // Merge PRs one by one
    console.log('');
    const mergeOptions: PRMergeOptions = {
      method: options.method ?? 'merge',
      deleteBranch: options.deleteBranch ?? true,
    };

    const results: { entry: { pr: LinkedPR; repo: RepoInfo }; success: boolean; error?: string }[] = [];

    for (const entry of prsToMerge) {
      const platformLabel = entry.pr.platformType && entry.pr.platformType !== 'github' ? ` (${entry.pr.platformType})` : '';
      const prSpinner = ora(`Merging ${entry.pr.repoName}${platformLabel} #${entry.pr.number}...`).start();

      try {
        const platform = getPlatformAdapter(entry.repo.platformType, entry.repo.platform);
        let success = false;
        let usedMethod = mergeOptions.method ?? 'merge';
        let lastError = '';

        // Try the requested method first
        try {
          success = await platform.mergePullRequest(entry.pr.owner, entry.pr.repo, entry.pr.number, mergeOptions);
        } catch (error) {
          const errorMsg = error instanceof Error ? error.message : String(error);
          lastError = errorMsg;

          // If merge method not allowed (405), try fallback methods
          if (errorMsg.includes('405') || errorMsg.includes('not allowed') || errorMsg.includes('merge_method')) {
            // Get allowed methods if platform supports it
            const fallbackMethods: Array<'merge' | 'squash' | 'rebase'> = ['squash', 'rebase', 'merge'];
            const allowedMethods = platform.getAllowedMergeMethods
              ? await platform.getAllowedMergeMethods(entry.pr.owner, entry.pr.repo)
              : null;

            for (const method of fallbackMethods) {
              if (method === usedMethod) continue; // Skip the method we already tried
              if (allowedMethods && !allowedMethods[method]) continue; // Skip disallowed methods

              prSpinner.text = `${entry.pr.repoName}${platformLabel} #${entry.pr.number}: trying ${method}...`;

              try {
                success = await platform.mergePullRequest(entry.pr.owner, entry.pr.repo, entry.pr.number, {
                  ...mergeOptions,
                  method,
                });
                if (success) {
                  usedMethod = method;
                  break;
                }
              } catch {
                // Continue to next fallback method
              }
            }
          }
        }

        if (success) {
          const methodNote = usedMethod !== (mergeOptions.method ?? 'merge') ? ` (${usedMethod})` : '';
          prSpinner.succeed(`${entry.pr.repoName}${platformLabel} #${entry.pr.number}: merged${methodNote}`);
          results.push({ entry, success: true });
        } else {
          const suggestion = lastError.includes('405')
            ? ' (try --method squash or --method rebase)'
            : '';
          prSpinner.fail(`${entry.pr.repoName}${platformLabel} #${entry.pr.number}: merge failed${suggestion}`);
          results.push({ entry, success: false, error: lastError || 'Merge API call failed' });

          // Stop on first failure for all-or-nothing
          if (manifest.settings.merge_strategy === 'all-or-nothing') {
            console.log('');
            console.log(
              chalk.red('Stopping due to merge failure (all-or-nothing merge strategy).')
            );
            break;
          }
        }
      } catch (error) {
        const errorMsg = error instanceof Error ? error.message : String(error);
        prSpinner.fail(`${entry.pr.repoName}${platformLabel} #${entry.pr.number}: ${errorMsg}`);
        results.push({ entry, success: false, error: errorMsg });

        if (manifest.settings.merge_strategy === 'all-or-nothing') {
          console.log('');
          console.log(chalk.red('Stopping due to merge failure (all-or-nothing merge strategy).'));
          break;
        }
      }
    }

    // Summary
    console.log('');
    const succeeded = results.filter((r) => r.success).length;
    const failed = results.filter((r) => !r.success).length;

    if (failed === 0) {
      console.log(chalk.green(`All ${succeeded} PRs merged successfully!`));

      if (mergeOptions.deleteBranch) {
        console.log(chalk.dim('\nRemote branches have been deleted.'));
        console.log(chalk.dim('Switch to default branch with: gitgrip checkout main'));
      }
    } else {
      console.log(
        chalk.yellow(`Merged ${succeeded}/${prsToMerge.length} PRs. ${failed} failed.`)
      );

      for (const result of results.filter((r) => !r.success)) {
        console.log(chalk.red(`  ✗ ${result.entry.pr.repoName}: ${result.error}`));
      }
    }
  } catch (error) {
    spinner.fail('Error during merge');
    console.error(chalk.red(error instanceof Error ? error.message : String(error)));
  }
}
