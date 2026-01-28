import chalk from 'chalk';
import ora from 'ora';
import inquirer from 'inquirer';
import { loadManifest, getAllRepoInfo, getManifestRepoInfo } from '../../lib/manifest.js';
import { pathExists, getCurrentBranch, isGitRepo } from '../../lib/git.js';
import { findPRByBranch, getLinkedPRInfo, mergePullRequest } from '../../lib/github.js';
import type { LinkedPR, PRMergeOptions } from '../../types.js';

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
    const prResults: (LinkedPR & { branch: string } | null)[] = await Promise.all(
      clonedRepos.map(async (repo) => {
        const branch = await getCurrentBranch(repo.absolutePath);

        // Skip repos on their default branch (no PR expected)
        if (branch === repo.default_branch) {
          return null;
        }

        const pr = await findPRByBranch(repo.owner, repo.repo, branch);
        if (!pr) {
          return null;
        }

        const prInfo = await getLinkedPRInfo(repo.owner, repo.repo, pr.number, repo.name);
        return { ...prInfo, branch };
      })
    );

    // Check for manifest PR too
    const manifestInfo = getManifestRepoInfo(manifest, rootDir);
    let manifestPR: (LinkedPR & { branch: string }) | null = null;
    if (manifestInfo && await isGitRepo(manifestInfo.absolutePath)) {
      const manifestBranch = await getCurrentBranch(manifestInfo.absolutePath);
      if (manifestBranch !== manifestInfo.default_branch) {
        const pr = await findPRByBranch(manifestInfo.owner, manifestInfo.repo, manifestBranch);
        if (pr) {
          const prInfo = await getLinkedPRInfo(manifestInfo.owner, manifestInfo.repo, pr.number, manifestInfo.name);
          manifestPR = { ...prInfo, branch: manifestBranch };
        }
      }
    }

    const prsToMerge = prResults.filter((pr): pr is LinkedPR & { branch: string } => pr !== null);
    if (manifestPR) {
      prsToMerge.push(manifestPR);
    }
    spinner.stop();

    if (prsToMerge.length === 0) {
      console.log(chalk.yellow('No open PRs found.'));
      return;
    }

    // Determine the branch name for display
    const branches = [...new Set(prsToMerge.map(pr => pr.branch))];
    const branchDisplay = branches.length === 1 ? branches[0] : `${branches.length} branches`;

    console.log(chalk.blue(`Merging PRs for branch: ${chalk.cyan(branchDisplay)}\n`));

    // Check if all PRs are ready
    const notReady = prsToMerge.filter(
      (pr) => pr.state !== 'open' || !pr.approved || !pr.checksPass || !pr.mergeable
    );

    if (notReady.length > 0 && !options.force) {
      console.log(chalk.yellow('Some PRs are not ready to merge:\n'));

      for (const pr of notReady) {
        const issues: string[] = [];
        if (pr.state !== 'open') issues.push(`state: ${pr.state}`);
        if (!pr.approved) issues.push('not approved');
        if (!pr.checksPass) issues.push('checks not passing');
        if (!pr.mergeable) issues.push('not mergeable');

        console.log(`  ${pr.repoName} #${pr.number}: ${chalk.dim(issues.join(', '))}`);
      }

      console.log('');
      console.log(chalk.dim('Use --force to merge anyway (not recommended).'));
      return;
    }

    // Show what will be merged
    console.log('PRs to merge:');
    for (const pr of prsToMerge) {
      const statusIcon = pr.approved && pr.checksPass ? chalk.green('✓') : chalk.yellow('⚠');
      console.log(`  ${statusIcon} ${pr.repoName} #${pr.number}`);
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

    const results: { pr: LinkedPR; success: boolean; error?: string }[] = [];

    for (const pr of prsToMerge) {
      const prSpinner = ora(`Merging ${pr.repoName} #${pr.number}...`).start();

      try {
        const success = await mergePullRequest(pr.owner, pr.repo, pr.number, mergeOptions);

        if (success) {
          prSpinner.succeed(`${pr.repoName} #${pr.number}: merged`);
          results.push({ pr, success: true });
        } else {
          prSpinner.fail(`${pr.repoName} #${pr.number}: merge failed`);
          results.push({ pr, success: false, error: 'Merge API call failed' });

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
        prSpinner.fail(`${pr.repoName} #${pr.number}: ${errorMsg}`);
        results.push({ pr, success: false, error: errorMsg });

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
        console.log(chalk.dim('Switch to default branch with: codi-repo checkout main'));
      }
    } else {
      console.log(
        chalk.yellow(`Merged ${succeeded}/${prsToMerge.length} PRs. ${failed} failed.`)
      );

      for (const result of results.filter((r) => !r.success)) {
        console.log(chalk.red(`  ✗ ${result.pr.repoName}: ${result.error}`));
      }
    }
  } catch (error) {
    spinner.fail('Error during merge');
    console.error(chalk.red(error instanceof Error ? error.message : String(error)));
  }
}
