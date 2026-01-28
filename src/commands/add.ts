import chalk from 'chalk';
import ora from 'ora';
import { loadManifest, getAllRepoInfo, getManifestRepoInfo } from '../lib/manifest.js';
import { pathExists, getGitInstance, isGitRepo } from '../lib/git.js';
import type { RepoInfo } from '../types.js';

interface AddOptions {
  all?: boolean;
}

interface AddResult {
  repo: RepoInfo;
  success: boolean;
  staged: boolean;
  files?: number;
  error?: string;
}

/**
 * Get count of unstaged changes in a repo
 */
async function getUnstagedCount(repoPath: string): Promise<number> {
  const git = getGitInstance(repoPath);
  const status = await git.status();
  return status.modified.length + status.not_added.length + status.deleted.length;
}

/**
 * Stage files in a repo
 */
async function stageFiles(repoPath: string, files: string[]): Promise<void> {
  const git = getGitInstance(repoPath);
  if (files.length === 1 && (files[0] === '.' || files[0] === '-A')) {
    await git.add('-A');
  } else {
    await git.add(files);
  }
}

/**
 * Stage changes across all repositories
 */
export async function add(files: string[], options: AddOptions = {}): Promise<void> {
  // Default to staging all if no files specified (or if -A flag used)
  const filesToAdd = (files.length > 0 && !options.all) ? files : ['.'];

  const { manifest, rootDir } = await loadManifest();
  let repos: RepoInfo[] = getAllRepoInfo(manifest, rootDir);

  // Include manifest repo if it has changes
  const manifestInfo = getManifestRepoInfo(manifest, rootDir);
  if (manifestInfo && await isGitRepo(manifestInfo.absolutePath)) {
    repos = [...repos, manifestInfo];
  }

  const results: AddResult[] = [];
  let hasChanges = false;

  console.log(chalk.blue('Checking repositories for changes to stage...\n'));

  for (const repo of repos) {
    const exists = await pathExists(repo.absolutePath);

    if (!exists) {
      continue;
    }

    // Check if there are unstaged changes
    const unstagedCount = await getUnstagedCount(repo.absolutePath);

    if (unstagedCount === 0) {
      continue;
    }

    hasChanges = true;
    const spinner = ora(`Staging ${repo.name}...`).start();

    try {
      await stageFiles(repo.absolutePath, filesToAdd);
      spinner.succeed(`${repo.name}: staged ${unstagedCount} file(s)`);
      results.push({ repo, success: true, staged: true, files: unstagedCount });
    } catch (error) {
      const errorMsg = error instanceof Error ? error.message : String(error);
      spinner.fail(`${repo.name}: ${errorMsg}`);
      results.push({ repo, success: false, staged: false, error: errorMsg });
    }
  }

  if (!hasChanges) {
    console.log(chalk.yellow('No changes to stage in any repository.'));
    return;
  }

  // Summary
  console.log('');
  const staged = results.filter((r) => r.staged).length;
  const totalFiles = results.reduce((sum, r) => sum + (r.files ?? 0), 0);
  const failed = results.filter((r) => !r.success).length;

  if (failed === 0) {
    console.log(chalk.green(`Staged ${totalFiles} file(s) in ${staged} repository(s).`));
  } else {
    console.log(chalk.yellow(`Staged in ${staged} repository(s). ${failed} failed.`));
  }
}
