#!/usr/bin/env npx tsx
/**
 * TypeScript benchmarks for comparison with Rust version
 *
 * Run with: npx tsx rust/bench-compare.ts [iterations]
 *
 * These benchmarks mirror the Rust Criterion benchmarks in benches/benchmarks.rs
 */

import * as fs from 'fs';
import * as path from 'path';
import * as yaml from 'yaml';
import * as crypto from 'crypto';
import { execSync } from 'child_process';
import { tmpdir } from 'os';

interface BenchmarkResult {
  name: string;
  iterations: number;
  min: number;
  max: number;
  avg: number;
  p50: number;
  p95: number;
  stdDev: number;
}

function benchmark(name: string, iterations: number, fn: () => void): BenchmarkResult {
  const durations: number[] = [];

  // Warmup
  for (let i = 0; i < 3; i++) {
    fn();
  }

  // Actual benchmark
  for (let i = 0; i < iterations; i++) {
    const start = performance.now();
    fn();
    durations.push(performance.now() - start);
  }

  durations.sort((a, b) => a - b);

  const min = durations[0];
  const max = durations[durations.length - 1];
  const sum = durations.reduce((a, b) => a + b, 0);
  const avg = sum / iterations;

  const p50Idx = Math.floor(iterations * 0.50);
  const p95Idx = Math.floor(iterations * 0.95);
  const p50 = durations[Math.min(p50Idx, durations.length - 1)];
  const p95 = durations[Math.min(p95Idx, durations.length - 1)];

  const variance = durations.reduce((acc, d) => acc + Math.pow(d - avg, 2), 0) / iterations;
  const stdDev = Math.sqrt(variance);

  return { name, iterations, min, max, avg, p50, p95, stdDev };
}

function printResult(result: BenchmarkResult) {
  console.log(`\n--- Benchmark: ${result.name} ---`);
  console.log(`Iterations: ${result.iterations}`);
  console.log(`Min:    ${result.min.toFixed(3)}ms`);
  console.log(`Max:    ${result.max.toFixed(3)}ms`);
  console.log(`Avg:    ${result.avg.toFixed(3)}ms`);
  console.log(`P50:    ${result.p50.toFixed(3)}ms`);
  console.log(`P95:    ${result.p95.toFixed(3)}ms`);
  console.log(`StdDev: ${result.stdDev.toFixed(3)}ms`);
}

// Test data - same as Rust version
const manifestYaml = `
version: 1
manifest:
  url: git@github.com:user/manifest.git
  default_branch: main
repos:
  app:
    url: git@github.com:user/app.git
    path: app
    default_branch: main
    copyfile:
      - src: README.md
        dest: APP_README.md
    linkfile:
      - src: config.yaml
        dest: app-config.yaml
  lib:
    url: git@github.com:user/lib.git
    path: lib
    default_branch: main
  api:
    url: git@github.com:user/api.git
    path: api
    default_branch: main
settings:
  pr_prefix: "[multi-repo]"
  merge_strategy: all-or-nothing
workspace:
  env:
    NODE_ENV: development
  scripts:
    build:
      description: Build all packages
      command: npm run build
    test:
      description: Run tests
      steps:
        - name: lint
          command: npm run lint
        - name: test
          command: npm test
`;

const stateJson = `{
  "currentManifestPr": 42,
  "branchToPr": {
    "feat/new-feature": 42,
    "feat/another": 43,
    "fix/bug": 44
  },
  "prLinks": {
    "42": [
      {
        "repoName": "app",
        "owner": "user",
        "repo": "app",
        "number": 123,
        "url": "https://github.com/user/app/pull/123",
        "state": "open",
        "approved": true,
        "checksPass": true,
        "mergeable": true
      },
      {
        "repoName": "lib",
        "owner": "user",
        "repo": "lib",
        "number": 456,
        "url": "https://github.com/user/lib/pull/456",
        "state": "open",
        "approved": false,
        "checksPass": true,
        "mergeable": true
      }
    ],
    "43": [],
    "44": []
  }
}`;

