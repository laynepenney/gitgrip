import chalk from 'chalk';
import ora from 'ora';
import { exec } from 'child_process';
import { promisify } from 'util';
import { loadManifest, getAllRepoInfo, getManifestRepoInfo } from '../lib/manifest.js';
import { pathExists, isGitRepo } from '../lib/git.js';
import type { RepoInfo } from '../types.js';

const execAsync = promisify(exec);

interface ForallOptions {
  command: string;
  repo?: string[];
  includeManifest?: boolean;
  continueOnError?: boolean;
}

interface ForallResult {
  repo: RepoInfo;
  success: boolean;
  stdout?: string;
  stderr?: string;
  error?: string;
}

/**
 * Run a command in each repository directory
 * Similar to AOSP's `repo forall -c "command"`
 */
export async function forall(options: ForallOptions): Promise<void> {
  const { command, continueOnError = false } = options;

  if (!command || command.trim().length === 0) {
    console.log(chalk.red('Error: Command is required. Use -c "command" to specify.'));
    return;
  }

  const { manifest, rootDir } = await loadManifest();
  let repos: RepoInfo[] = getAllRepoInfo(manifest, rootDir);

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
  }

  // Include manifest if flag is set
  if (options.includeManifest) {
    const manifestInfo = getManifestRepoInfo(manifest, rootDir);
    if (manifestInfo && (await isGitRepo(manifestInfo.absolutePath))) {
      repos = [...repos, manifestInfo];
    }
  }

  if (repos.length === 0) {
    console.log(chalk.red('No repositories to run command in.'));
    return;
  }

  // Filter to existing repos only
  const existingRepos: RepoInfo[] = [];
  for (const repo of repos) {
    if (await pathExists(repo.absolutePath)) {
      existingRepos.push(repo);
    }
  }

  if (existingRepos.length === 0) {
    console.log(chalk.red('No cloned repositories found.'));
    return;
  }

  console.log(chalk.blue(`Running command in ${existingRepos.length} repo(s): ${chalk.dim(command)}\n`));

  const results: ForallResult[] = [];
  let hasFailure = false;

  for (const repo of existingRepos) {
    const spinner = ora(`${repo.name}...`).start();

    try {
      const { stdout, stderr } = await execAsync(command, {
        cwd: repo.absolutePath,
        env: {
          ...process.env,
          REPO_NAME: repo.name,
          REPO_PATH: repo.absolutePath,
          REPO_URL: repo.url,
        },
        maxBuffer: 10 * 1024 * 1024, // 10MB buffer
      });

      spinner.succeed(`${repo.name}`);

      // Print output if there is any
      if (stdout.trim()) {
        console.log(chalk.dim(stdout.trim().split('\n').map(line => `  ${line}`).join('\n')));
      }
      if (stderr.trim()) {
        console.log(chalk.yellow(stderr.trim().split('\n').map(line => `  ${line}`).join('\n')));
      }

      results.push({ repo, success: true, stdout, stderr });
    } catch (error) {
      hasFailure = true;
      const err = error as { stdout?: string; stderr?: string; message?: string };
      const errorMsg = err.stderr || err.message || String(error);

      spinner.fail(`${repo.name}`);

      // Print error output
      if (err.stdout?.trim()) {
        console.log(chalk.dim(err.stdout.trim().split('\n').map(line => `  ${line}`).join('\n')));
      }
      if (errorMsg.trim()) {
        console.log(chalk.red(errorMsg.trim().split('\n').map(line => `  ${line}`).join('\n')));
      }

      results.push({ repo, success: false, stdout: err.stdout, stderr: err.stderr, error: errorMsg });

      if (!continueOnError) {
        console.log('');
        console.log(chalk.red(`Stopping due to error. Use --continue-on-error to continue past failures.`));
        break;
      }
    }

    console.log(''); // Blank line between repos
  }

  // Summary
  const succeeded = results.filter((r) => r.success).length;
  const failed = results.filter((r) => !r.success).length;
  const skipped = existingRepos.length - results.length;

  if (failed === 0 && skipped === 0) {
    console.log(chalk.green(`Completed successfully in ${succeeded} repo(s).`));
  } else if (skipped > 0) {
    console.log(chalk.yellow(`Completed in ${succeeded} repo(s). ${skipped} skipped due to earlier error.`));
  } else {
    console.log(chalk.yellow(`Completed in ${succeeded} repo(s). ${failed} failed.`));
  }
}
