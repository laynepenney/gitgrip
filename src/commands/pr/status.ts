import chalk from 'chalk';
import ora from 'ora';
import { loadManifest, getAllRepoInfo, getManifestRepoInfo } from '../../lib/manifest.js';
import { pathExists, getCurrentBranch, isGitRepo } from '../../lib/git.js';
import { findPRByBranch, getLinkedPRInfo } from '../../lib/github.js';
import type { LinkedPR } from '../../types.js';

interface StatusOptions {
  json?: boolean;
}

/**
 * Show status of PRs for current branch
 */
export async function prStatus(options: StatusOptions = {}): Promise<void> {
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

  const spinner = ora('Fetching PR status...').start();

  try {
    // Find PRs for each repo based on its own current branch (not a single global branch)
    const prStatuses: (LinkedPR & { branch: string } | null)[] = await Promise.all(
      clonedRepos.map(async (repo) => {
        const branch = await getCurrentBranch(repo.absolutePath);

        // Skip repos on their default branch (no PR expected)
        if (branch === repo.default_branch) {
          return null;
        }

        // Find PR for this repo's current branch
        const pr = await findPRByBranch(repo.owner, repo.repo, branch);
        if (!pr) {
          return null;
        }

        // Get full PR info
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

    spinner.stop();

    const foundPRs = prStatuses.filter((pr): pr is LinkedPR & { branch: string } => pr !== null);
    if (manifestPR) {
      foundPRs.push(manifestPR);
    }

    if (foundPRs.length === 0) {
      console.log(chalk.yellow('No open PRs found.'));
      console.log(chalk.dim('\nCreate PRs with: gitgrip pr create'));
      return;
    }

    // Determine the branch name for display (use the common branch if all same, otherwise show per-PR)
    const branches = [...new Set(foundPRs.map(pr => pr.branch))];
    const branchDisplay = branches.length === 1 ? branches[0] : `${branches.length} branches`;

    console.log(chalk.blue(`PR Status for branch: ${chalk.cyan(branchDisplay)}\n`));

    if (options.json) {
      console.log(JSON.stringify(foundPRs, null, 2));
      return;
    }

    // Display as table
    console.log(
      chalk.dim(
        '  Repo                  PR        Status     Approved   Checks    Mergeable'
      )
    );
    console.log(chalk.dim('  ' + '-'.repeat(76)));

    for (const pr of foundPRs) {
      const repoName = pr.repoName.padEnd(20);
      const prNum = `#${pr.number}`.padEnd(8);

      let statusIcon: string;
      let statusText: string;
      switch (pr.state) {
        case 'open':
          statusIcon = chalk.green('●');
          statusText = chalk.green('open'.padEnd(10));
          break;
        case 'merged':
          statusIcon = chalk.magenta('●');
          statusText = chalk.magenta('merged'.padEnd(10));
          break;
        case 'closed':
          statusIcon = chalk.red('●');
          statusText = chalk.red('closed'.padEnd(10));
          break;
      }

      const approved = pr.approved
        ? chalk.green('✓'.padEnd(10))
        : chalk.yellow('pending'.padEnd(10));

      const checks = pr.checksPass
        ? chalk.green('✓'.padEnd(10))
        : chalk.yellow('pending'.padEnd(10));

      const mergeable = pr.mergeable
        ? chalk.green('✓')
        : chalk.red('✗');

      console.log(`  ${repoName}  ${prNum}  ${statusText}  ${approved}  ${checks}  ${mergeable}`);
    }

    // Summary
    console.log('');
    const allApproved = foundPRs.every((pr) => pr.approved);
    const allChecksPass = foundPRs.every((pr) => pr.checksPass);
    const allMergeable = foundPRs.every((pr) => pr.mergeable && pr.state === 'open');
    const allOpen = foundPRs.every((pr) => pr.state === 'open');

    if (allOpen && allApproved && allChecksPass && allMergeable) {
      console.log(chalk.green('  ✓ All PRs are ready to merge'));
      console.log(chalk.dim('\n  Run `gitgrip pr merge` to merge all PRs.'));
    } else {
      const issues: string[] = [];
      if (!allOpen) issues.push('some PRs are not open');
      if (!allApproved) issues.push('some PRs need approval');
      if (!allChecksPass) issues.push('some checks are pending');
      if (!allMergeable) issues.push('some PRs are not mergeable');
      console.log(chalk.yellow(`  ⚠ Not ready to merge: ${issues.join(', ')}`));
    }

    // Show links
    console.log('');
    console.log(chalk.dim('  Links:'));
    for (const pr of foundPRs) {
      console.log(chalk.dim(`    ${pr.repoName}: ${pr.url}`));
    }
  } catch (error) {
    spinner.fail('Failed to fetch PR status');
    console.error(chalk.red(error instanceof Error ? error.message : String(error)));
  }
}