// URL parsing function (simplified version of what gitgrip does)
function parseGitUrl(url: string): { owner: string; repo: string } | null {
  // SSH URL: git@github.com:owner/repo.git
  if (url.startsWith('git@')) {
    const parts = url.split(':');
    if (parts.length !== 2) return null;
    const pathPart = parts[1].replace(/\.git$/, '');
    const segments = pathPart.split('/');
    if (segments.length >= 2) {
      return { owner: segments[0], repo: segments[segments.length - 1] };
    }
  }

  // HTTPS URL
  if (url.startsWith('https://') || url.startsWith('http://')) {
    const urlObj = new URL(url);
    const pathPart = urlObj.pathname.replace(/^\//, '').replace(/\.git$/, '');
    const segments = pathPart.split('/');
    if (segments.length >= 2) {
      return { owner: segments[0], repo: segments[segments.length - 1] };
    }
  }

  return null;
}

// Manifest validation (simplified)
interface Manifest {
  version: number;
  repos: Record<string, { url: string; path: string; default_branch?: string }>;
  settings?: { pr_prefix?: string; merge_strategy?: string };
}

function validateManifest(manifest: Manifest): { valid: boolean; errors: string[] } {
  const errors: string[] = [];

  if (manifest.version !== 1) {
    errors.push('Invalid version');
  }

  if (!manifest.repos || Object.keys(manifest.repos).length === 0) {
    errors.push('No repos defined');
  }

  for (const [name, config] of Object.entries(manifest.repos || {})) {
    if (!config.url) {
      errors.push(`Repo ${name} missing URL`);
    }
    if (!config.path) {
      errors.push(`Repo ${name} missing path`);
    }
    // Check for path traversal
    if (config.path?.includes('..')) {
      errors.push(`Repo ${name} has invalid path`);
    }
  }

  return { valid: errors.length === 0, errors };
}

// Regex-based URL parsing (matches Rust version)
const githubRegex = /github\.com[:/]([^/]+)\/([^/.]+)/;
const gitlabRegex = /gitlab\.com[:/](.+)\/([^/.]+)/;
const azureRegex = /dev\.azure\.com\/([^/]+)\/([^/]+)\/_git\/([^/.]+)/;

function parseUrlWithRegex(url: string, regex: RegExp): RegExpMatchArray | null {
  return url.match(regex);
}

// Path operations
function pathJoin(workspace: string, repoPath: string): string {
  return path.join(workspace, repoPath);
}

function pathComponents(fullPath: string): string[] {
  return fullPath.split(path.sep).filter(Boolean);
}

// File hashing
function hashContent(content: string): string {
  return crypto.createHash('sha256').update(content).digest('hex');
}

// Setup a test git repo for git benchmarks
function setupTestRepo(): string {
  const tempDir = fs.mkdtempSync(path.join(tmpdir(), 'bench-repo-'));
  execSync('git init', { cwd: tempDir, stdio: 'pipe' });
  execSync('git config user.name "Bench User"', { cwd: tempDir, stdio: 'pipe' });
  execSync('git config user.email "bench@example.com"', { cwd: tempDir, stdio: 'pipe' });

  // Create initial commit
  fs.writeFileSync(path.join(tempDir, 'README.md'), '# Benchmark Repo');
  execSync('git add README.md', { cwd: tempDir, stdio: 'pipe' });
  execSync('git commit -m "Initial commit"', { cwd: tempDir, stdio: 'pipe' });

  // Create some branches
  for (let i = 0; i < 10; i++) {
    execSync(`git branch branch-${i}`, { cwd: tempDir, stdio: 'pipe' });
  }

  // Add some files
  for (let i = 0; i < 10; i++) {
    fs.writeFileSync(path.join(tempDir, `file${i}.txt`), `Content ${i}`);
  }

  return tempDir;
}

function cleanupTestRepo(repoPath: string) {
  fs.rmSync(repoPath, { recursive: true, force: true });
}

async function main() {
  const iterations = parseInt(process.argv[2] || '100');
  console.log(`Running TypeScript benchmarks (iterations: ${iterations})...\n`);

  const results: BenchmarkResult[] = [];

  // ============================================
  // Core Parsing Benchmarks (match Rust)
  // ============================================

  // Benchmark: Manifest parsing
  const manifestResult = benchmark('manifest_parse', iterations, () => {
    yaml.parse(manifestYaml);
  });
  printResult(manifestResult);
  results.push(manifestResult);

  // Benchmark: State parsing
  const stateResult = benchmark('state_parse', iterations, () => {
    JSON.parse(stateJson);
  });
  printResult(stateResult);
  results.push(stateResult);

  // Benchmark: URL parsing (GitHub SSH)
  const urlResult = benchmark('url_parse_github_ssh', iterations, () => {
    parseGitUrl('git@github.com:organization/repository-name.git');
  });
  printResult(urlResult);
  results.push(urlResult);

  // Benchmark: URL parsing (Azure HTTPS)
  const urlAzureResult = benchmark('url_parse_azure_https', iterations, () => {
    parseGitUrl('https://dev.azure.com/organization/project/_git/repository');
  });
  printResult(urlAzureResult);
  results.push(urlAzureResult);

  // Benchmark: Manifest validation
  const parsedManifest = yaml.parse(manifestYaml) as Manifest;
  const validateResult = benchmark('manifest_validate', iterations, () => {
    validateManifest(parsedManifest);
  });
  printResult(validateResult);
  results.push(validateResult);

  // ============================================
  // Path Operation Benchmarks (match Rust)
  // ============================================

  const workspace = '/home/user/workspace';
  const repoPath = 'packages/my-awesome-repo';

  const pathJoinResult = benchmark('path_join', iterations, () => {
    pathJoin(workspace, repoPath);
  });
  printResult(pathJoinResult);
  results.push(pathJoinResult);

  const fullPath = path.join(workspace, repoPath);
  const pathComponentsResult = benchmark('path_canonicalize_relative', iterations, () => {
    pathComponents(fullPath);
  });
  printResult(pathComponentsResult);
  results.push(pathComponentsResult);

  // ============================================
  // Regex URL Parsing Benchmarks (match Rust)
  // ============================================

  const githubUrl = 'git@github.com:organization/repository-name.git';
  const regexGithubResult = benchmark('url_regex_github', iterations, () => {
    parseUrlWithRegex(githubUrl, githubRegex);
  });
  printResult(regexGithubResult);
  results.push(regexGithubResult);

  const gitlabUrl = 'git@gitlab.com:group/subgroup/repo.git';
  const regexGitlabResult = benchmark('url_regex_gitlab', iterations, () => {
    parseUrlWithRegex(gitlabUrl, gitlabRegex);
  });
  printResult(regexGitlabResult);
  results.push(regexGitlabResult);

  // ============================================
  // File Hashing Benchmark (match Rust)
  // ============================================

  const testContent = 'This is some test content for hashing\n'.repeat(100);
  const hashResult = benchmark('file_hash_content', iterations, () => {
    hashContent(testContent);
  });
  printResult(hashResult);
  results.push(hashResult);

  // ============================================
  // Git Operation Benchmarks (match Rust)
  // ============================================

  console.log('\nSetting up test git repository...');
  const testRepoPath = setupTestRepo();

  try {
    // Benchmark: Git status
    const gitStatusResult = benchmark('git_status', Math.min(iterations, 50), () => {
      execSync('git status --porcelain', { cwd: testRepoPath, stdio: 'pipe' });
    });
    printResult(gitStatusResult);
    results.push(gitStatusResult);

    // Benchmark: Git list branches
    const gitBranchResult = benchmark('git_list_branches', Math.min(iterations, 50), () => {
      execSync('git branch --list', { cwd: testRepoPath, stdio: 'pipe' });
    });
    printResult(gitBranchResult);
    results.push(gitBranchResult);
  } finally {
    cleanupTestRepo(testRepoPath);
  }

  // ============================================
  // Summary
  // ============================================

  console.log('\n=== Summary ===');
  for (const result of results) {
    console.log(`${result.name}: avg=${result.avg.toFixed(3)}ms, p50=${result.p50.toFixed(3)}ms, p95=${result.p95.toFixed(3)}ms (n=${result.iterations})`);
  }
}

main().catch(console.error);
