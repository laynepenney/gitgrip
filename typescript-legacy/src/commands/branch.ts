import chalk from 'chalk';
import ora from 'ora';
import inquirer from 'inquirer';
import { loadManifest, getAllRepoInfo, getManifestRepoInfo } from '../lib/manifest.js';
import {
  createBranchInAllRepos,
  checkoutBranchInAllRepos,
  pathExists,
  branchExists,
  remoteBranchExists,
  getCurrentBranch,
  hasUncommittedChanges,
  isGitRepo,
  createBranch,
  checkoutBranch,
  deleteLocalBranch,
  deleteRemoteBranch,
  isBranchMerged,
  resetHard,
} from '../lib/git.js';
import type { RepoInfo } from '../types.js';

interface BranchOptions {
  create?: boolean;
  delete?: boolean;
  repo?: string[];
  includeManifest?: boolean;
  local?: boolean;
  remote?: boolean;
  force?: boolean;
  /** Move N commits from current branch to new branch */
  moveCommit?: number;
}

/**
 * Delete a branch across all repositories
 */
export async function deleteBranch(branchName: string, options: BranchOptions = {}): Promise<void> {
  const { manifest, rootDir } = await loadManifest();
  let repos = getAllRepoInfo(manifest, rootDir);

  // Filter by --repo flag if specified
  if (options.repo && options.repo.length > 0) {
    const requestedRepos = new Set(options.repo);
    repos = repos.filter((r) => requestedRepos.has(r.name));
  }

  // Filter to cloned repos only
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

  // Determine what to delete
  const deleteLocal = options.local || (!options.local && !options.remote);
  const deleteRemote = options.remote || (!options.local && !options.remote);

  // Check which repos have this branch
  const branchStatus = await Promise.all(
    clonedRepos.map(async (repo) => {
      const currentBranch = await getCurrentBranch(repo.absolutePath);
      const hasLocal = await branchExists(repo.absolutePath, branchName);
      const hasRemote = await remoteBranchExists(repo.absolutePath, branchName);
      const merged = hasLocal ? await isBranchMerged(repo.absolutePath, branchName, repo.default_branch) : true;
      return { repo, currentBranch, hasLocal, hasRemote, merged };
    })
  );

  const hasAnyBranch = branchStatus.some((r) => r.hasLocal || r.hasRemote);
  if (!hasAnyBranch) {
    console.log(chalk.yellow(`Branch '${branchName}' not found in any repository.`));
    return;
  }

  // Warn about current branch
  const onCurrentBranch = branchStatus.filter((r) => r.currentBranch === branchName);
  if (onCurrentBranch.length > 0) {
    console.log(chalk.red(`Cannot delete '${branchName}': currently checked out in:`));
    for (const r of onCurrentBranch) {
      console.log(`  - ${r.repo.name}`);
    }
    console.log(chalk.dim(`\nSwitch to a different branch first: gitgrip checkout main`));
    return;
  }

  // Warn about unmerged branches
  const unmerged = branchStatus.filter((r) => r.hasLocal && !r.merged);
  if (unmerged.length > 0 && !options.force) {
    console.log(chalk.yellow(`Warning: Branch '${branchName}' has unmerged changes in:`));
    for (const r of unmerged) {
      console.log(`  - ${r.repo.name}`);
    }
    console.log('');

    const { confirm } = await inquirer.prompt([
      {
        type: 'confirm',
        name: 'confirm',
        message: 'Delete anyway?',
        default: false,
      },
    ]);

    if (!confirm) {
      console.log('Cancelled.');
      return;
    }
  }

  console.log(chalk.blue(`Deleting branch '${branchName}'...\n`));

  // Delete in each repo
  for (const { repo, hasLocal, hasRemote } of branchStatus) {
    if (!hasLocal && !hasRemote) continue;

    const spinner = ora(`${repo.name}...`).start();
    const actions: string[] = [];

    try {
      // Delete local
      if (deleteLocal && hasLocal) {
        await deleteLocalBranch(repo.absolutePath, branchName, options.force);
        actions.push('local');
      }

      // Delete remote
      if (deleteRemote && hasRemote) {
        await deleteRemoteBranch(repo.absolutePath, branchName);
        actions.push('remote');
      }

      spinner.succeed(`${repo.name}: deleted (${actions.join(' + ')})`);
    } catch (error) {
      spinner.fail(`${repo.name}: ${error instanceof Error ? error.message : error}`);
    }
  }

  // Handle manifest if needed
  const manifestInfo = getManifestRepoInfo(manifest, rootDir);
  if (options.includeManifest && manifestInfo && await isGitRepo(manifestInfo.absolutePath)) {
    const hasLocal = await branchExists(manifestInfo.absolutePath, branchName);
    const hasRemote = await remoteBranchExists(manifestInfo.absolutePath, branchName);

    if (hasLocal || hasRemote) {
      const spinner = ora(`${manifestInfo.name}...`).start();
      const actions: string[] = [];

      try {
        if (deleteLocal && hasLocal) {
          await deleteLocalBranch(manifestInfo.absolutePath, branchName, options.force);
          actions.push('local');
        }
        if (deleteRemote && hasRemote) {
          await deleteRemoteBranch(manifestInfo.absolutePath, branchName);
          actions.push('remote');
        }
        spinner.succeed(`${manifestInfo.name}: deleted (${actions.join(' + ')})`);
      } catch (error) {
        spinner.fail(`${manifestInfo.name}: ${error instanceof Error ? error.message : error}`);
      }
    }
  }

  console.log(chalk.green(`\nBranch '${branchName}' deleted.`));
}

