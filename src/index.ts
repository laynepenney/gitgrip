#!/usr/bin/env node

import { Command } from 'commander';
import chalk from 'chalk';
import { init } from './commands/init.js';
import { migrate } from './commands/migrate.js';
import { sync } from './commands/sync.js';
import { status } from './commands/status.js';
import { branch, listBranches } from './commands/branch.js';
import { checkout } from './commands/checkout.js';
import { createPR, prStatus, mergePRs } from './commands/pr/index.js';
import { link } from './commands/link.js';
import { run } from './commands/run.js';
import { env } from './commands/env.js';
import { bench } from './commands/bench.js';
import { commit } from './commands/commit.js';
import { push } from './commands/push.js';
import { add } from './commands/add.js';
import { diff } from './commands/diff.js';
import { forall } from './commands/forall.js';
import { TimingContext, formatTimingReport, setTimingContext, getTimingContext } from './lib/timing.js';

const program = new Command();

program
  .name('gitgrip')
  .description('git a grip - Multi-repo workflow tool\n\nShorthand: Use "gr" instead of "gitgrip"')
  .version('0.2.0')
  .option('--timing', 'Show timing breakdown for operations');

// Set up timing hooks
program.hook('preAction', (thisCommand) => {
  const opts = thisCommand.optsWithGlobals();
  if (opts.timing) {
    setTimingContext(new TimingContext(true));
  }
});

program.hook('postAction', () => {
  const ctx = getTimingContext();
  if (ctx && ctx.isEnabled()) {
    console.log('\n' + formatTimingReport(ctx.getReport()));
    setTimingContext(undefined);
  }
});

// Init command - AOSP-style with manifest URL
program
  .command('init <manifest-url>')
  .description('Initialize a gitgrip workspace from a manifest repository')
  .option('-b, --branch <branch>', 'Branch to clone from manifest repository')
  .action(async (manifestUrl, options) => {
    try {
      await init(manifestUrl, { branch: options.branch });
    } catch (error) {
      console.error(chalk.red(error instanceof Error ? error.message : String(error)));
      process.exit(1);
    }
  });

// Migrate command - convert legacy format to new structure
program
  .command('migrate')
  .description('Migrate from legacy format to .gitgrip/manifests/ structure')
  .option('-f, --force', 'Skip confirmation prompts')
  .option('-r, --remote <url>', 'Remote URL to push manifest repository')
  .action(async (options) => {
    try {
      await migrate(options);
    } catch (error) {
      console.error(chalk.red(error instanceof Error ? error.message : String(error)));
      process.exit(1);
    }
  });

// Sync command
program
  .command('sync')
  .description('Pull latest changes from manifest and all repositories')
  .option('--fetch', 'Fetch only (do not merge)')
  .option('--no-link', 'Skip processing copyfile/linkfile entries')
  .option('--no-hooks', 'Skip running post-sync hooks')
  .action(async (options) => {
    try {
      await sync({
        fetch: options.fetch,
        noLink: !options.link,
        noHooks: !options.hooks,
      });
    } catch (error) {
      console.error(chalk.red(error instanceof Error ? error.message : String(error)));
      process.exit(1);
    }
  });

// Status command
program
  .command('status')
  .description('Show status of all repositories')
  .option('--json', 'Output as JSON')
  .action(async (options) => {
    try {
      await status(options);
    } catch (error) {
      console.error(chalk.red(error instanceof Error ? error.message : String(error)));
      process.exit(1);
    }
  });

// Branch command
program
  .command('branch [name]')
  .description('Create or list branches across all repositories')
  .option('-c, --create', 'Create a new branch')
  .option('-r, --repo <repos...>', 'Only operate on specific repositories')
  .option('--include-manifest', 'Include manifest repo in branch operation')
  .action(async (name, options) => {
    try {
      if (name) {
        await branch(name, { create: options.create, repo: options.repo, includeManifest: options.includeManifest });
      } else {
        await listBranches();
      }
    } catch (error) {
      console.error(chalk.red(error instanceof Error ? error.message : String(error)));
      process.exit(1);
    }
  });

// Checkout command
program
  .command('checkout <branch>')
  .description('Checkout a branch across all repositories')
  .option('-b', 'Create the branch if it does not exist')
  .option('--no-hooks', 'Skip running post-checkout hooks')
  .action(async (branchName, options) => {
    try {
      await checkout(branchName, { create: options.b, noHooks: !options.hooks });
    } catch (error) {
      console.error(chalk.red(error instanceof Error ? error.message : String(error)));
      process.exit(1);
    }
  });

// Link command
program
  .command('link')
  .description('Create/update copyfile and linkfile entries')
  .option('--status', 'Show link status (valid, broken, missing)')
  .option('--clean', 'Remove orphaned links')
  .option('--force', 'Overwrite existing files/links')
  .option('--dry-run', 'Preview changes without executing')
  .action(async (options) => {
    try {
      await link(options);
    } catch (error) {
      console.error(chalk.red(error instanceof Error ? error.message : String(error)));
      process.exit(1);
    }
  });

// Run command
program
  .command('run [script]')
  .description('Run a workspace script')
  .option('--list', 'List available scripts')
  .allowUnknownOption(true)
  .action(async (scriptName, options, command) => {
    try {
      // Get remaining args after "--"
      const args = command.args.slice(1);
      await run(scriptName, args, { list: options.list });
    } catch (error) {
      console.error(chalk.red(error instanceof Error ? error.message : String(error)));
      process.exit(1);
    }
  });

