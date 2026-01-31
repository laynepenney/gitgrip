import chalk from 'chalk';
import ora from 'ora';
import { resolve } from 'path';
import { loadManifest, getManifestPath, addRepoToManifest, getManifestsDir } from '../lib/manifest.js';
import { parseRepoUrl } from '../lib/platform/index.js';
import { cloneRepo, pathExists, getCurrentBranch, createBranch, branchExists } from '../lib/git.js';

export interface RepoAddOptions {
  path?: string;
  name?: string;
  branch?: string;
  noClone?: boolean;
}

/**
 * Add a repository to the workspace
 *
 * @param url - Git URL (SSH or HTTPS) of the repository to add
 * @param options - Options for adding the repo
 */
export async function repoAdd(url: string, options: RepoAddOptions = {}): Promise<void> {
  // 1. Parse URL to get owner/repo
  const parsed = parseRepoUrl(url);
  if (!parsed) {
    throw new Error(
      `Unable to parse repository URL: ${url}\n` +
      `Supported formats:\n` +
      `  - GitHub: git@github.com:owner/repo.git or https://github.com/owner/repo.git\n` +
      `  - GitLab: git@gitlab.com:owner/repo.git or https://gitlab.com/owner/repo.git\n` +
      `  - Azure DevOps: git@ssh.dev.azure.com:v3/org/project/repo or https://dev.azure.com/org/project/_git/repo`
    );
  }

  // 2. Determine repo name and path
  const repoName = options.name ?? parsed.repo;
  const repoPath = options.path ?? `./${repoName}`;
  const defaultBranch = options.branch ?? 'main';

  // 3. Load manifest
  const { manifest, rootDir } = await loadManifest();
  const manifestPath = getManifestPath(rootDir);
  const manifestsDir = getManifestsDir(rootDir);

  // 4. Check if repo already exists
  if (manifest.repos[repoName]) {
    throw new Error(`Repository '${repoName}' already exists in manifest`);
  }

  // Check if path is already used by another repo
  const absoluteNewPath = resolve(rootDir, repoPath);
  for (const [existingName, existingRepo] of Object.entries(manifest.repos)) {
    const existingAbsPath = resolve(rootDir, existingRepo.path);
    if (existingAbsPath === absoluteNewPath) {
      throw new Error(`Path '${repoPath}' is already used by repository '${existingName}'`);
    }
  }

  // 5. Add to manifest
  const manifestSpinner = ora('Adding repository to manifest...').start();
  try {
    await addRepoToManifest(manifestPath, repoName, {
      url,
      path: repoPath,
      default_branch: defaultBranch,
    });
    manifestSpinner.succeed(`Added '${repoName}' to manifest`);
  } catch (error) {
    manifestSpinner.fail(`Failed to update manifest: ${error instanceof Error ? error.message : String(error)}`);
    throw error;
  }

  // 6. Clone if requested
  if (!options.noClone) {
    const absolutePath = resolve(rootDir, repoPath);

    // Check if directory already exists
    if (await pathExists(absolutePath)) {
      console.log(chalk.yellow(`  Directory '${repoPath}' already exists, skipping clone`));
    } else {
      const cloneSpinner = ora(`Cloning ${url}...`).start();
      try {
        await cloneRepo(url, absolutePath, defaultBranch);
        cloneSpinner.succeed(`Cloned to ${repoPath}`);

        // Sync branch if workspace is on a feature branch
        // Get current branch from manifest repo (represents workspace branch)
        const workspaceBranch = await getCurrentBranch(manifestsDir);
        if (workspaceBranch !== 'main' && workspaceBranch !== defaultBranch) {
          // Check if the branch exists in the newly cloned repo
          const branchExistsInNew = await branchExists(absolutePath, workspaceBranch);
          if (!branchExistsInNew) {
            const branchSpinner = ora(`Creating branch '${workspaceBranch}' in new repo...`).start();
            try {
              await createBranch(absolutePath, workspaceBranch);
              branchSpinner.succeed(`Created branch '${workspaceBranch}' in ${repoName}`);
            } catch (branchError) {
              branchSpinner.warn(`Could not create branch '${workspaceBranch}' in ${repoName}`);
            }
          }
        }
      } catch (error) {
        cloneSpinner.fail(`Failed to clone: ${error instanceof Error ? error.message : String(error)}`);
        console.log(chalk.yellow(`  Repository was added to manifest but not cloned. Run 'gr sync' to retry.`));
      }
    }
  } else {
    console.log(chalk.dim(`  Skipped cloning (--no-clone). Run 'gr sync' to clone later.`));
  }

  // Summary
  console.log('');
  console.log(chalk.green(`Successfully added '${repoName}' to workspace:`));
  console.log(`  ${chalk.dim('URL:')} ${url}`);
  console.log(`  ${chalk.dim('Path:')} ${repoPath}`);
  console.log(`  ${chalk.dim('Branch:')} ${defaultBranch}`);
  console.log(`  ${chalk.dim('Platform:')} ${parsed.platform}`);
  console.log('');
  console.log(chalk.dim(`Remember to commit the manifest changes with 'gr commit -m "Add ${repoName} to workspace"'`));
}
