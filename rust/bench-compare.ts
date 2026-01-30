#!/usr/bin/env npx tsx
/**
 * TypeScript benchmarks for comparison with Rust version
 *
 * Run with: npx tsx rust/bench-compare.ts
 */

import * as fs from 'fs';
import * as yaml from 'yaml';
import * as path from 'path';

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

async function main() {
  const iterations = parseInt(process.argv[2] || '10');
  console.log(`Running TypeScript benchmarks (iterations: ${iterations})...\n`);

  const results: BenchmarkResult[] = [];

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

  // Benchmark: URL parsing
  const urlResult = benchmark('url_parse', iterations, () => {
    parseGitUrl('git@github.com:organization/repository-name.git');
  });
  printResult(urlResult);
  results.push(urlResult);

  // Summary
  console.log('\n=== Summary ===');
  for (const result of results) {
    console.log(`${result.name}: avg=${result.avg.toFixed(3)}ms, p50=${result.p50.toFixed(3)}ms, p95=${result.p95.toFixed(3)}ms (n=${result.iterations})`);
  }
}

main().catch(console.error);
