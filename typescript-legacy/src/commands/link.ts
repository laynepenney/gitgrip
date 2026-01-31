import chalk from 'chalk';
import { loadManifest, getManifestsDir } from '../lib/manifest.js';
import { processAllLinks, getAllLinkStatus, cleanOrphanedLinks } from '../lib/files.js';
import type { LinkStatus } from '../types.js';

export interface LinkOptions {
  status?: boolean;
  clean?: boolean;
  force?: boolean;
  dryRun?: boolean;
}

/**
 * Format a link status for display
 */
function formatLinkStatus(link: LinkStatus): string {
  const typeLabel = link.type === 'copyfile' ? 'copy' : 'link';
  const icon = {
    valid: chalk.green('\u2713'),
    missing: chalk.yellow('!'),
    broken: chalk.red('\u2717'),
    conflict: chalk.red('?'),
  }[link.status];

  const statusColor = {
    valid: chalk.green,
    missing: chalk.yellow,
    broken: chalk.red,
    conflict: chalk.red,
  }[link.status];

  const line = `  ${icon} [${typeLabel}] ${chalk.dim(link.repoName)}: ${link.dest}`;
  if (link.message) {
    return `${line} ${chalk.dim(`(${link.message})`)}`;
  }
  return line;
}

/**
 * Show status of all links
 */
async function showStatus(): Promise<void> {
  const { manifest, rootDir } = await loadManifest();
  const manifestsDir = getManifestsDir(rootDir);
  const statuses = await getAllLinkStatus(manifest, rootDir, manifestsDir);

  if (statuses.length === 0) {
    console.log(chalk.dim('No copyfile or linkfile entries defined in manifest'));
    return;
  }

  console.log(chalk.blue('Link Status\n'));

  // Group by status
  const byStatus: Record<string, LinkStatus[]> = {
    valid: [],
    missing: [],
    broken: [],
    conflict: [],
  };

  for (const status of statuses) {
    byStatus[status.status].push(status);
  }

  // Show each group
  if (byStatus.valid.length > 0) {
    console.log(chalk.green(`Valid (${byStatus.valid.length}):`));
    for (const link of byStatus.valid) {
      console.log(formatLinkStatus(link));
    }
    console.log('');
  }

  if (byStatus.missing.length > 0) {
    console.log(chalk.yellow(`Missing (${byStatus.missing.length}):`));
    for (const link of byStatus.missing) {
      console.log(formatLinkStatus(link));
    }
    console.log('');
  }

  if (byStatus.broken.length > 0) {
    console.log(chalk.red(`Broken (${byStatus.broken.length}):`));
    for (const link of byStatus.broken) {
      console.log(formatLinkStatus(link));
    }
    console.log('');
  }

  if (byStatus.conflict.length > 0) {
    console.log(chalk.red(`Conflicts (${byStatus.conflict.length}):`));
    for (const link of byStatus.conflict) {
      console.log(formatLinkStatus(link));
    }
    console.log('');
  }

  // Summary
  const total = statuses.length;
  const valid = byStatus.valid.length;
  const issues = total - valid;

  if (issues === 0) {
    console.log(chalk.green(`All ${total} links are valid.`));
  } else {
    console.log(chalk.yellow(`${valid}/${total} links valid, ${issues} need attention.`));
    console.log(chalk.dim(`Run 'cr link' to create missing links, or 'cr link --force' to fix conflicts.`));
  }
}

/**
 * Clean orphaned links
 */
async function cleanLinks(options: { dryRun?: boolean }): Promise<void> {
  const { manifest, rootDir } = await loadManifest();

  console.log(chalk.blue('Cleaning orphaned links...\n'));

  const results = await cleanOrphanedLinks(manifest, rootDir, { dryRun: options.dryRun });

  if (results.length === 0) {
    console.log(chalk.dim('No orphaned links found.'));
    return;
  }

  for (const result of results) {
    if (result.removed) {
      console.log(chalk.green(`  \u2713 Removed: ${result.path}`));
    } else if (result.message?.startsWith('Would remove')) {
      console.log(chalk.yellow(`  ! ${result.message}`));
    } else {
      console.log(chalk.red(`  \u2717 Failed: ${result.path} - ${result.message}`));
    }
  }

  console.log('');
  const removed = results.filter((r) => r.removed).length;
  const wouldRemove = results.filter((r) => r.message?.startsWith('Would remove')).length;

  if (options.dryRun) {
    console.log(chalk.dim(`Would remove ${wouldRemove} orphaned link(s). Run without --dry-run to execute.`));
  } else {
    console.log(chalk.green(`Removed ${removed} orphaned link(s).`));
  }
}

/**
 * Create/update all links
 */
async function createLinks(options: { force?: boolean; dryRun?: boolean }): Promise<void> {
  const { manifest, rootDir } = await loadManifest();
  const manifestsDir = getManifestsDir(rootDir);

  console.log(chalk.blue(`${options.dryRun ? 'Previewing' : 'Processing'} links...\n`));

  const results = await processAllLinks(manifest, rootDir, {
    force: options.force,
    dryRun: options.dryRun,
  }, manifestsDir);

  let totalCopied = 0;
  let totalLinked = 0;
  let totalFailed = 0;

  for (const result of results) {
    const hasOperations = result.copyfiles.length > 0 || result.linkfiles.length > 0;
    if (!hasOperations) continue;

    console.log(chalk.bold(result.repoName));

    for (const copy of result.copyfiles) {
      if (copy.success) {
        totalCopied++;
        if (options.dryRun) {
          console.log(chalk.dim(`  ${copy.message}`));
        } else {
          console.log(chalk.green(`  \u2713 [copy] ${copy.dest}`));
        }
      } else {
        totalFailed++;
        console.log(chalk.yellow(`  ! [copy] ${copy.dest}: ${copy.message}`));
      }
    }

    for (const link of result.linkfiles) {
      if (link.success) {
        totalLinked++;
        if (options.dryRun) {
          console.log(chalk.dim(`  ${link.message}`));
        } else {
          console.log(chalk.green(`  \u2713 [link] ${link.dest}`));
        }
      } else {
        totalFailed++;
        console.log(chalk.yellow(`  ! [link] ${link.dest}: ${link.message}`));
      }
    }

    console.log('');
  }

  // Summary
  const total = totalCopied + totalLinked;
  if (total === 0 && totalFailed === 0) {
    console.log(chalk.dim('No copyfile or linkfile entries defined in manifest.'));
  } else if (options.dryRun) {
    console.log(chalk.dim(`Would create ${total} link(s). ${totalFailed > 0 ? `${totalFailed} would fail.` : ''}`));
    console.log(chalk.dim(`Run without --dry-run to execute.`));
  } else {
    if (totalFailed === 0) {
      console.log(chalk.green(`Created ${totalCopied} copy file(s), ${totalLinked} symlink(s).`));
    } else {
      console.log(chalk.yellow(`Created ${totalCopied} copy file(s), ${totalLinked} symlink(s). ${totalFailed} failed.`));
    }
  }
}

/**
 * Main link command handler
 */
export async function link(options: LinkOptions = {}): Promise<void> {
  if (options.status) {
    await showStatus();
  } else if (options.clean) {
    await cleanLinks({ dryRun: options.dryRun });
  } else {
    await createLinks({ force: options.force, dryRun: options.dryRun });
  }
}
