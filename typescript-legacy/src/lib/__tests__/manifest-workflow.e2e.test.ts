/**
 * Manifest-based workflow E2E tests
 *
 * Tests the full codi-repo workflow using the new AOSP-style manifest structure:
 * - Creating/loading manifest from .codi-repo/manifests/
 * - Cloning repos
 * - Branch operations across repos
 * - Status aggregation
 *
 * Run with: GITHUB_E2E=1 npx vitest run src/lib/__tests__/manifest-workflow.e2e.test.ts
 */

import { describe, it, expect, beforeAll, afterAll } from 'vitest';
import { mkdir, rm, writeFile, access } from 'fs/promises';
import { join } from 'path';
import { tmpdir } from 'os';

const runE2E = process.env.GITHUB_E2E === '1';

describe.skipIf(!runE2E)('Manifest Workflow E2E Tests', () => {
  const TEST_OWNER = 'laynepenney';
  let workspaceDir: string;
  let testBranchName: string;

  // Test manifest content (new format)
  const manifestContent = `
version: 1
repos:
  repo1:
    url: git@github.com:${TEST_OWNER}/codi-repo-test.git
    path: ./repo1
    default_branch: main
  repo2:
    url: git@github.com:${TEST_OWNER}/codi-repo-test-2.git
    path: ./repo2
    default_branch: main
settings:
  pr_prefix: "[cross-repo]"
  merge_strategy: all-or-nothing
`;

  beforeAll(async () => {
    // Create a temp workspace directory with AOSP-style structure
    workspaceDir = join(tmpdir(), `codi-repo-test-${Date.now()}`);
    const manifestsDir = join(workspaceDir, '.codi-repo', 'manifests');
    await mkdir(manifestsDir, { recursive: true });

    // Write manifest file in new location
    await writeFile(join(manifestsDir, 'manifest.yaml'), manifestContent);

    testBranchName = `test/manifest-${Date.now()}`;
    console.log(`Workspace: ${workspaceDir}`);
    console.log(`Test branch: ${testBranchName}`);
  });

  afterAll(async () => {
    // Cleanup: delete test branches from GitHub
    const { getOctokit } = await import('../github.js');
    const octokit = getOctokit();

    for (const repo of ['codi-repo-test', 'codi-repo-test-2']) {
      try {
        await octokit.git.deleteRef({
          owner: TEST_OWNER,
          repo,
          ref: `heads/${testBranchName}`,
        });
        console.log(`Deleted branch ${testBranchName} from ${repo}`);
      } catch {
        // Branch may not exist
      }
    }

    // Cleanup workspace
    try {
      await rm(workspaceDir, { recursive: true, force: true });
      console.log(`Deleted workspace: ${workspaceDir}`);
    } catch {
      console.log(`Failed to delete workspace: ${workspaceDir}`);
    }
  });

  describe('Manifest Loading', () => {
    it('can load manifest from .codi-repo/manifests/', async () => {
      const { loadManifest } = await import('../manifest.js');

      const manifestPath = join(workspaceDir, '.codi-repo', 'manifests', 'manifest.yaml');
      const { manifest, rootDir } = await loadManifest(manifestPath);

      expect(manifest.version).toBe(1);
      expect(Object.keys(manifest.repos)).toEqual(['repo1', 'repo2']);
      expect(manifest.repos.repo1.url).toContain('codi-repo-test');
      expect(manifest.repos.repo2.url).toContain('codi-repo-test-2');
      expect(manifest.settings.merge_strategy).toBe('all-or-nothing');
      // rootDir should be the workspace root, not the manifests dir
      expect(rootDir).toBe(workspaceDir);

      console.log('Manifest loaded successfully');
    });

    it('can get repo info with computed fields', async () => {
      const { loadManifest, getAllRepoInfo } = await import('../manifest.js');

      const manifestPath = join(workspaceDir, '.codi-repo', 'manifests', 'manifest.yaml');
      const { manifest, rootDir } = await loadManifest(manifestPath);
      const repos = getAllRepoInfo(manifest, rootDir);

      expect(repos.length).toBe(2);

      for (const repo of repos) {
        expect(repo.owner).toBe(TEST_OWNER);
        expect(repo.absolutePath).toContain(workspaceDir);
        expect(['codi-repo-test', 'codi-repo-test-2']).toContain(repo.repo);
      }

      console.log('Repo info:');
      for (const repo of repos) {
        console.log(`  ${repo.name}: ${repo.owner}/${repo.repo} -> ${repo.path}`);
      }
    });
  });

  describe('Repository Cloning', () => {
    it('can clone repos defined in manifest', async () => {
      const { loadManifest, getAllRepoInfo } = await import('../manifest.js');
      const { cloneRepo, pathExists } = await import('../git.js');

      const manifestPath = join(workspaceDir, '.codi-repo', 'manifests', 'manifest.yaml');
      const { manifest, rootDir } = await loadManifest(manifestPath);
      const repos = getAllRepoInfo(manifest, rootDir);

      for (const repo of repos) {
        if (await pathExists(repo.absolutePath)) {
          console.log(`${repo.name}: already exists`);
          continue;
        }

        await cloneRepo(repo.url, repo.absolutePath, repo.default_branch);
        console.log(`Cloned ${repo.name} to ${repo.path}`);

        // Verify clone succeeded
        const exists = await pathExists(repo.absolutePath);
        expect(exists).toBe(true);
      }
    }, 60000); // 60s timeout for cloning

    it('all repos exist after cloning', async () => {
      const { loadManifest, getAllRepoInfo } = await import('../manifest.js');
      const { pathExists } = await import('../git.js');

      const manifestPath = join(workspaceDir, '.codi-repo', 'manifests', 'manifest.yaml');
      const { manifest, rootDir } = await loadManifest(manifestPath);
      const repos = getAllRepoInfo(manifest, rootDir);

      for (const repo of repos) {
        const exists = await pathExists(repo.absolutePath);
        expect(exists).toBe(true);
      }
    });
  });

  describe('Status Across Repos', () => {
    it('can get status for all repos', async () => {
      const { loadManifest, getAllRepoInfo } = await import('../manifest.js');
      const { getAllRepoStatus } = await import('../git.js');

      const manifestPath = join(workspaceDir, '.codi-repo', 'manifests', 'manifest.yaml');
      const { manifest, rootDir } = await loadManifest(manifestPath);
      const repos = getAllRepoInfo(manifest, rootDir);
      const statuses = await getAllRepoStatus(repos);

      expect(statuses.length).toBe(2);

      for (const status of statuses) {
        expect(status.exists).toBe(true);
        expect(status.branch).toBe('main');
        expect(status.clean).toBe(true);
      }

      console.log('Status:');
      for (const status of statuses) {
        console.log(`  ${status.name}: ${status.branch}, clean=${status.clean}`);
      }
    });
  });

  describe('Branch Operations', () => {
    it('can create branch in all repos', async () => {
      const { loadManifest, getAllRepoInfo } = await import('../manifest.js');
      const { createBranchInAllRepos, getCurrentBranch } = await import('../git.js');

      const manifestPath = join(workspaceDir, '.codi-repo', 'manifests', 'manifest.yaml');
      const { manifest, rootDir } = await loadManifest(manifestPath);
      const repos = getAllRepoInfo(manifest, rootDir);

      const results = await createBranchInAllRepos(repos, testBranchName);

      for (const result of results) {
        expect(result.success).toBe(true);
        console.log(`Created branch in ${result.repoName}`);
      }

      // Verify branches were created and checked out
      for (const repo of repos) {
        const currentBranch = await getCurrentBranch(repo.absolutePath);
        expect(currentBranch).toBe(testBranchName);
      }
    });

    it('can checkout branch in all repos', async () => {
      const { loadManifest, getAllRepoInfo } = await import('../manifest.js');
      const { checkoutBranchInAllRepos, getCurrentBranch } = await import('../git.js');

      const manifestPath = join(workspaceDir, '.codi-repo', 'manifests', 'manifest.yaml');
      const { manifest, rootDir } = await loadManifest(manifestPath);
      const repos = getAllRepoInfo(manifest, rootDir);

      // First checkout main
      await checkoutBranchInAllRepos(repos, 'main');

      for (const repo of repos) {
        const branch = await getCurrentBranch(repo.absolutePath);
        expect(branch).toBe('main');
      }

      // Then checkout test branch
      await checkoutBranchInAllRepos(repos, testBranchName);

      for (const repo of repos) {
        const branch = await getCurrentBranch(repo.absolutePath);
        expect(branch).toBe(testBranchName);
      }

      console.log(`All repos on branch: ${testBranchName}`);
    });
  });

  describe('State Management', () => {
    it('can save and load state', async () => {
      const { loadState, saveState } = await import('../manifest.js');

      const testState = {
        currentManifestPR: 123,
        branchToPR: { [testBranchName]: 123 },
        prLinks: {
          123: [
            {
              repoName: 'repo1',
              owner: TEST_OWNER,
              repo: 'codi-repo-test',
              number: 1,
              url: 'https://github.com/test',
              state: 'open' as const,
              approved: false,
              checksPass: false,
              mergeable: true,
            },
          ],
        },
      };

      await saveState(workspaceDir, testState);

      const loaded = await loadState(workspaceDir);

      expect(loaded.currentManifestPR).toBe(123);
      expect(loaded.branchToPR[testBranchName]).toBe(123);
      expect(loaded.prLinks[123]).toBeDefined();
      expect(loaded.prLinks[123][0].repoName).toBe('repo1');

      console.log('State saved and loaded successfully');
    });

    it('state file is in .codi-repo/', async () => {
      const statePath = join(workspaceDir, '.codi-repo', 'state.json');

      try {
        await access(statePath);
        console.log(`State file exists at: ${statePath}`);
      } catch {
        throw new Error('State file should exist');
      }
    });
  });

  describe('Linker Operations', () => {
    it('can link branch to manifest PR', async () => {
      const { linkBranchToManifestPR, getManifestPRForBranch } = await import('../linker.js');

      await linkBranchToManifestPR(workspaceDir, testBranchName, 456);

      const prNumber = await getManifestPRForBranch(workspaceDir, testBranchName);
      expect(prNumber).toBe(456);

      console.log(`Branch ${testBranchName} linked to PR #456`);
    });

    it('can check branch sync across repos', async () => {
      const { loadManifest, getAllRepoInfo } = await import('../manifest.js');
      const { checkBranchSync } = await import('../linker.js');

      const manifestPath = join(workspaceDir, '.codi-repo', 'manifests', 'manifest.yaml');
      const { manifest, rootDir } = await loadManifest(manifestPath);
      const repos = getAllRepoInfo(manifest, rootDir);

      const { inSync, missing } = await checkBranchSync(repos, testBranchName);

      expect(inSync).toBe(true);
      expect(missing.length).toBe(0);

      console.log(`Branch ${testBranchName} in sync across all repos`);
    });

    it('detects missing branches', async () => {
      const { loadManifest, getAllRepoInfo } = await import('../manifest.js');
      const { checkBranchSync } = await import('../linker.js');

      const manifestPath = join(workspaceDir, '.codi-repo', 'manifests', 'manifest.yaml');
      const { manifest, rootDir } = await loadManifest(manifestPath);
      const repos = getAllRepoInfo(manifest, rootDir);

      const { inSync, missing } = await checkBranchSync(repos, 'nonexistent-branch-xyz');

      expect(inSync).toBe(false);
      expect(missing.length).toBe(2);

      console.log(`Nonexistent branch missing from: ${missing.join(', ')}`);
    });
  });
});
