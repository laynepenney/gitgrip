import chalk from 'chalk';
import ora from 'ora';
import path from 'path';
import { mkdir, rm, readdir } from 'fs/promises';
import { loadManifest, getAllRepoInfo, getManifestRepoInfo } from '../lib/manifest.js';
import { pathExists, getGitInstance, isGitRepo } from '../lib/git.js';
import {
  sanitizeBranchName,
  getDefaultGriptreePath,
  readGriptreeConfig,
  writeGriptreeConfig,
  removeGriptreeConfig,
  readGriptreeRegistry,
  writeGriptreePointer,
  findLegacyGriptrees,
  registerLegacyGriptree,
  isGriptreePathValid,
} from '../lib/griptree.js';
import type { RepoInfo, TreeInfo, TreeRepoInfo, GriptreeConfig, GriptreeStatus } from '../types.js';

interface TreeAddOptions {
  path?: string;
}

/**
 * Create a tree (worktree-based workspace) for a branch
 */
export async function treeAdd(branch: string, options: TreeAddOptions = {}): Promise<void> {
  const { manifest, rootDir } = await loadManifest();
  const repos = getAllRepoInfo(manifest, rootDir);

  // Determine tree path
  const treePath = options.path
    ? path.resolve(options.path)
    : getDefaultGriptreePath(rootDir, branch);

  // Check if griptree already exists in registry
  const existingConfig = await readGriptreeConfig(rootDir, branch);
  if (existingConfig) {
    if (await pathExists(existingConfig.path)) {
      console.error(chalk.red(`Griptree already exists for branch '${branch}' at ${existingConfig.path}`));
      process.exit(1);
    } else {
      // Registry entry exists but directory is gone - clean up orphan
      console.log(chalk.yellow(`Cleaning up orphaned registry entry for branch '${branch}'...`));
      await removeGriptreeConfig(rootDir, branch);
    }
  }

  // Check if tree directory already exists
  if (await pathExists(treePath)) {
    console.error(chalk.red(`Directory already exists: ${treePath}`));
    process.exit(1);
  }

  console.log(chalk.blue(`Creating griptree for branch '${branch}' at ${treePath}\n`));

  // Create tree directory
  await mkdir(treePath, { recursive: true });

  // Create worktree for each repo in parallel
  const repoResults = await Promise.all(
    repos.map(async (repo): Promise<{ repo: RepoInfo; success: boolean; error?: string }> => {
      // Use the same relative path as in the manifest (e.g., ./codi -> codi)
      const worktreePath = path.join(treePath, repo.path);
      const spinner = ora(`Creating worktree for ${repo.name}...`).start();

      try {
        // Check if repo exists
        if (!await pathExists(repo.absolutePath)) {
          spinner.warn(`${repo.name}: not cloned, skipping`);
          return { repo, success: false, error: 'not cloned' };
        }

        const git = getGitInstance(repo.absolutePath);

        // Check if branch exists locally or remotely
        const branches = await git.branchLocal();
        if (!branches.all.includes(branch)) {
          // Try to fetch and create from remote
          try {
            await git.fetch('origin', branch);
            await git.raw(['worktree', 'add', '-b', branch, worktreePath, `origin/${branch}`]);
          } catch {
            // Branch doesn't exist anywhere, create from current HEAD
            await git.raw(['worktree', 'add', '-b', branch, worktreePath]);
          }
        } else {
          // Branch exists locally
          await git.raw(['worktree', 'add', worktreePath, branch]);
        }

        spinner.succeed(`${repo.name}: worktree created`);
        return { repo, success: true };
      } catch (error) {
        const errorMsg = error instanceof Error ? error.message : String(error);

        // Check for common errors
        if (errorMsg.includes('already checked out')) {
          spinner.fail(`${repo.name}: branch '${branch}' is already checked out in another worktree`);
        } else {
          spinner.fail(`${repo.name}: ${errorMsg}`);
        }
        return { repo, success: false, error: errorMsg };
      }
    })
  );

  // Handle manifest repo if it exists
  const manifestInfo = getManifestRepoInfo(manifest, rootDir);
  if (manifestInfo && await isGitRepo(manifestInfo.absolutePath)) {
    const manifestWorktreePath = path.join(treePath, '.gitgrip', 'manifests');
    const spinner = ora('Creating worktree for manifest...').start();

    try {
      await mkdir(path.join(treePath, '.gitgrip'), { recursive: true });
      const git = getGitInstance(manifestInfo.absolutePath);

      const branches = await git.branchLocal();
      if (!branches.all.includes(branch)) {
        try {
          await git.fetch('origin', branch);
          await git.raw(['worktree', 'add', '-b', branch, manifestWorktreePath, `origin/${branch}`]);
        } catch {
          await git.raw(['worktree', 'add', '-b', branch, manifestWorktreePath]);
        }
      } else {
        await git.raw(['worktree', 'add', manifestWorktreePath, branch]);
      }

      spinner.succeed('manifest: worktree created');
    } catch (error) {
      const errorMsg = error instanceof Error ? error.message : String(error);
      if (errorMsg.includes('already checked out')) {
        spinner.fail(`manifest: branch '${branch}' is already checked out in another worktree`);
      } else {
        spinner.fail(`manifest: ${errorMsg}`);
      }
    }
  }

  // Write griptree config to central registry
  const config: GriptreeConfig = {
    branch,
    path: treePath,
    createdAt: new Date().toISOString(),
    locked: false,
  };
  await writeGriptreeConfig(rootDir, branch, config);

  // Write pointer file in griptree directory
  await writeGriptreePointer(treePath, {
    mainWorkspace: rootDir,
    branch,
  });

  // Summary
  console.log('');
  const succeeded = repoResults.filter(r => r.success).length;
  const failed = repoResults.filter(r => !r.success).length;

  if (failed === 0) {
    console.log(chalk.green(`Griptree created successfully with ${succeeded} repo(s).`));
    console.log(chalk.dim(`\nTo work in this griptree:\n  cd ${treePath}`));
  } else {
    console.log(chalk.yellow(`Griptree created with ${succeeded} repo(s). ${failed} failed.`));
  }
}

