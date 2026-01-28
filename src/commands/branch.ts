import chalk from 'chalk';
import ora from 'ora';
import { loadManifest, getAllRepoInfo, getManifestRepoInfo } from '../lib/manifest.js';
import {
  createBranchInAllRepos,
  checkoutBranchInAllRepos,
  pathExists,
  branchExists,
  getCurrentBranch,
  hasUncommittedChanges,
  isGitRepo,
  createBranch,
  checkoutBranch,
} from '../lib/git.js';
import type { RepoInfo } from '../types.js';

interface BranchOptions {
  create?: boolean;
  repo?: string[];
  includeManifest?: boolean;
}

/**
 * Create or checkout a branch across all repositories
 */
export async function branch(branchName: string, options: BranchOptions = {}): Promise<void> {
  const { manifest, rootDir } = await loadManifest();
  let repos = getAllRepoInfo(manifest, rootDir);

  // Filter by --repo flag if specified
  if (options.repo && options.repo.length > 0) {
    const requestedRepos = new Set(options.repo);
    const filteredRepos = repos.filter((r) => requestedRepos.has(r.name));

    // Check for unknown repo names
    const knownNames = new Set(repos.map((r) => r.name));
    const unknownRepos = options.repo.filter((name) => !knownNames.has(name));
    if (unknownRepos.length > 0) {
      console.log(chalk.yellow(`Unknown repositories: ${unknownRepos.join(', ')}`));
      console.log(chalk.dim(`Available: ${repos.map((r) => r.name).join(', ')}\n`));
    }

    repos = filteredRepos;
    if (repos.length === 0) {
      console.log(chalk.red('No valid repositories specified.'));
      return;
    }
  }

  // Filter to cloned repos only
  const clonedRepos: RepoInfo[] = [];
  for (const repo of repos) {
    if (await pathExists(repo.absolutePath)) {
      clonedRepos.push(repo);
    }
  }

  if (clonedRepos.length === 0) {
    console.log(chalk.yellow('No repositories are cloned. Run `codi-repo init --clone` first.'));
    return;
  }

  const notCloned = repos.length - clonedRepos.length;
  if (notCloned > 0) {
    console.log(chalk.dim(`Skipping ${notCloned} uncloned repositories\n`));
  }

  // Check if we should create or checkout
  let shouldCreate = options.create;

  if (!shouldCreate) {
    // Check if branch exists in any repo
    const branchExistsResults = await Promise.all(
      clonedRepos.map(async (repo) => ({
        repo,
        exists: await branchExists(repo.absolutePath, branchName),
      }))
    );

    const existingCount = branchExistsResults.filter((r) => r.exists).length;

    if (existingCount === 0) {
      // Branch doesn't exist anywhere, create it
      shouldCreate = true;
    } else if (existingCount < clonedRepos.length) {
      // Branch exists in some repos but not all
      console.log(
        chalk.yellow(
          `Branch '${branchName}' exists in ${existingCount}/${clonedRepos.length} repos`
        )
      );
      console.log(chalk.dim('Creating in remaining repos...\n'));

      // Create in repos where it doesn't exist, checkout where it does
      for (const { repo, exists } of branchExistsResults) {
        const spinner = ora(`${repo.name}...`).start();
        try {
          if (exists) {
            const { checkoutBranch } = await import('../lib/git.js');
            await checkoutBranch(repo.absolutePath, branchName);
            spinner.succeed(`${repo.name}: switched to ${branchName}`);
          } else {
            const { createBranch } = await import('../lib/git.js');
            await createBranch(repo.absolutePath, branchName);
            spinner.succeed(`${repo.name}: created ${branchName}`);
          }
        } catch (error) {
          spinner.fail(`${repo.name}: ${error instanceof Error ? error.message : error}`);
        }
      }
      return;
    }
  }

  if (shouldCreate) {
    console.log(chalk.blue(`Creating branch '${branchName}' in ${clonedRepos.length} repos...\n`));
    const results = await createBranchInAllRepos(clonedRepos, branchName);

    for (const result of results) {
      if (result.success) {
        console.log(chalk.green(`  ✓ ${result.repoName}: created`));
      } else {
        // Check if error is "branch already exists"
        if (result.error?.includes('already exists')) {
          console.log(chalk.yellow(`  - ${result.repoName}: branch already exists`));
        } else {
          console.log(chalk.red(`  ✗ ${result.repoName}: ${result.error}`));
        }
      }
    }
  } else {
    console.log(
      chalk.blue(`Checking out branch '${branchName}' in ${clonedRepos.length} repos...\n`)
    );
    const results = await checkoutBranchInAllRepos(clonedRepos, branchName);

    for (const result of results) {
      if (result.success) {
        console.log(chalk.green(`  ✓ ${result.repoName}: switched`));
      } else {
        console.log(chalk.red(`  ✗ ${result.repoName}: ${result.error}`));
      }
    }
  }

  // Handle manifest repo if configured
  const manifestInfo = getManifestRepoInfo(manifest, rootDir);
  if (manifestInfo && await isGitRepo(manifestInfo.absolutePath)) {
    const manifestHasChanges = await hasUncommittedChanges(manifestInfo.absolutePath);
    const shouldIncludeManifest = options.includeManifest || manifestHasChanges;

    if (shouldIncludeManifest) {
      const manifestBranchExists = await branchExists(manifestInfo.absolutePath, branchName);
      const spinner = ora(`${manifestInfo.name}...`).start();

      try {
        if (shouldCreate && !manifestBranchExists) {
          await createBranch(manifestInfo.absolutePath, branchName);
          spinner.succeed(`${manifestInfo.name}: created ${branchName}`);
        } else if (manifestBranchExists) {
          await checkoutBranch(manifestInfo.absolutePath, branchName);
          spinner.succeed(`${manifestInfo.name}: switched to ${branchName}`);
        } else {
          await createBranch(manifestInfo.absolutePath, branchName);
          spinner.succeed(`${manifestInfo.name}: created ${branchName}`);
        }
      } catch (error) {
        spinner.fail(`${manifestInfo.name}: ${error instanceof Error ? error.message : error}`);
      }
    }
  }

  // Summary
  console.log('');
  console.log(chalk.dim(`All repos now on branch: ${branchName}`));
}

/**
 * List branches across all repositories
 */
export async function listBranches(): Promise<void> {
  const { manifest, rootDir } = await loadManifest();
  const repos = getAllRepoInfo(manifest, rootDir);

  console.log(chalk.blue('Current branches:\n'));

  for (const repo of repos) {
    if (!(await pathExists(repo.absolutePath))) {
      console.log(`  ${chalk.dim(repo.name)}: ${chalk.dim('not cloned')}`);
      continue;
    }

    const currentBranch = await getCurrentBranch(repo.absolutePath);
    console.log(`  ${chalk.bold(repo.name)}: ${chalk.cyan(currentBranch)}`);
  }
}
