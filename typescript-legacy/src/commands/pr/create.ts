import chalk from 'chalk';
import ora from 'ora';
import inquirer from 'inquirer';
import { loadManifest, getAllRepoInfo, loadState, saveState, getManifestRepoInfo } from '../../lib/manifest.js';
import {
  pathExists,
  getCurrentBranch,
  hasCommitsAhead,
  pushBranch,
  remoteBranchExists,
  isGitRepo,
} from '../../lib/git.js';
import { getPlatformAdapter } from '../../lib/platform/index.js';
import { generateManifestPRBody, getLinkedPRInfo } from '../../lib/linker.js';
import type { RepoInfo, PRCreateOptions, LinkedPR } from '../../types.js';

interface CreateOptions {
  title?: string;
  body?: string;
  draft?: boolean;
  base?: string;
  push?: boolean;
  noInput?: boolean;
}

/**
 * Create linked PRs across all repositories with changes
 */
export async function createPR(options: CreateOptions = {}): Promise<void> {
  const { manifest, rootDir } = await loadManifest();
  const repos = getAllRepoInfo(manifest, rootDir);

  // Check which repos are cloned
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

  // Get current branch and check for changes in each repo
  const repoStatus = await Promise.all(
    clonedRepos.map(async (repo) => {
      const branch = await getCurrentBranch(repo.absolutePath);
      const hasChanges = await hasCommitsAhead(repo.absolutePath, repo.default_branch);
      const needsPush = hasChanges && !(await remoteBranchExists(repo.absolutePath, branch));
      return { repo, branch, hasChanges, needsPush };
    })
  );

  // Check manifest for changes too
  const manifestInfo = getManifestRepoInfo(manifest, rootDir);
  let manifestBranch: string | null = null;
  let manifestHasChanges = false;
  let manifestNeedsPush = false;
  if (manifestInfo && await isGitRepo(manifestInfo.absolutePath)) {
    manifestBranch = await getCurrentBranch(manifestInfo.absolutePath);
    manifestHasChanges = await hasCommitsAhead(manifestInfo.absolutePath, manifestInfo.default_branch);
    manifestNeedsPush = manifestHasChanges && !(await remoteBranchExists(manifestInfo.absolutePath, manifestBranch));
  }

  // Filter to repos with changes
  const withChanges = repoStatus.filter((r) => r.hasChanges);

  if (withChanges.length === 0 && !manifestHasChanges) {
    console.log(chalk.yellow('No repositories have commits ahead of their default branch.'));
    console.log(chalk.dim('Make some commits first, then run this command again.'));
    return;
  }

  // Only check branch consistency for repos WITH CHANGES (not all repos)
  const branchesWithChanges = withChanges.map((r) => r.branch);
  if (manifestHasChanges && manifestBranch) {
    branchesWithChanges.push(manifestBranch);
  }
  const uniqueBranches = [...new Set(branchesWithChanges)];

  if (uniqueBranches.length > 1) {
    console.log(chalk.yellow('Repositories with changes are on different branches:'));
    for (const { repo, branch } of withChanges) {
      console.log(`  ${repo.name}: ${chalk.cyan(branch)}`);
    }
    if (manifestHasChanges && manifestInfo && manifestBranch) {
      console.log(`  ${manifestInfo.name}: ${chalk.cyan(manifestBranch)}`);
    }
    console.log('');
    console.log(chalk.dim('Use `gitgrip checkout <branch>` to sync branches first.'));
    return;
  }

  const branchName = uniqueBranches[0];

  // Check it's not the default branch
  const onDefaultBranch = withChanges.some((r) => r.repo.default_branch === branchName);
  if (onDefaultBranch) {
    console.log(chalk.yellow(`You're on the default branch (${branchName}).`));
    console.log(chalk.dim('Create a feature branch first with `gitgrip branch <name>`.'));
    return;
  }

  console.log(chalk.blue(`Creating PRs for branch: ${chalk.cyan(branchName)}\n`));

  const totalChanges = withChanges.length + (manifestHasChanges ? 1 : 0);
  console.log(`Found changes in ${totalChanges} repos:`);
  for (const { repo } of withChanges) {
    const platformLabel = repo.platformType !== 'github' ? ` (${repo.platformType})` : '';
    console.log(`  ${chalk.green('•')} ${repo.name}${chalk.dim(platformLabel)}`);
  }
  if (manifestHasChanges && manifestInfo) {
    const platformLabel = manifestInfo.platformType !== 'github' ? ` (${manifestInfo.platformType})` : '';
    console.log(`  ${chalk.green('•')} ${manifestInfo.name}${chalk.dim(platformLabel)}`);
  }
  console.log('');

  // Check if any need to be pushed first (including manifest)
  const needsPush = withChanges.filter((r) => r.needsPush);
  const allNeedsPush: { repo: RepoInfo; needsPush: boolean }[] = [...needsPush];
  if (manifestNeedsPush && manifestInfo) {
    allNeedsPush.push({ repo: manifestInfo, needsPush: true });
  }

  if (allNeedsPush.length > 0) {
    if (options.push) {
      console.log(chalk.dim('Pushing branches to remote...\n'));
      for (const { repo } of allNeedsPush) {
        const spinner = ora(`Pushing ${repo.name}...`).start();
        try {
          await pushBranch(repo.absolutePath, branchName, 'origin', true);
          spinner.succeed(`${repo.name}: pushed`);
        } catch (error) {
          spinner.fail(`${repo.name}: ${error instanceof Error ? error.message : error}`);
          console.log(chalk.red('\nFailed to push. Fix the error and try again.'));
          return;
        }
      }
      console.log('');
    } else {
      console.log(chalk.yellow('Some branches need to be pushed to remote first:'));
      for (const { repo } of allNeedsPush) {
        console.log(`  ${repo.name}`);
      }
      console.log('');
      console.log(chalk.dim('Run with --push flag to push automatically, or push manually.'));
      return;
    }
  }

  // Determine if we can prompt interactively
  const isInteractive = process.stdin.isTTY && process.stdout.isTTY && !options.noInput;

  // Get PR title if not provided
  let title: string = options.title ?? '';
  if (!title) {
    if (isInteractive) {
      const answers = await inquirer.prompt([
        {
          type: 'input',
          name: 'title',
          message: 'PR title:',
          default: branchName.replace(/[-_]/g, ' ').replace(/^feature\//, ''),
          validate: (input: string) => input.length > 0 || 'Title is required',
        },
      ]);
      title = answers.title as string;
    } else {
      // Non-interactive: use branch name as title
      title = branchName.replace(/[-_]/g, ' ').replace(/^(feat|fix|chore)\//, '');
      console.log(chalk.dim(`Using title from branch: "${title}"`));
    }
  }

  // Get PR body if not provided
  let body = options.body ?? '';
  if (!body && isInteractive) {
    const answers = await inquirer.prompt([
      {
        type: 'editor',
        name: 'body',
        message: 'PR description (optional):',
        default: '',
      },
    ]);
    body = answers.body.trim();
  }

  // Create PRs
  const spinner = ora('Creating pull requests...').start();

  try {
    const reposForPR = withChanges.map((r) => r.repo);
    const prOptions: PRCreateOptions = {
      title,
      body,
      draft: options.draft,
      base: options.base,
    };

    // Create PRs in each repo using their respective platforms
    const linkedPRs: LinkedPR[] = [];

    for (const repo of reposForPR) {
      const platform = getPlatformAdapter(repo.platformType, repo.platform);

      // Check if PR already exists
      const existing = await platform.findPRByBranch(repo.owner, repo.repo, branchName);
      if (existing) {
        const info = await getLinkedPRInfo(repo, existing.number);
        linkedPRs.push(info);
        continue;
      }

      // Create PR
      const pr = await platform.createPullRequest(
        repo.owner,
        repo.repo,
        branchName,
        prOptions.base ?? repo.default_branch,
        prOptions.title,
        prOptions.body ?? '',
        prOptions.draft
      );

      const info = await getLinkedPRInfo(repo, pr.number);
      linkedPRs.push(info);
    }

    // Create manifest PR if manifest has changes
    let manifestPR: LinkedPR | null = null;
    if (manifestHasChanges && manifestInfo) {
      try {
        const manifestPlatform = getPlatformAdapter(manifestInfo.platformType, manifestInfo.platform);

        // Generate manifest PR body with linked PR table
        const manifestBody = generateManifestPRBody(title, linkedPRs, body);
        const manifestPRResult = await manifestPlatform.createPullRequest(
          manifestInfo.owner,
          manifestInfo.repo,
          branchName,
          manifestInfo.default_branch,
          title,
          manifestBody,
          options.draft
        );
        manifestPR = {
          repoName: manifestInfo.name,
          owner: manifestInfo.owner,
          repo: manifestInfo.repo,
          number: manifestPRResult.number,
          url: manifestPRResult.url,
          state: 'open',
          approved: false,
          checksPass: true,
          mergeable: true,
          platformType: manifestInfo.platformType,
        };
      } catch (error) {
        // Don't fail the whole operation if manifest PR fails
        console.log(chalk.yellow(`\nWarning: Could not create manifest PR: ${error instanceof Error ? error.message : error}`));
      }
    }

    spinner.succeed('Pull requests created!\n');

    // Display results
    console.log(chalk.green('Created PRs:'));
    for (const pr of linkedPRs) {
      const platformLabel = pr.platformType && pr.platformType !== 'github' ? ` (${pr.platformType})` : '';
      console.log(`  ${pr.repoName}${chalk.dim(platformLabel)}: ${chalk.cyan(pr.url)}`);
    }
    if (manifestPR) {
      const platformLabel = manifestPR.platformType && manifestPR.platformType !== 'github' ? ` (${manifestPR.platformType})` : '';
      console.log(`  ${manifestPR.repoName}${chalk.dim(platformLabel)}: ${chalk.cyan(manifestPR.url)}`);
    }

    // Generate a summary for the user
    console.log('');
    console.log(chalk.dim('To view PR status: gitgrip pr status'));
    console.log(chalk.dim('To merge all PRs:  gitgrip pr merge'));

    // Save state
    const state = await loadState(rootDir);
    // We don't have a manifest PR number in simple mode, use branch name as key
    state.branchToPR[branchName] = manifestPR?.number ?? -1;
    await saveState(rootDir, state);
  } catch (error) {
    spinner.fail('Failed to create PRs');
    console.error(chalk.red(error instanceof Error ? error.message : String(error)));
  }
}