/**
 * List all trees in the workspace
 */
export async function treeList(): Promise<void> {
  const { rootDir } = await loadManifest();

  // Read from central registry
  let registryConfigs = await readGriptreeRegistry(rootDir);

  // Find and auto-register legacy griptrees
  const legacyGriptrees = await findLegacyGriptrees(rootDir);
  for (const legacy of legacyGriptrees) {
    const spinner = ora(`Registering legacy griptree '${legacy.config.branch}'...`).start();
    try {
      const config = await registerLegacyGriptree(rootDir, legacy.path, legacy.config);
      registryConfigs.push(config);
      spinner.succeed(`Registered legacy griptree '${legacy.config.branch}'`);
    } catch (error) {
      spinner.fail(`Failed to register legacy griptree: ${error instanceof Error ? error.message : String(error)}`);
    }
  }

  // Build tree info list with status
  const trees: TreeInfo[] = [];
  const orphanedBranches: string[] = [];

  for (const config of registryConfigs) {
    const exists = await isGriptreePathValid(config);

    if (!exists) {
      // Auto-prune: remove orphaned registry entries
      orphanedBranches.push(config.branch);
      await removeGriptreeConfig(rootDir, config.branch);
      continue;
    }

    // Get repo info for this tree
    const repoInfos: TreeRepoInfo[] = [];

    try {
      const subentries = await readdir(config.path, { withFileTypes: true });
      for (const subentry of subentries) {
        if (!subentry.isDirectory() || subentry.name.startsWith('.')) continue;

        const repoPath = path.join(config.path, subentry.name);
        const isRepo = await isGitRepo(repoPath);

        if (isRepo) {
          const git = getGitInstance(repoPath);
          try {
            const branchName = (await git.revparse(['--abbrev-ref', 'HEAD'])).trim();
            repoInfos.push({
              name: subentry.name,
              path: repoPath,
              branch: branchName,
              exists: true,
            });
          } catch {
            repoInfos.push({
              name: subentry.name,
              path: repoPath,
              branch: 'unknown',
              exists: true,
            });
          }
        }
      }
    } catch {
      // Skip if we can't read the directory
    }

    trees.push({
      branch: config.branch,
      path: config.path,
      locked: config.locked,
      repos: repoInfos,
      status: 'active' as GriptreeStatus,
    });
  }

  // Report auto-pruned orphans
  if (orphanedBranches.length > 0) {
    console.log(chalk.yellow(`Auto-pruned ${orphanedBranches.length} orphaned griptree(s): ${orphanedBranches.join(', ')}\n`));
  }

  if (trees.length === 0) {
    console.log(chalk.yellow('No griptrees found.'));
    console.log(chalk.dim('\nCreate one with: gr tree add <branch>'));
    return;
  }

  console.log(chalk.blue('Griptrees:\n'));

  for (const tree of trees) {
    const lockIcon = tree.locked ? chalk.yellow(' [locked]') : '';
    console.log(chalk.bold(`  ${tree.branch}${lockIcon}`));
    console.log(chalk.dim(`    Path: ${tree.path}`));
    console.log(chalk.dim(`    Repos: ${tree.repos.length}`));
    console.log('');
  }
}

/**
 * Remove a tree
 */