// Env command
program
  .command('env')
  .description('Show workspace environment variables')
  .option('--json', 'Output as JSON')
  .action(async (options) => {
    try {
      await env(options);
    } catch (error) {
      console.error(chalk.red(error instanceof Error ? error.message : String(error)));
      process.exit(1);
    }
  });

// PR commands
const pr = program.command('pr').description('Pull request management');

pr.command('create')
  .description('Create linked PRs across repositories')
  .option('-t, --title <title>', 'PR title')
  .option('-b, --body <body>', 'PR body')
  .option('-d, --draft', 'Create as draft PR')
  .option('--base <branch>', 'Base branch to merge into')
  .option('--push', 'Push branches to remote if needed')
  .action(async (options) => {
    try {
      await createPR(options);
    } catch (error) {
      console.error(chalk.red(error instanceof Error ? error.message : String(error)));
      process.exit(1);
    }
  });

pr.command('status')
  .description('Show status of PRs for current branch')
  .option('--json', 'Output as JSON')
  .action(async (options) => {
    try {
      await prStatus(options);
    } catch (error) {
      console.error(chalk.red(error instanceof Error ? error.message : String(error)));
      process.exit(1);
    }
  });

pr.command('merge')
  .description('Merge all PRs for current branch')
  .option('-m, --method <method>', 'Merge method: merge, squash, rebase', 'merge')
  .option('--no-delete-branch', 'Do not delete branch after merge')
  .option('-f, --force', 'Merge even if not all checks pass')
  .action(async (options) => {
    try {
      await mergePRs({
        method: options.method as 'merge' | 'squash' | 'rebase',
        deleteBranch: options.deleteBranch,
        force: options.force,
      });
    } catch (error) {
      console.error(chalk.red(error instanceof Error ? error.message : String(error)));
      process.exit(1);
    }
  });

// Bench command
program
  .command('bench [operation]')
  .description('Benchmark workspace operations')
  .option('--list', 'List available benchmarks')
  .option('-n, --iterations <n>', 'Number of iterations', '5')
  .option('-w, --warmup <n>', 'Number of warmup iterations', '1')
  .option('--json', 'Output as JSON')
  .action(async (operation, options) => {
    try {
      await bench(operation, {
        list: options.list,
        iterations: parseInt(options.iterations, 10),
        warmup: parseInt(options.warmup, 10),
        json: options.json,
      });
    } catch (error) {
      console.error(chalk.red(error instanceof Error ? error.message : String(error)));
      process.exit(1);
    }
  });

// Commit command
program
  .command('commit')
  .description('Commit staged changes across all repositories')
  .option('-m, --message <message>', 'Commit message')
  .option('-a, --all', 'Stage all changes before committing')
  .action(async (options) => {
    try {
      await commit({
        message: options.message,
        all: options.all,
      });
    } catch (error) {
      console.error(chalk.red(error instanceof Error ? error.message : String(error)));
      process.exit(1);
    }
  });

// Push command
program
  .command('push')
  .description('Push current branch to remote across all repositories')
  .option('-u, --set-upstream', 'Set upstream tracking for the branch')
  .option('-f, --force', 'Force push (use with caution)')
  .action(async (options) => {
    try {
      await push({
        setUpstream: options.setUpstream,
        force: options.force,
      });
    } catch (error) {
      console.error(chalk.red(error instanceof Error ? error.message : String(error)));
      process.exit(1);
    }
  });

// Add command
program
  .command('add [files...]')
  .description('Stage changes across all repositories')
  .option('-A, --all', 'Stage all changes (same as git add -A)')
  .action(async (files, options) => {
    try {
      await add(files ?? [], { all: options.all });
    } catch (error) {
      console.error(chalk.red(error instanceof Error ? error.message : String(error)));
      process.exit(1);
    }
  });

// Diff command
program
  .command('diff')
  .description('Show diff across all repositories')
  .option('--staged', 'Show staged changes')
  .option('--stat', 'Show diffstat')
  .option('--name-only', 'Show only file names')
  .action(async (options) => {
    try {
      await diff({
        staged: options.staged,
        stat: options.stat,
        nameOnly: options.nameOnly,
      });
    } catch (error) {
      console.error(chalk.red(error instanceof Error ? error.message : String(error)));
      process.exit(1);
    }
  });

// Forall command - run command in all repos (like AOSP repo forall)
program
  .command('forall')
  .description('Run a command in each repository (like AOSP repo forall)')
  .requiredOption('-c, --command <command>', 'Command to run in each repo')
  .option('-r, --repo <repos...>', 'Only run in specific repositories')
  .option('--include-manifest', 'Include manifest repo')
  .option('--continue-on-error', 'Continue running in other repos if command fails')
  .action(async (options) => {
    try {
      await forall({
        command: options.command,
        repo: options.repo,
        includeManifest: options.includeManifest,
        continueOnError: options.continueOnError,
      });
    } catch (error) {
      console.error(chalk.red(error instanceof Error ? error.message : String(error)));
      process.exit(1);
    }
  });

// Parse and execute
program.parse();
