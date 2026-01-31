import chalk from 'chalk';
import { loadManifest, getAllRepoInfo, getManifestsDir, getManifestRepoInfo } from '../lib/manifest.js';
import { getAllRepoStatus, getRepoStatus, isGitRepo } from '../lib/git.js';
import { getAllLinkStatus } from '../lib/files.js';
import { getTimingContext } from '../lib/timing.js';
import type { RepoStatus } from '../types.js';

interface StatusOptions {
  json?: boolean;
}

/**
 * Format a single repo status line
 */
function formatRepoStatus(status: RepoStatus): string {
  if (!status.exists) {
    return `${chalk.yellow(status.name)}: ${chalk.dim('not cloned')}`;
  }

  const parts: string[] = [];

  // Branch name
  parts.push(chalk.cyan(status.branch));

  // Clean/dirty indicator
  if (status.clean) {
    parts.push(chalk.green('clean'));
  } else {
    const changes: string[] = [];
    if (status.staged > 0) {
      changes.push(chalk.green(`+${status.staged} staged`));
    }
    if (status.modified > 0) {
      changes.push(chalk.yellow(`~${status.modified} modified`));
    }
    if (status.untracked > 0) {
      changes.push(chalk.dim(`?${status.untracked} untracked`));
    }
    parts.push(changes.join(', '));
  }

  // Ahead/behind
  if (status.ahead > 0 || status.behind > 0) {
    const sync: string[] = [];
    if (status.ahead > 0) {
      sync.push(chalk.green(`↑${status.ahead}`));
    }
    if (status.behind > 0) {
      sync.push(chalk.red(`↓${status.behind}`));
    }
    parts.push(sync.join(' '));
  }

  return `${chalk.bold(status.name)}: ${parts.join(' | ')}`;
}

/**
 * Show status of all repositories
 */