export async function treeRemove(branch: string, options: { force?: boolean } = {}): Promise<void> {
  const { manifest, rootDir } = await loadManifest();
  const repos = getAllRepoInfo(manifest, rootDir);

  // Find the tree in central registry
  const config = await readGriptreeConfig(rootDir, branch);
  if (!config) {
    console.error(chalk.red(`Griptree for branch '${branch}' not found.`));
    process.exit(1);
  }

  const treePath = config.path;

  // Check if locked
  if (config.locked && !options.force) {
    console.error(chalk.red(`Griptree for branch '${branch}' is locked.`));
    console.log(chalk.dim('Use --force to remove anyway, or unlock first with: gr tree unlock ' + branch));
    process.exit(1);
  }

  console.log(chalk.blue(`Removing griptree for branch '${branch}' at ${treePath}\n`));

  // Check if griptree directory exists
  const treeExists = await pathExists(treePath);

  if (treeExists) {
    // Remove worktrees from each repo in parallel
    const results = await Promise.all(
      repos.map(async (repo): Promise<{ repo: RepoInfo; success: boolean; error?: string }> => {
        // Use the same relative path as in the manifest (e.g., ./codi -> codi)
        const worktreePath = path.join(treePath, repo.path);
        const spinner = ora(`Removing worktree for ${repo.name}...`).start();

        try {
          if (!await pathExists(repo.absolutePath)) {
            spinner.warn(`${repo.name}: main repo not found, skipping`);
            return { repo, success: true };
          }

          if (!await pathExists(worktreePath)) {
            spinner.succeed(`${repo.name}: worktree not found, skipping`);
            return { repo, success: true };
          }

          const git = getGitInstance(repo.absolutePath);
          await git.raw(['worktree', 'remove', worktreePath, '--force']);
          spinner.succeed(`${repo.name}: worktree removed`);
          return { repo, success: true };
        } catch (error) {
          const errorMsg = error instanceof Error ? error.message : String(error);
          spinner.fail(`${repo.name}: ${errorMsg}`);
          return { repo, success: false, error: errorMsg };
        }
      })
    );

    // Remove manifest worktree
    const manifestInfo = getManifestRepoInfo(manifest, rootDir);
    if (manifestInfo && await isGitRepo(manifestInfo.absolutePath)) {
      const manifestWorktreePath = path.join(treePath, '.gitgrip', 'manifests');
      const spinner = ora('Removing worktree for manifest...').start();

      try {
        if (await pathExists(manifestWorktreePath)) {
          const git = getGitInstance(manifestInfo.absolutePath);
          await git.raw(['worktree', 'remove', manifestWorktreePath, '--force']);
          spinner.succeed('manifest: worktree removed');
        } else {
          spinner.succeed('manifest: worktree not found, skipping');
        }
      } catch (error) {
        const errorMsg = error instanceof Error ? error.message : String(error);
        spinner.fail(`manifest: ${errorMsg}`);
      }
    }

    // Remove the tree directory
    try {
      await rm(treePath, { recursive: true, force: true });
    } catch (error) {
      console.error(chalk.red(`Failed to remove griptree directory: ${error instanceof Error ? error.message : String(error)}`));
    }
  } else {
    console.log(chalk.yellow(`Griptree directory not found, cleaning up registry entry...`));
  }

  // Remove from central registry
  await removeGriptreeConfig(rootDir, branch);

  console.log(chalk.green(`\nGriptree for branch '${branch}' removed successfully.`));
}

/**
 * Lock a tree to prevent accidental removal
 */
export async function treeLock(branch: string): Promise<void> {
  const { rootDir } = await loadManifest();

  const config = await readGriptreeConfig(rootDir, branch);
  if (!config) {
    console.error(chalk.red(`Griptree for branch '${branch}' not found.`));
    process.exit(1);
  }

  if (config.locked) {
    console.log(chalk.yellow(`Griptree for branch '${branch}' is already locked.`));
    return;
  }

  config.locked = true;
  config.lockedAt = new Date().toISOString();
  await writeGriptreeConfig(rootDir, branch, config);
  console.log(chalk.green(`Griptree for branch '${branch}' is now locked.`));
}

/**
 * Unlock a tree
 */
export async function treeUnlock(branch: string): Promise<void> {
  const { rootDir } = await loadManifest();

  const config = await readGriptreeConfig(rootDir, branch);
  if (!config) {
    console.error(chalk.red(`Griptree for branch '${branch}' not found.`));
    process.exit(1);
  }

  if (!config.locked) {
    console.log(chalk.yellow(`Griptree for branch '${branch}' is not locked.`));
    return;
  }

  config.locked = false;
  config.lockedAt = undefined;
  config.lockedReason = undefined;
  await writeGriptreeConfig(rootDir, branch, config);
  console.log(chalk.green(`Griptree for branch '${branch}' is now unlocked.`));
}
