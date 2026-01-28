import { describe, bench, beforeAll, afterAll } from 'vitest';
import { mkdir, rm, writeFile } from 'fs/promises';
import { join } from 'path';
import { tmpdir } from 'os';
import { parseGitHubUrl, loadManifest, getManifestPath } from '../manifest.js';

describe('Manifest Operations', () => {
  bench('parseGitHubUrl - SSH', () => {
    parseGitHubUrl('git@github.com:owner/repo.git');
  });

  bench('parseGitHubUrl - HTTPS', () => {
    parseGitHubUrl('https://github.com/owner/repo.git');
  });

  bench('parseGitHubUrl - SSH without .git', () => {
    parseGitHubUrl('git@github.com:owner/repo');
  });

  bench('parseGitHubUrl - HTTPS without .git', () => {
    parseGitHubUrl('https://github.com/owner/repo');
  });
});

describe('Manifest Loading', () => {
  let testDir: string;
  let manifestPath: string;

  beforeAll(async () => {
    testDir = join(tmpdir(), `codi-repo-bench-${Date.now()}`);
    const manifestsDir = join(testDir, '.codi-repo', 'manifests');
    await mkdir(manifestsDir, { recursive: true });

    // Create a realistic manifest
    const manifest = `
version: 1
repos:
  repo1:
    url: git@github.com:owner/repo1.git
    path: ./repo1
    default_branch: main
  repo2:
    url: git@github.com:owner/repo2.git
    path: ./repo2
    default_branch: main
  repo3:
    url: git@github.com:owner/repo3.git
    path: ./repo3
    default_branch: main
settings:
  pr_prefix: "[cross-repo]"
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
    manifestPath = join(manifestsDir, 'manifest.yaml');
    await writeFile(manifestPath, manifest);
  });

  afterAll(async () => {
    await rm(testDir, { recursive: true, force: true });
  });

  bench('loadManifest', async () => {
    await loadManifest(manifestPath);
  });

  bench('getManifestPath', () => {
    getManifestPath('/workspace/test');
  });
});
