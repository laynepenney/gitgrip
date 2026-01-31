import chalk from 'chalk';
import ora from 'ora';
import { loadManifest, getAllRepoInfo, getManifestsDir } from '../lib/manifest.js';
import { pullLatest, fetchRemote, pathExists, getCurrentBranch, getRemoteUrl, setRemoteUrl, setUpstreamBranch, safePullLatest } from '../lib/git.js';
import { processAllLinks } from '../lib/files.js';
import { runHooks } from '../lib/hooks.js';
import { getTimingContext } from '../lib/timing.js';
import type { RepoInfo } from '../types.js';

interface SyncOptions {
  fetch?: boolean;
  all?: boolean;
  noLink?: boolean;
  noHooks?: boolean;
}

/**
 * Sync (pull or fetch) all repositories
 * First updates the manifest repository, then syncs each managed repo
 */
export async function sync(options: SyncOptions = {}): Promise<void> {
  const timing = getTimingContext();

  // Load manifest to get rootDir
  timing?.startPhase('load manifest');
  const { manifest, rootDir } = await loadManifest();
  const manifestsDir = getManifestsDir(rootDir);
  timing?.endPhase('load manifest');

  // 1. Update manifest repository first
  timing?.startPhase('update manifest');
  const manifestSpinner = ora('Updating manifests...').start();
  try {
    // Check if manifest has a URL configured and ensure remote is set
    if (manifest.manifest?.url) {
      const existingRemote = await getRemoteUrl(manifestsDir);
      if (!existingRemote) {
        await setRemoteUrl(manifestsDir, manifest.manifest.url);
        await setUpstreamBranch(manifestsDir);
        manifestSpinner.text = 'Configured manifest remote, updating...';
      }
    }

    const hasRemote = await getRemoteUrl(manifestsDir);
    if (!hasRemote) {
      manifestSpinner.warn('Manifests has no remote configured (add manifest.url to manifest.yaml)');
    } else if (options.fetch) {
      await fetchRemote(manifestsDir);
      manifestSpinner.succeed('Fetched manifest updates');
    } else {
      // Use safePullLatest to handle case where tracking branch was deleted (after PR merge)
      const defaultBranch = manifest.manifest?.default_branch ?? 'main';
      const result = await safePullLatest(manifestsDir, defaultBranch);

      if (result.pulled) {
        if (result.recovered) {
          manifestSpinner.succeed(`Pulled latest manifest (${result.message})`);
        } else {
          manifestSpinner.succeed('Pulled latest manifest');
        }
      } else {
        throw new Error(result.message ?? 'Unknown error');
      }
    }
  } catch (error) {
    const errorMsg = error instanceof Error ? error.message : String(error);
    if (errorMsg.includes('uncommitted changes')) {
      manifestSpinner.warn('Manifests have uncommitted changes, skipping');
    } else {
      manifestSpinner.fail(`Failed to update manifests: ${errorMsg}`);
    }
  }
  timing?.endPhase('update manifest');

  // 2. Reload manifest (may have changed after pull)
  const { manifest: updatedManifest } = await loadManifest();
  const repos = getAllRepoInfo(updatedManifest, rootDir);

  console.log(chalk.blue(`\nSyncing ${repos.length} repositories...\n`));

  timing?.startPhase('sync repos');

  // Sync all repos in parallel for better performance
  const results = await Promise.all(
    repos.map(async (repo): Promise<{ repo: RepoInfo; success: boolean; error?: string; branch?: string }> => {
      const exists = await pathExists(repo.absolutePath);

      if (!exists) {
        console.log(chalk.yellow(`  ${repo.name}: not cloned (run 'gitgrip init <url>')`));
        return { repo, success: false, error: 'not cloned' };
      }

      const spinner = ora(`${options.fetch ? 'Fetching' : 'Pulling'} ${repo.name}...`).start();
      timing?.startPhase(repo.name);

      try {
        const branch = await getCurrentBranch(repo.absolutePath);

        if (options.fetch) {
          await fetchRemote(repo.absolutePath);
          spinner.succeed(`${repo.name} (${chalk.cyan(branch)}): fetched`);
        } else {
          await pullLatest(repo.absolutePath);
          spinner.succeed(`${repo.name} (${chalk.cyan(branch)}): pulled`);
        }

        timing?.endPhase(repo.name);
        return { repo, success: true, branch };
      } catch (error) {
        const errorMsg = error instanceof Error ? error.message : String(error);

        // Check for common errors
        if (errorMsg.includes('uncommitted changes')) {
          spinner.warn(`${repo.name}: has uncommitted changes, skipping`);
          timing?.endPhase(repo.name);
          return { repo, success: false, error: 'uncommitted changes' };
        } else if (errorMsg.includes('diverged')) {
          spinner.warn(`${repo.name}: branch has diverged from remote`);
          timing?.endPhase(repo.name);
          return { repo, success: false, error: 'diverged' };
        } else {
          spinner.fail(`${repo.name}: ${errorMsg}`);
          timing?.endPhase(repo.name);
          return { repo, success: false, error: errorMsg };
        }
      }
    })
  );

  timing?.endPhase('sync repos');

  // Summary
  console.log('');
  const succeeded = results.filter((r) => r.success).length;
  const failed = results.filter((r) => !r.success).length;

  if (failed === 0) {
    console.log(chalk.green(`All ${succeeded} repositories synced successfully.`));
  } else {
    console.log(
      chalk.yellow(`Synced ${succeeded}/${repos.length} repositories. ${failed} had issues.`)
    );
  }

  // Process links unless disabled
  if (!options.noLink) {
    const hasRepoLinks = Object.values(updatedManifest.repos).some(
      (repo) => (repo.copyfile && repo.copyfile.length > 0) || (repo.linkfile && repo.linkfile.length > 0)
    );
    const hasManifestLinks = updatedManifest.manifest && (
      (updatedManifest.manifest.copyfile && updatedManifest.manifest.copyfile.length > 0) ||
      (updatedManifest.manifest.linkfile && updatedManifest.manifest.linkfile.length > 0)
    );

    if (hasRepoLinks || hasManifestLinks) {
      console.log('');
      timing?.startPhase('process links');
      const linkSpinner = ora('Processing links...').start();
      try {
        const linkResults = await processAllLinks(updatedManifest, rootDir, { force: false }, manifestsDir);
        const totalLinks = linkResults.reduce(
          (sum, r) => sum + r.copyfiles.length + r.linkfiles.length,
          0
        );
        const successfulLinks = linkResults.reduce(
          (sum, r) =>
            sum +
            r.copyfiles.filter((c) => c.success).length +
            r.linkfiles.filter((l) => l.success).length,
          0
        );

        if (successfulLinks === totalLinks) {
          linkSpinner.succeed(`Processed ${totalLinks} link(s)`);
        } else {
          linkSpinner.warn(`Processed ${successfulLinks}/${totalLinks} link(s), some failed`);
        }
      } catch (error) {
        linkSpinner.fail(`Failed to process links: ${error instanceof Error ? error.message : String(error)}`);
      }
      timing?.endPhase('process links');
    }
  }

  // Run post-sync hooks unless disabled
  if (!options.noHooks) {
    const postSyncHooks = updatedManifest.workspace?.hooks?.['post-sync'];
    if (postSyncHooks && postSyncHooks.length > 0) {
      console.log('');
      console.log(chalk.blue('Running post-sync hooks...\n'));

      timing?.startPhase('run hooks');
      const hookResults = await runHooks(postSyncHooks, rootDir, updatedManifest.workspace?.env);

      for (const result of hookResults) {
        if (result.success) {
          console.log(chalk.green(`  \u2713 ${result.command}`));
        } else {
          console.log(chalk.red(`  \u2717 ${result.command}`));
          if (result.stderr) {
            console.log(chalk.dim(`    ${result.stderr.trim()}`));
          }
          if (result.error) {
            console.log(chalk.dim(`    Error: ${result.error}`));
          }
        }
      }

      const hooksFailed = hookResults.some((r) => !r.success);
      if (hooksFailed) {
        console.log('');
        console.log(chalk.yellow('Some post-sync hooks failed.'));
      }
      timing?.endPhase('run hooks');
    }
  }
}
