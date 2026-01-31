import chalk from 'chalk';
import { loadManifest } from '../lib/manifest.js';

export interface EnvOptions {
  json?: boolean;
}

/**
 * Show workspace environment variables
 */
export async function env(options: EnvOptions = {}): Promise<void> {
  const { manifest } = await loadManifest();
  const workspaceEnv = manifest.workspace?.env ?? {};

  if (options.json) {
    console.log(JSON.stringify(workspaceEnv, null, 2));
    return;
  }

  const entries = Object.entries(workspaceEnv);

  if (entries.length === 0) {
    console.log(chalk.dim('No workspace environment variables defined.'));
    console.log(chalk.dim('\nAdd env vars to your manifest.yaml:'));
    console.log(chalk.dim(`
workspace:
  env:
    NODE_ENV: development
    DEBUG: "true"
`));
    return;
  }

  console.log(chalk.blue('Workspace Environment Variables\n'));

  // Find longest key for alignment
  const maxKeyLength = Math.max(...entries.map(([key]) => key.length));

  for (const [key, value] of entries) {
    const paddedKey = key.padEnd(maxKeyLength);
    console.log(`  ${chalk.cyan(paddedKey)}  ${value}`);
  }

  console.log('');
  console.log(chalk.dim(`These variables are passed to scripts run with 'cr run <script>'`));
}
