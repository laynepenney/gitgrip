import chalk from 'chalk';
import ora from 'ora';
import path from 'path';
import { mkdir, rm, readdir, writeFile, readFile } from 'fs/promises';
import { loadManifest, getAllRepoInfo, getManifestRepoInfo } from '../lib/manifest.js';
import { pathExists, getGitInstance, isGitRepo } from '../lib/git.js';
import type { RepoInfo, GriptreeInfo, GriptreeRepoInfo } from '../types.js';

const GRIPTREE_CONFIG_FILE = '.griptree';

interface GriptreeAddOptions {
  path?: string;
}

interface GriptreeConfig {
  branch: string;
  locked: boolean;
  createdAt: string;
}

/**
 * Sanitize branch name for use as directory name
 */
function sanitizeBranchName(branch: string): string {
  return branch.replace(/\//g, '-');
}

/**
 * Get the default griptree path for a branch
 */
function getDefaultGriptreePath(rootDir: string, branch: string): string {
  const parentDir = path.dirname(rootDir);
  const sanitized = sanitizeBranchName(branch);
  return path.join(parentDir, sanitized);
}

/**
 * Read griptree config from a directory
 */
async function readGriptreeConfig(griptreePath: string): Promise<GriptreeConfig | null> {
  const configPath = path.join(griptreePath, GRIPTREE_CONFIG_FILE);
  try {
    const content = await readFile(configPath, 'utf-8');
    return JSON.parse(content);
  } catch {
    return null;
  }
}

/**
 * Write griptree config to a directory
 */
async function writeGriptreeConfig(griptreePath: string, config: GriptreeConfig): Promise<void> {
  const configPath = path.join(griptreePath, GRIPTREE_CONFIG_FILE);
  await writeFile(configPath, JSON.stringify(config, null, 2));
}

/**
 * Find a griptree by branch name
 */
async function findGriptreeByBranch(rootDir: string, branch: string): Promise<{ path: string; config: GriptreeConfig } | null> {
  const parentDir = path.dirname(rootDir);

  try {
    const entries = await readdir(parentDir, { withFileTypes: true });

    for (const entry of entries) {
      if (!entry.isDirectory()) continue;

      const dirPath = path.join(parentDir, entry.name);
      const config = await readGriptreeConfig(dirPath);

      if (config && config.branch === branch) {
        return { path: dirPath, config };
      }
    }
  } catch {
    return null;
  }

  return null;
}

/**
 * Create a griptree (worktree-based workspace) for a branch
 */
export async function griptreeAdd(branch: string, options: GriptreeAddOptions = {}): Promise<void> {
  const { manifest, rootDir } = await loadManifest();
  const repos = getAllRepoInfo(manifest, rootDir);

  // Determine griptree path
  const griptreePath = options.path
    ? path.resolve(options.path)
    : getDefaultGriptreePath(rootDir, branch);

  // Check if griptree already exists
  if (await pathExists(griptreePath)) {
    const config = await readGriptreeConfig(griptreePath);
    if (config) {
      console.error(chalk.red(`Griptree already exists at ${griptreePath} for branch '${config.branch}'`));
      process.exit(1);
    }
    console.error(chalk.red(`Directory already exists: ${griptreePath}`));
    process.exit(1);
  }

  console.log(chalk.blue(`Creating griptree for branch '${branch}' at ${griptreePath}\n`));

  // Create griptree directory
  await mkdir(griptreePath, { recursive: true });

  // Create worktree for each repo in parallel
  const repoResults = await Promise.all(
    repos.map(async (repo): Promise<{ repo: RepoInfo; success: boolean; error?: string }> => {
      const worktreePath = path.join(griptreePath, repo.name);
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
    const manifestWorktreePath = path.join(griptreePath, '.gitgrip', 'manifests');
    const spinner = ora('Creating worktree for manifest...').start();

    try {
      await mkdir(path.join(griptreePath, '.gitgrip'), { recursive: true });
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

  // Write griptree config
  await writeGriptreeConfig(griptreePath, {
    branch,
    locked: false,
    createdAt: new Date().toISOString(),
  });

  // Summary
  console.log('');
  const succeeded = repoResults.filter(r => r.success).length;
  const failed = repoResults.filter(r => !r.success).length;

  if (failed === 0) {
    console.log(chalk.green(`Griptree created successfully with ${succeeded} repo(s).`));
    console.log(chalk.dim(`\nTo work in this griptree:\n  cd ${griptreePath}`));
  } else {
    console.log(chalk.yellow(`Griptree created with ${succeeded} repo(s). ${failed} failed.`));
  }
}

/**
 * List all griptrees in the workspace
 */
export async function griptreeList(): Promise<void> {
  const { rootDir } = await loadManifest();
  const parentDir = path.dirname(rootDir);

  // Find all directories that contain a .griptree config file
  const griptrees: GriptreeInfo[] = [];

  try {
    const entries = await readdir(parentDir, { withFileTypes: true });

    for (const entry of entries) {
      if (!entry.isDirectory()) continue;

      const dirPath = path.join(parentDir, entry.name);
      const config = await readGriptreeConfig(dirPath);

      if (config) {
        // Get repo info for this griptree
        const repoInfos: GriptreeRepoInfo[] = [];

        try {
          const subentries = await readdir(dirPath, { withFileTypes: true });
          for (const subentry of subentries) {
            if (!subentry.isDirectory() || subentry.name.startsWith('.')) continue;

            const repoPath = path.join(dirPath, subentry.name);
            const isRepo = await isGitRepo(repoPath);

            if (isRepo) {
              const git = getGitInstance(repoPath);
              try {
                const branch = (await git.revparse(['--abbrev-ref', 'HEAD'])).trim();
                repoInfos.push({
                  name: subentry.name,
                  path: repoPath,
                  branch,
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

        griptrees.push({
          branch: config.branch,
          path: dirPath,
          locked: config.locked,
          repos: repoInfos,
        });
      }
    }
  } catch (error) {
    console.error(chalk.red(`Failed to list griptrees: ${error instanceof Error ? error.message : String(error)}`));
    process.exit(1);
  }

  if (griptrees.length === 0) {
    console.log(chalk.yellow('No griptrees found.'));
    console.log(chalk.dim('\nCreate one with: gr griptree add <branch>'));
    return;
  }

  console.log(chalk.blue('Griptrees:\n'));

  for (const griptree of griptrees) {
    const lockIcon = griptree.locked ? chalk.yellow(' [locked]') : '';
    console.log(chalk.bold(`  ${griptree.branch}${lockIcon}`));
    console.log(chalk.dim(`    Path: ${griptree.path}`));
    console.log(chalk.dim(`    Repos: ${griptree.repos.length}`));
    console.log('');
  }
}

/**
 * Remove a griptree
 */
export async function griptreeRemove(branch: string, options: { force?: boolean } = {}): Promise<void> {
  const { manifest, rootDir } = await loadManifest();
  const repos = getAllRepoInfo(manifest, rootDir);

  // Find the griptree
  const found = await findGriptreeByBranch(rootDir, branch);
  if (!found) {
    console.error(chalk.red(`Griptree for branch '${branch}' not found.`));
    process.exit(1);
  }

  const { path: griptreePath, config } = found;

  // Check if locked
  if (config.locked && !options.force) {
    console.error(chalk.red(`Griptree for branch '${branch}' is locked.`));
    console.log(chalk.dim('Use --force to remove anyway, or unlock first with: gr griptree unlock ' + branch));
    process.exit(1);
  }

  console.log(chalk.blue(`Removing griptree for branch '${branch}' at ${griptreePath}\n`));

  // Remove worktrees from each repo in parallel
  const results = await Promise.all(
    repos.map(async (repo): Promise<{ repo: RepoInfo; success: boolean; error?: string }> => {
      const worktreePath = path.join(griptreePath!, repo.name);
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
    const manifestWorktreePath = path.join(griptreePath, '.gitgrip', 'manifests');
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

  // Remove the griptree directory
  try {
    await rm(griptreePath, { recursive: true, force: true });
    console.log(chalk.green(`\nGriptree for branch '${branch}' removed successfully.`));
  } catch (error) {
    console.error(chalk.red(`Failed to remove griptree directory: ${error instanceof Error ? error.message : String(error)}`));
  }
}

/**
 * Lock a griptree to prevent accidental removal
 */
export async function griptreeLock(branch: string): Promise<void> {
  const { rootDir } = await loadManifest();

  const found = await findGriptreeByBranch(rootDir, branch);
  if (!found) {
    console.error(chalk.red(`Griptree for branch '${branch}' not found.`));
    process.exit(1);
  }

  const { path: griptreePath, config } = found;

  if (config.locked) {
    console.log(chalk.yellow(`Griptree for branch '${branch}' is already locked.`));
    return;
  }

  config.locked = true;
  await writeGriptreeConfig(griptreePath, config);
  console.log(chalk.green(`Griptree for branch '${branch}' is now locked.`));
}

/**
 * Unlock a griptree
 */
export async function griptreeUnlock(branch: string): Promise<void> {
  const { rootDir } = await loadManifest();

  const found = await findGriptreeByBranch(rootDir, branch);
  if (!found) {
    console.error(chalk.red(`Griptree for branch '${branch}' not found.`));
    process.exit(1);
  }

  const { path: griptreePath, config } = found;

  if (!config.locked) {
    console.log(chalk.yellow(`Griptree for branch '${branch}' is not locked.`));
    return;
  }

  config.locked = false;
  await writeGriptreeConfig(griptreePath, config);
  console.log(chalk.green(`Griptree for branch '${branch}' is now unlocked.`));
}