/**
 * Move commits from current branch to a new branch
 * Creates the new branch at HEAD, then resets the original branch back
 */
async function moveCommitsToNewBranch(
  repoPath: string,
  newBranchName: string,
  commitCount: number
): Promise<void> {
  // Create the new branch at the current HEAD
  await createBranch(repoPath, newBranchName);

  // Get the current branch name before switching
  const currentBranch = await getCurrentBranch(repoPath);

  // Reset the current branch back by N commits
  await resetHard(repoPath, `HEAD~${commitCount}`);

  // Switch to the new branch
  await checkoutBranch(repoPath, newBranchName);

  console.log(chalk.dim(`  Moved ${commitCount} commit(s) from ${currentBranch} to ${newBranchName}`));
}

/**
 * Create or checkout a branch across all repositories
 */
export async function branch(branchName: string, options: BranchOptions = {}): Promise<void> {
  // Handle delete separately
  if (options.delete) {
    return deleteBranch(branchName, options);
  }

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
    console.log(chalk.yellow('No repositories are cloned. Run `gitgrip init --clone` first.'));
    return;
  }

  const notCloned = repos.length - clonedRepos.length;
  if (notCloned > 0) {
    console.log(chalk.dim(`Skipping ${notCloned} uncloned repositories\n`));
  }

  // Handle move-commit: move N commits from current branch to new branch
  if (options.moveCommit && options.moveCommit > 0) {
    const commitCount = options.moveCommit;

    console.log(chalk.blue(`Moving ${commitCount} commit(s) to new branch '${branchName}'...\n`));

    for (const repo of clonedRepos) {
      const spinner = ora(`${repo.name}...`).start();

      try {
        // Check for uncommitted changes
        const hasChanges = await hasUncommittedChanges(repo.absolutePath);
        if (hasChanges) {
          spinner.fail(`${repo.name}: has uncommitted changes, skipping`);
          continue;
        }

        // Check if branch already exists
        const exists = await branchExists(repo.absolutePath, branchName);
        if (exists) {
          spinner.fail(`${repo.name}: branch '${branchName}' already exists`);
          continue;
        }

        const currentBranch = await getCurrentBranch(repo.absolutePath);
        await moveCommitsToNewBranch(repo.absolutePath, branchName, commitCount);
        spinner.succeed(`${repo.name}: moved ${commitCount} commit(s) from ${currentBranch}`);
      } catch (error) {
        spinner.fail(`${repo.name}: ${error instanceof Error ? error.message : error}`);
      }
    }

    console.log('');
    console.log(chalk.dim(`Repos now on branch: ${branchName}`));
    console.log(chalk.dim(`Original branches have been reset back ${commitCount} commit(s).`));
    return;
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
