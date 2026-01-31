import chalk from 'chalk';
import { loadManifest } from '../lib/manifest.js';
import { runScript, listScripts } from '../lib/scripts.js';

export interface RunOptions {
  list?: boolean;
}

/**
 * Show available scripts
 */
async function showScripts(): Promise<void> {
  const { manifest } = await loadManifest();
  const scripts = listScripts(manifest);

  if (scripts.length === 0) {
    console.log(chalk.dim('No scripts defined in manifest.'));
    console.log(chalk.dim('\nAdd scripts to your manifest.yaml:'));
    console.log(chalk.dim(`
workspace:
  scripts:
    build:
      description: "Build all packages"
      command: "pnpm -r build"
`));
    return;
  }

  console.log(chalk.blue('Available Scripts\n'));

  // Find longest name for alignment
  const maxNameLength = Math.max(...scripts.map((s) => s.name.length));

  for (const script of scripts) {
    const paddedName = script.name.padEnd(maxNameLength);
    const desc = script.description ?? chalk.dim('(no description)');
    console.log(`  ${chalk.cyan(paddedName)}  ${desc}`);
  }

  console.log('');
  console.log(chalk.dim(`Run a script with: cr run <name>`));
  console.log(chalk.dim(`Pass extra args with: cr run <name> -- <args>`));
}

/**
 * Run a named script
 */
async function executeScript(scriptName: string, args: string[]): Promise<void> {
  const { manifest, rootDir } = await loadManifest();

  console.log(chalk.blue(`Running script: ${scriptName}\n`));

  const result = await runScript(scriptName, manifest, rootDir, args);

  console.log('');

  if (result.success) {
    if (result.steps.length > 1) {
      console.log(chalk.green(`\u2713 Script '${scriptName}' completed (${result.steps.length} steps)`));
    } else {
      console.log(chalk.green(`\u2713 Script '${scriptName}' completed`));
    }
  } else {
    const failedStep = result.steps.find((s) => !s.success);
    if (failedStep) {
      console.log(chalk.red(`\u2717 Script '${scriptName}' failed at step '${failedStep.name}'`));
      if (failedStep.error) {
        console.log(chalk.dim(`  Error: ${failedStep.error}`));
      }
      if (failedStep.exitCode !== null) {
        console.log(chalk.dim(`  Exit code: ${failedStep.exitCode}`));
      }
    }
    process.exit(1);
  }
}

/**
 * Main run command handler
 */
export async function run(scriptName?: string, args: string[] = [], options: RunOptions = {}): Promise<void> {
  if (options.list || !scriptName) {
    await showScripts();
  } else {
    await executeScript(scriptName, args);
  }
}
