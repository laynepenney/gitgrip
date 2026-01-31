import chalk from 'chalk';
import { loadManifest, getAllRepoInfo, getManifestRepoInfo } from '../lib/manifest.js';
import { pathExists, getGitInstance, isGitRepo } from '../lib/git.js';
import type { RepoInfo } from '../types.js';

interface DiffOptions {
  staged?: boolean;
  stat?: boolean;
  nameOnly?: boolean;
}

/**
 * Get diff output for a repo
 */
async function getRepoDiff(repoPath: string, options: DiffOptions): Promise<string> {
  const git = getGitInstance(repoPath);
  const args: string[] = [];

  if (options.staged) {
    args.push('--staged');
  }

  if (options.stat) {
    args.push('--stat');
  }

  if (options.nameOnly) {
    args.push('--name-only');
  }

  const result = await git.diff(args);
  return result;
}

/**
 * Check if repo has any changes (staged or unstaged)
 */
async function hasChanges(repoPath: string, staged: boolean): Promise<boolean> {
  const git = getGitInstance(repoPath);
  const status = await git.status();

  if (staged) {
    return status.staged.length > 0;
  }

  return status.modified.length > 0 || status.not_added.length > 0 || status.deleted.length > 0;
}

/**
 * Show diff across all repositories
 */
export async function diff(options: DiffOptions = {}): Promise<void> {
  const { manifest, rootDir } = await loadManifest();
  let repos: RepoInfo[] = getAllRepoInfo(manifest, rootDir);

  // Include manifest repo if it exists
  const manifestInfo = getManifestRepoInfo(manifest, rootDir);
  if (manifestInfo && await isGitRepo(manifestInfo.absolutePath)) {
    repos = [...repos, manifestInfo];
  }

  let hasAnyChanges = false;
  const outputs: { repo: RepoInfo; diff: string }[] = [];

  for (const repo of repos) {
    const exists = await pathExists(repo.absolutePath);

    if (!exists) {
      continue;
    }

    // Check if there are changes to show
    const repoHasChanges = await hasChanges(repo.absolutePath, options.staged ?? false);

    if (!repoHasChanges) {
      continue;
    }

    hasAnyChanges = true;

    try {
      const diffOutput = await getRepoDiff(repo.absolutePath, options);
      if (diffOutput.trim()) {
        outputs.push({ repo, diff: diffOutput });
      }
    } catch (error) {
      console.error(chalk.red(`${repo.name}: ${error instanceof Error ? error.message : String(error)}`));
    }
  }

  if (!hasAnyChanges) {
    const changeType = options.staged ? 'staged changes' : 'changes';
    console.log(chalk.yellow(`No ${changeType} in any repository.`));
    return;
  }

  // Output diffs with repo headers
  for (let i = 0; i < outputs.length; i++) {
    const { repo, diff: diffOutput } = outputs[i];

    // Print header
    console.log(chalk.blue.bold(`\n${'═'.repeat(60)}`));
    console.log(chalk.blue.bold(`  ${repo.name}`));
    console.log(chalk.blue.bold(`${'═'.repeat(60)}\n`));

    // Print diff
    // Color the diff output
    const lines = diffOutput.split('\n');
    for (const line of lines) {
      if (line.startsWith('+') && !line.startsWith('+++')) {
        console.log(chalk.green(line));
      } else if (line.startsWith('-') && !line.startsWith('---')) {
        console.log(chalk.red(line));
      } else if (line.startsWith('@@')) {
        console.log(chalk.cyan(line));
      } else if (line.startsWith('diff --git') || line.startsWith('index ') || line.startsWith('---') || line.startsWith('+++')) {
        console.log(chalk.dim(line));
      } else {
        console.log(line);
      }
    }

    // Add spacing between repos
    if (i < outputs.length - 1) {
      console.log('');
    }
  }
}
