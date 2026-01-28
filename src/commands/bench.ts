import chalk from 'chalk';
import { loadManifest, getAllRepoInfo, getManifestsDir } from '../lib/manifest.js';
import { getAllRepoStatus, branchExists, pathExists } from '../lib/git.js';
import { getAllLinkStatus } from '../lib/files.js';
import { runBenchmark, formatBenchmarkResults } from '../lib/timing.js';
import type { BenchmarkResult } from '../types.js';

interface BenchOptions {
  list?: boolean;
  iterations?: number;
  warmup?: number;
  json?: boolean;
}

/**
 * Available benchmark operations
 */
const BENCHMARKS: Record<string, { description: string; fn: () => Promise<void> }> = {
  'manifest-load': {
    description: 'Load and parse manifest',
    fn: async () => {
      await loadManifest();
    },
  },
  status: {
    description: 'Full status check',
    fn: async () => {
      const { manifest, rootDir } = await loadManifest();
      const repos = getAllRepoInfo(manifest, rootDir);
      await getAllRepoStatus(repos);
    },
  },
  'link-status': {
    description: 'Check link status',
    fn: async () => {
      const { manifest, rootDir } = await loadManifest();
      const manifestsDir = getManifestsDir(rootDir);
      await getAllLinkStatus(manifest, rootDir, manifestsDir);
    },
  },
  'branch-check': {
    description: 'Check branch existence',
    fn: async () => {
      const { manifest, rootDir } = await loadManifest();
      const repos = getAllRepoInfo(manifest, rootDir);
      for (const repo of repos) {
        if (await pathExists(repo.absolutePath)) {
          await branchExists(repo.absolutePath, repo.default_branch);
        }
      }
    },
  },
};

/**
 * List available benchmarks
 */
function listBenchmarks(): void {
  console.log(chalk.blue('Available Benchmarks\n'));

  const maxNameLen = Math.max(...Object.keys(BENCHMARKS).map((k) => k.length));

  for (const [name, { description }] of Object.entries(BENCHMARKS)) {
    console.log(`  ${chalk.cyan(name.padEnd(maxNameLen))}  ${description}`);
  }

  console.log('');
  console.log(chalk.dim('Run a specific benchmark:'));
  console.log(chalk.dim('  cr bench manifest-load'));
  console.log(chalk.dim('  cr bench status -n 10'));
  console.log('');
  console.log(chalk.dim('Run all benchmarks:'));
  console.log(chalk.dim('  cr bench'));
}

/**
 * Run a single benchmark
 */
async function runSingleBenchmark(
  name: string,
  options: { iterations: number; warmup: number }
): Promise<BenchmarkResult> {
  const benchmark = BENCHMARKS[name];
  if (!benchmark) {
    throw new Error(`Unknown benchmark: ${name}. Use --list to see available benchmarks.`);
  }

  return runBenchmark(name, benchmark.fn, options);
}

/**
 * Benchmark workspace operations
 */
export async function bench(operation: string | undefined, options: BenchOptions = {}): Promise<void> {
  const { list = false, iterations = 5, warmup = 1, json = false } = options;

  // List mode
  if (list) {
    listBenchmarks();
    return;
  }

  // Check if we're in a workspace
  try {
    await loadManifest();
  } catch {
    console.log(chalk.yellow('Not in a codi-repo workspace.'));
    console.log(chalk.dim('Run `codi-repo init <manifest-url>` first.'));
    return;
  }

  const results: BenchmarkResult[] = [];

  if (operation) {
    // Run single benchmark
    if (!json) {
      console.log(chalk.blue(`Running benchmark: ${operation}\n`));
      console.log(chalk.dim(`Iterations: ${iterations}, Warmup: ${warmup}\n`));
    }

    const result = await runSingleBenchmark(operation, { iterations, warmup });
    results.push(result);
  } else {
    // Run all benchmarks
    if (!json) {
      console.log(chalk.blue('Running all benchmarks\n'));
      console.log(chalk.dim(`Iterations: ${iterations}, Warmup: ${warmup}\n`));
    }

    for (const name of Object.keys(BENCHMARKS)) {
      if (!json) {
        process.stdout.write(`  ${name}...`);
      }

      try {
        const result = await runSingleBenchmark(name, { iterations, warmup });
        results.push(result);

        if (!json) {
          console.log(chalk.green(' done'));
        }
      } catch (error) {
        if (!json) {
          console.log(chalk.red(` failed: ${error instanceof Error ? error.message : String(error)}`));
        }
      }
    }

    if (!json) {
      console.log('');
    }
  }

  // Output results
  if (json) {
    console.log(JSON.stringify(results, null, 2));
  } else {
    console.log(formatBenchmarkResults(results));
  }
}