export async function status(options: StatusOptions = {}): Promise<void> {
  const timing = getTimingContext();

  timing?.startPhase('load manifest');
  const { manifest, rootDir } = await loadManifest();
  const repos = getAllRepoInfo(manifest, rootDir);
  timing?.endPhase('load manifest');

  timing?.startPhase('get repo status');
  const statuses = await getAllRepoStatus(repos);
  timing?.endPhase('get repo status');

  // Get manifest status
  timing?.startPhase('get manifest status');
  const manifestInfo = getManifestRepoInfo(manifest, rootDir);
  let manifestStatus: RepoStatus | null = null;
  if (manifestInfo) {
    const isRepo = await isGitRepo(manifestInfo.absolutePath);
    if (isRepo) {
      manifestStatus = await getRepoStatus(manifestInfo);
    }
  }
  timing?.endPhase('get manifest status');

  if (options.json) {
    const output = {
      repos: statuses,
      manifest: manifestStatus,
    };
    console.log(JSON.stringify(output, null, 2));
    return;
  }

  console.log(chalk.blue('Repository Status\n'));

  // Find longest repo name for alignment
  const maxNameLength = Math.max(...statuses.map((s) => s.name.length));

  for (const status of statuses) {
    const paddedName = status.name.padEnd(maxNameLength);

    if (!status.exists) {
      console.log(`  ${chalk.yellow(paddedName)}  ${chalk.dim('not cloned')}`);
      continue;
    }

    const parts: string[] = [];

    // Branch with fixed width
    const branchDisplay = status.branch.length > 20
      ? status.branch.slice(0, 17) + '...'
      : status.branch.padEnd(20);
    parts.push(chalk.cyan(branchDisplay));

    // Status indicators
    if (status.clean) {
      parts.push(chalk.green('✓'));
    } else {
      const indicators: string[] = [];
      if (status.staged > 0) indicators.push(chalk.green(`+${status.staged}`));
      if (status.modified > 0) indicators.push(chalk.yellow(`~${status.modified}`));
      if (status.untracked > 0) indicators.push(chalk.dim(`?${status.untracked}`));
      parts.push(indicators.join(' '));
    }

    // Ahead/behind
    if (status.ahead > 0 || status.behind > 0) {
      const sync: string[] = [];
      if (status.ahead > 0) sync.push(chalk.green(`↑${status.ahead}`));
      if (status.behind > 0) sync.push(chalk.red(`↓${status.behind}`));
      parts.push(sync.join(' '));
    }

    console.log(`  ${chalk.bold(paddedName)}  ${parts.join('  ')}`);
  }

  // Summary
  console.log('');
  const cloned = statuses.filter((s) => s.exists).length;
  const dirty = statuses.filter((s) => s.exists && !s.clean).length;
  const notCloned = statuses.filter((s) => !s.exists).length;

  const summaryParts: string[] = [];
  summaryParts.push(`${cloned}/${repos.length} cloned`);
  if (dirty > 0) {
    summaryParts.push(chalk.yellow(`${dirty} with changes`));
  }
  if (notCloned > 0) {
    summaryParts.push(chalk.dim(`${notCloned} not cloned`));
  }

  console.log(chalk.dim(`  ${summaryParts.join(' | ')}`));

  // Check if all on same branch
  const branches = new Set(statuses.filter((s) => s.exists).map((s) => s.branch));
  if (branches.size > 1) {
    console.log('');
    console.log(chalk.yellow('  \u26a0 Repositories are on different branches'));
  }

  // Show manifest status (already fetched above)
  if (manifestStatus) {
    console.log('');
    console.log(chalk.blue('Manifest'));

    const parts: string[] = [];

    // Branch
    const branchDisplay = manifestStatus.branch.length > 20
      ? manifestStatus.branch.slice(0, 17) + '...'
      : manifestStatus.branch;
    parts.push(`branch: ${chalk.cyan(branchDisplay)}`);

    // Status indicators
    if (manifestStatus.clean) {
      parts.push(chalk.green('✓'));
    } else {
      const indicators: string[] = [];
      if (manifestStatus.staged > 0) indicators.push(chalk.green(`+${manifestStatus.staged}`));
      if (manifestStatus.modified > 0) indicators.push(chalk.yellow(`~${manifestStatus.modified}`));
      if (manifestStatus.untracked > 0) indicators.push(chalk.dim(`?${manifestStatus.untracked}`));
      parts.push(indicators.join(' '));
    }

    // Ahead/behind
    if (manifestStatus.ahead > 0 || manifestStatus.behind > 0) {
      const sync: string[] = [];
      if (manifestStatus.ahead > 0) sync.push(chalk.green(`↑${manifestStatus.ahead}`));
      if (manifestStatus.behind > 0) sync.push(chalk.red(`↓${manifestStatus.behind}`));
      parts.push(sync.join(' '));
    }

    console.log(chalk.dim(`  ${parts.join('  ')}`));
  }

  // Show link status summary
  timing?.startPhase('get link status');
  const manifestsDir = getManifestsDir(rootDir);
  const linkStatuses = await getAllLinkStatus(manifest, rootDir, manifestsDir);
  timing?.endPhase('get link status');

  if (linkStatuses.length > 0) {
    const validLinks = linkStatuses.filter((l) => l.status === 'valid').length;
    const brokenLinks = linkStatuses.filter((l) => l.status === 'broken').length;
    const missingLinks = linkStatuses.filter((l) => l.status === 'missing').length;
    const conflictLinks = linkStatuses.filter((l) => l.status === 'conflict').length;

    console.log('');
    console.log(chalk.blue('Links'));

    const linkParts: string[] = [];
    linkParts.push(`${validLinks}/${linkStatuses.length} valid`);
    if (brokenLinks > 0) {
      linkParts.push(chalk.red(`${brokenLinks} broken`));
    }
    if (missingLinks > 0) {
      linkParts.push(chalk.yellow(`${missingLinks} missing`));
    }
    if (conflictLinks > 0) {
      linkParts.push(chalk.red(`${conflictLinks} conflicts`));
    }

    console.log(chalk.dim(`  ${linkParts.join(' | ')}`));

    if (brokenLinks + missingLinks + conflictLinks > 0) {
      console.log(chalk.dim(`  Run 'cr link --status' for details`));
    }
  }
}
