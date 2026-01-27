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

const program = new Command();

program
  .name('codi-repo')
  .description('Multi-repository orchestration CLI for unified PR workflows')
  .version('0.1.0');

// Init command - AOSP-style with manifest URL
program
  .command('init <manifest-url>')
  .description('Initialize a codi-repo workspace from a manifest repository')
  .action(async (manifestUrl) => {
    try {
      await init(manifestUrl);
    } catch (error) {
      console.error(chalk.red(error instanceof Error ? error.message : String(error)));
      process.exit(1);
    }
  });

// Migrate command - convert legacy format to new structure
program
  .command('migrate')
  .description('Migrate from legacy codi-repos.yaml to .codi-repo/manifests/ structure')
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
  .action(async (options) => {
    try {
      await sync(options);
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
  .action(async (name, options) => {
    try {
      if (name) {
        await branch(name, options);
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
  .action(async (branchName, options) => {
    try {
      await checkout(branchName, { create: options.b });
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

// Parse and execute
program.parse();
