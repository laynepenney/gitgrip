import { mkdir } from 'fs/promises';
import { resolve } from 'path';
import chalk from 'chalk';
import ora from 'ora';
import {
  loadManifest,
  getAllRepoInfo,
  getCodiRepoDir,
  getManifestsDir,
  findLegacyManifestPath,
} from '../lib/manifest.js';
import { cloneRepo, pathExists } from '../lib/git.js';

/**
 * Initialize a new codi-repo workspace (AOSP-style)
 *
 * This command:
 * 1. Creates .codi-repo/ directory
 * 2. Clones the manifest repository into .codi-repo/manifests/
 * 3. Reads manifest.yaml from the cloned repo
 * 4. Clones all repositories defined in the manifest
 */
export async function init(manifestUrl: string): Promise<void> {
  const cwd = process.cwd();
  const codiRepoDir = getCodiRepoDir(cwd);
  const manifestsDir = getManifestsDir(cwd);

  // Check if already initialized
  if (await pathExists(codiRepoDir)) {
    console.log(chalk.yellow('Workspace already initialized.'));
    console.log(chalk.dim('Run `codi-repo sync` to update, or delete .codi-repo/ to reinitialize.'));
    return;
  }

  // Check for legacy format
  const legacyManifest = await findLegacyManifestPath(cwd);
  if (legacyManifest) {
    console.log(chalk.yellow('Found legacy codi-repos.yaml format.'));
    console.log(chalk.dim('Run `codi-repo migrate` to convert to the new .codi-repo/ structure.'));
    return;
  }

  // Create .codi-repo/ directory
  const spinner = ora('Creating workspace...').start();
  try {
    await mkdir(codiRepoDir, { recursive: true });
    spinner.succeed('Created .codi-repo/');
  } catch (error) {
    spinner.fail('Failed to create .codi-repo/');
    throw error;
  }

  // Clone manifest repository into .codi-repo/manifests/
  const cloneSpinner = ora(`Cloning manifest from ${manifestUrl}...`).start();
  try {
    await cloneRepo(manifestUrl, manifestsDir);
    cloneSpinner.succeed('Cloned manifest repository');
  } catch (error) {
    cloneSpinner.fail('Failed to clone manifest repository');
    throw error;
  }

  // Load the manifest
  let manifest;
  let rootDir;
  try {
    const result = await loadManifest();
    manifest = result.manifest;
    rootDir = result.rootDir;
    console.log(chalk.green(`Loaded manifest with ${Object.keys(manifest.repos).length} repositories`));
  } catch (error) {
    console.error(chalk.red('Failed to load manifest.yaml from cloned repository.'));
    console.error(chalk.dim('Ensure the manifest repository contains a manifest.yaml file.'));
    throw error;
  }

  // Clone all repositories defined in manifest
  const repos = getAllRepoInfo(manifest, rootDir);
  console.log(chalk.blue(`\nCloning ${repos.length} repositories...\n`));

  for (const repo of repos) {
    const exists = await pathExists(repo.absolutePath);

    if (exists) {
      console.log(chalk.dim(`  ${repo.name}: already exists at ${repo.path}`));
      continue;
    }

    const repoSpinner = ora(`Cloning ${repo.name}...`).start();
    try {
      await cloneRepo(repo.url, repo.absolutePath, repo.default_branch);
      repoSpinner.succeed(`Cloned ${repo.name} to ${repo.path}`);
    } catch (error) {
      repoSpinner.fail(`Failed to clone ${repo.name}`);
      console.error(chalk.red(`  Error: ${error instanceof Error ? error.message : error}`));
    }
  }

  console.log('');
  console.log(chalk.green('Workspace initialized successfully!'));
  console.log(chalk.dim('Run `codi-repo status` to see the status of all repositories.'));
}
