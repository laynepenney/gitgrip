import { mkdir, readFile, writeFile, rename, rm } from 'fs/promises';
import { resolve, dirname } from 'path';
import chalk from 'chalk';
import ora from 'ora';
import inquirer from 'inquirer';
import { simpleGit } from 'simple-git';
import {
  findLegacyManifestPath,
  getNewGitgripDir,
  getManifestsDir,
} from '../lib/manifest.js';
import { pathExists } from '../lib/git.js';

interface MigrateOptions {
  force?: boolean;
  remote?: string;
}

/**
 * Migrate from old codi-repos.yaml format to new .gitgrip/manifests/ structure
 *
 * This command:
 * 1. Finds codi-repos.yaml in current or parent directory
 * 2. Creates .gitgrip/manifests/ as a new git repo
 * 3. Moves codi-repos.yaml to .gitgrip/manifests/manifest.yaml
 * 4. Commits the manifest
 * 5. Optionally pushes to a remote
 */
export async function migrate(options: MigrateOptions = {}): Promise<void> {
  // Find legacy manifest
  const legacyPath = await findLegacyManifestPath();
  if (!legacyPath) {
    console.log(chalk.yellow('No legacy codi-repos.yaml found.'));
    console.log(chalk.dim('This workspace may already be using the new format, or not initialized.'));
    return;
  }

  const workspaceRoot = dirname(legacyPath);
  const gitgripDir = getNewGitgripDir(workspaceRoot);
  const manifestsDir = getManifestsDir(workspaceRoot);

  console.log(chalk.blue('Migration Plan:'));
  console.log(chalk.dim(`  From: ${legacyPath}`));
  console.log(chalk.dim(`  To:   ${manifestsDir}/manifest.yaml`));
  console.log('');

  // Check if .gitgrip already exists
  if (await pathExists(gitgripDir)) {
    if (!options.force) {
      const { proceed } = await inquirer.prompt([
        {
          type: 'confirm',
          name: 'proceed',
          message: '.gitgrip/ already exists. Overwrite?',
          default: false,
        },
      ]);
      if (!proceed) {
        console.log('Migration cancelled.');
        return;
      }
    }
    // Remove existing .gitgrip
    await rm(gitgripDir, { recursive: true, force: true });
  }

  // Ask for confirmation
  if (!options.force) {
    const { confirm } = await inquirer.prompt([
      {
        type: 'confirm',
        name: 'confirm',
        message: 'Proceed with migration?',
        default: true,
      },
    ]);
    if (!confirm) {
      console.log('Migration cancelled.');
      return;
    }
  }

  // Create .gitgrip/manifests/ directory
  const mkdirSpinner = ora('Creating .gitgrip/manifests/...').start();
  try {
    await mkdir(manifestsDir, { recursive: true });
    mkdirSpinner.succeed('Created .gitgrip/manifests/');
  } catch (error) {
    mkdirSpinner.fail('Failed to create directories');
    throw error;
  }

  // Read legacy manifest content
  const legacyContent = await readFile(legacyPath, 'utf-8');

  // Write to new location
  const writeSpinner = ora('Moving manifest...').start();
  try {
    await writeFile(resolve(manifestsDir, 'manifest.yaml'), legacyContent, 'utf-8');
    writeSpinner.succeed('Created manifest.yaml');
  } catch (error) {
    writeSpinner.fail('Failed to write manifest.yaml');
    throw error;
  }

  // Initialize git repo in manifests directory
  const gitSpinner = ora('Initializing git repository...').start();
  try {
    const git = simpleGit(manifestsDir);
    await git.init();
    await git.add('manifest.yaml');
    await git.commit('chore: migrate manifest from codi-repos.yaml');
    gitSpinner.succeed('Initialized git repository with initial commit');
  } catch (error) {
    gitSpinner.fail('Failed to initialize git repository');
    throw error;
  }

  // Optionally add remote and push
  let remoteUrl = options.remote;
  if (!remoteUrl) {
    const { addRemote } = await inquirer.prompt([
      {
        type: 'confirm',
        name: 'addRemote',
        message: 'Would you like to push the manifest to a remote repository?',
        default: false,
      },
    ]);

    if (addRemote) {
      const { url } = await inquirer.prompt([
        {
          type: 'input',
          name: 'url',
          message: 'Enter the remote URL (e.g., git@github.com:user/manifests.git):',
        },
      ]);
      remoteUrl = url;
    }
  }

  if (remoteUrl) {
    const pushSpinner = ora('Pushing to remote...').start();
    try {
      const git = simpleGit(manifestsDir);
      await git.addRemote('origin', remoteUrl);
      await git.push(['-u', 'origin', 'main']);
      pushSpinner.succeed(`Pushed to ${remoteUrl}`);
    } catch (error) {
      pushSpinner.fail('Failed to push to remote');
      console.error(chalk.dim(`Error: ${error instanceof Error ? error.message : error}`));
      console.log(chalk.dim('You can add the remote manually later.'));
    }
  }

  // Remove old manifest file
  const removeSpinner = ora('Removing old codi-repos.yaml...').start();
  try {
    await rm(legacyPath);
    removeSpinner.succeed('Removed old codi-repos.yaml');
  } catch (error) {
    removeSpinner.warn('Could not remove old codi-repos.yaml (you may want to remove it manually)');
  }

  // Remove old .gitgrip entries from .gitignore if present
  const gitignorePath = resolve(workspaceRoot, '.gitignore');
  if (await pathExists(gitignorePath)) {
    try {
      const gitignoreContent = await readFile(gitignorePath, 'utf-8');
      // The workspace is no longer a git repo, but clean up anyway
      console.log(chalk.dim('Note: .gitignore file remains; you may want to remove it if the workspace is no longer a git repo.'));
    } catch {
      // Ignore
    }
  }

  console.log('');
  console.log(chalk.green('Migration complete!'));
  console.log('');
  console.log(chalk.dim('Your workspace is now using the AOSP-style structure:'));
  console.log(chalk.cyan(`  ${workspaceRoot}/`));
  console.log(chalk.cyan('  ├── .gitgrip/'));
  console.log(chalk.cyan('  │   └── manifests/'));
  console.log(chalk.cyan('  │       ├── .git/'));
  console.log(chalk.cyan('  │       └── manifest.yaml'));
  console.log(chalk.cyan('  └── <your repos>/'));
  console.log('');
  console.log(chalk.dim('Run `gr status` to verify everything is working.'));

  if (!remoteUrl) {
    console.log('');
    console.log(chalk.yellow('Tip: Consider pushing your manifest to a remote for team sharing:'));
    console.log(chalk.dim(`  cd ${manifestsDir}`));
    console.log(chalk.dim('  git remote add origin <your-manifest-repo-url>'));
    console.log(chalk.dim('  git push -u origin main'));
  }
}
