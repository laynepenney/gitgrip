import chalk from 'chalk';
import ora from 'ora';
import { loadManifest, getAllRepoInfo, getManifestRepoInfo } from '../lib/manifest.js';
import { pathExists, getGitInstance, getCurrentBranch, isGitRepo, fetchRemote } from '../lib/git.js';
import type { RepoInfo } from '../types.js';

interface RebaseOptions {
  push?: boolean;
}

interface RebaseResult {
  repo: RepoInfo;
  success: boolean;
  rebased: boolean;
  pushed?: boolean;
  error?: string;
}

/**
 * Rebase current branch across all repositories
 */
export async function rebase(targetBranch?: string, options: RebaseOptions = {}): Promise<void> {
  const { manifest, rootDir } = await loadManifest();
  let repos: RepoInfo[] = getAllRepoInfo(manifest, rootDir);

  // Include manifest repo if it exists
  const manifestInfo = getManifestRepoInfo(manifest, rootDir);
  if (manifestInfo && await isGitRepo(manifestInfo.absolutePath)) {
    repos = [...repos, manifestInfo];
  }

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

  // Check which repos are not on default branch
  const reposToRebase: { repo: RepoInfo; currentBranch: string; target: string }[] = [];

  for (const repo of clonedRepos) {
    const currentBranch = await getCurrentBranch(repo.absolutePath);
    if (currentBranch === repo.default_branch) {
      continue; // Skip repos on default branch
    }
    const target = targetBranch ?? `origin/${repo.default_branch}`;
    reposToRebase.push({ repo, currentBranch, target });
  }

  if (reposToRebase.length === 0) {
    console.log(chalk.yellow('All repositories are on their default branch. Nothing to rebase.'));
    return;
  }

  console.log(chalk.blue(`Rebasing ${reposToRebase.length} repository(s)...\n`));

  // First, fetch all repos in parallel
  console.log(chalk.dim('Fetching from remotes...\n'));
  await Promise.all(
    reposToRebase.map(async ({ repo }) => {
      try {
        await fetchRemote(repo.absolutePath);
      } catch {
        // Ignore fetch errors, rebase will fail if needed
      }
    })
  );

  // Rebase each repo
  const results: RebaseResult[] = [];

  for (const { repo, currentBranch, target } of reposToRebase) {
    const spinner = ora(`Rebasing ${repo.name} (${currentBranch} onto ${target})...`).start();

    try {
      const git = getGitInstance(repo.absolutePath);

      // Check for uncommitted changes
      const status = await git.status();
      if (status.modified.length > 0 || status.staged.length > 0) {
        spinner.fail(`${repo.name}: has uncommitted changes`);
        results.push({ repo, success: false, rebased: false, error: 'uncommitted changes' });
        continue;
      }

      // Perform rebase
      await git.rebase([target]);
      spinner.succeed(`${repo.name}: rebased onto ${target}`);

      let pushed = false;
      if (options.push) {
        spinner.start(`${repo.name}: force pushing...`);
        try {
          await git.push('origin', currentBranch, ['--force-with-lease']);
          spinner.succeed(`${repo.name}: force pushed`);
          pushed = true;
        } catch (pushError) {
          spinner.warn(`${repo.name}: rebased but push failed: ${pushError instanceof Error ? pushError.message : pushError}`);
        }
      }

      results.push({ repo, success: true, rebased: true, pushed });
    } catch (error) {
      const errorMsg = error instanceof Error ? error.message : String(error);

      // Check if it's a conflict
      if (errorMsg.includes('CONFLICT') || errorMsg.includes('could not apply')) {
        spinner.fail(`${repo.name}: rebase conflict`);
        console.log(chalk.yellow(`  Resolve conflicts in ${repo.absolutePath} and run:`));
        console.log(chalk.dim(`    cd ${repo.absolutePath}`));
        console.log(chalk.dim(`    git rebase --continue`));
        console.log(chalk.dim(`  Or abort with: git rebase --abort`));
      } else {
        spinner.fail(`${repo.name}: ${errorMsg}`);
      }

      results.push({ repo, success: false, rebased: false, error: errorMsg });
    }
  }

  // Summary
  console.log('');
  const rebased = results.filter((r) => r.rebased).length;
  const failed = results.filter((r) => !r.success).length;
  const pushed = results.filter((r) => r.pushed).length;

  if (failed === 0) {
    let msg = `Rebased ${rebased} repository(s).`;
    if (options.push && pushed > 0) {
      msg += ` Force pushed ${pushed}.`;
    }
    console.log(chalk.green(msg));

    if (!options.push && rebased > 0) {
      console.log(chalk.dim('\nTo push rebased branches: gr rebase --push'));
      console.log(chalk.dim('Or manually: gr push --force-with-lease'));
    }
  } else {
    console.log(chalk.yellow(`Rebased ${rebased}/${reposToRebase.length} repository(s). ${failed} failed.`));
  }
}
