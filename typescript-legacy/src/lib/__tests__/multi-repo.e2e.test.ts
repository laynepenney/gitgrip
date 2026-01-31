/**
 * Multi-repo E2E tests for codi-repo
 *
 * Tests the full cross-repository workflow:
 * - Creating branches across multiple repos
 * - Creating linked PRs
 * - Checking cross-repo status
 * - Merging linked PRs together
 *
 * Run with: GITHUB_E2E=1 npx vitest run src/lib/__tests__/multi-repo.e2e.test.ts
 */

import { describe, it, expect, beforeAll, afterAll } from 'vitest';
import type { RepoInfo, LinkedPR } from '../../types.js';

const runE2E = process.env.GITHUB_E2E === '1';

describe.skipIf(!runE2E)('Multi-Repo E2E Tests', () => {
  const TEST_OWNER = 'laynepenney';
  const TEST_REPOS = [
    { name: 'repo1', repo: 'codi-repo-test' },
    { name: 'repo2', repo: 'codi-repo-test-2' },
  ];

  let testBranchName: string;
  const createdPRs: { owner: string; repo: string; number: number }[] = [];

  beforeAll(() => {
    testBranchName = `test/multi-repo-${Date.now()}`;
    console.log(`Test branch: ${testBranchName}`);
  });

  afterAll(async () => {
    const { getOctokit } = await import('../github.js');
    const octokit = getOctokit();

    // Cleanup: close all PRs and delete branches
    for (const pr of createdPRs) {
      try {
        await octokit.pulls.update({
          owner: pr.owner,
          repo: pr.repo,
          pull_number: pr.number,
          state: 'closed',
        });
        console.log(`Closed ${pr.repo}#${pr.number}`);
      } catch (e) {
        console.log(`Failed to close PR ${pr.repo}#${pr.number}: ${e}`);
      }
    }

    for (const { repo } of TEST_REPOS) {
      try {
        await octokit.git.deleteRef({
          owner: TEST_OWNER,
          repo,
          ref: `heads/${testBranchName}`,
        });
        console.log(`Deleted branch ${testBranchName} from ${repo}`);
      } catch (e) {
        console.log(`Failed to delete branch from ${repo}: ${e}`);
      }
    }
  });

  describe('Cross-Repo Branch Creation', () => {
    it('can create the same branch in multiple repos', async () => {
      const { getOctokit } = await import('../github.js');
      const octokit = getOctokit();

      for (const { name, repo } of TEST_REPOS) {
        // Get main SHA
        const { data: mainRef } = await octokit.git.getRef({
          owner: TEST_OWNER,
          repo,
          ref: 'heads/main',
        });

        // Create branch
        const { data: newRef } = await octokit.git.createRef({
          owner: TEST_OWNER,
          repo,
          ref: `refs/heads/${testBranchName}`,
          sha: mainRef.object.sha,
        });

        expect(newRef.ref).toBe(`refs/heads/${testBranchName}`);
        console.log(`Created ${testBranchName} in ${repo}`);
      }
    });

    it('can create commits on the branch in each repo', async () => {
      const { getOctokit } = await import('../github.js');
      const octokit = getOctokit();

      for (const { name, repo } of TEST_REPOS) {
        const content = `# Multi-Repo Test\n\nRepo: ${repo}\nBranch: ${testBranchName}\nTime: ${new Date().toISOString()}`;

        const { data: file } = await octokit.repos.createOrUpdateFileContents({
          owner: TEST_OWNER,
          repo,
          path: `multi-repo-test/${testBranchName.replace(/\//g, '-')}.md`,
          message: `[Multi-Repo Test] Add test file`,
          content: Buffer.from(content).toString('base64'),
          branch: testBranchName,
        });

        expect(file.commit).toBeDefined();
        console.log(`Created commit in ${repo}: ${file.commit.sha?.slice(0, 7)}`);
      }
    });
  });

  describe('Cross-Repo PR Creation', () => {
    it('can create PRs in all repos with the same branch', async () => {
      const { createPullRequest } = await import('../github.js');

      for (const { name, repo } of TEST_REPOS) {
        const pr = await createPullRequest(
          TEST_OWNER,
          repo,
          testBranchName,
          'main',
          `[Multi-Repo Test] Cross-repo PR in ${name}`,
          `Part of multi-repo test.\n\nLinked repos: ${TEST_REPOS.map((r) => r.repo).join(', ')}`,
          false
        );

        expect(pr.number).toBeGreaterThan(0);
        createdPRs.push({ owner: TEST_OWNER, repo, number: pr.number });
        console.log(`Created PR in ${repo}: #${pr.number}`);
      }

      expect(createdPRs.length).toBe(TEST_REPOS.length);
    });

    it('can find all PRs by branch name', async () => {
      const { findPRByBranch } = await import('../github.js');

      for (const { name, repo } of TEST_REPOS) {
        const pr = await findPRByBranch(TEST_OWNER, repo, testBranchName);

        expect(pr).not.toBeNull();
        console.log(`Found PR in ${repo}: #${pr!.number}`);
      }
    });
  });

  describe('Cross-Repo Status Aggregation', () => {
    it('can get linked PR info for all repos', async () => {
      const { getLinkedPRInfo } = await import('../github.js');

      const linkedPRs: LinkedPR[] = [];

      for (const pr of createdPRs) {
        const repoName = TEST_REPOS.find((r) => r.repo === pr.repo)?.name ?? pr.repo;
        const info = await getLinkedPRInfo(pr.owner, pr.repo, pr.number, repoName);

        expect(info.state).toBe('open');
        expect(info.approved).toBe(false); // New PRs aren't approved
        linkedPRs.push(info);
      }

      expect(linkedPRs.length).toBe(TEST_REPOS.length);

      // All should be open
      expect(linkedPRs.every((pr) => pr.state === 'open')).toBe(true);

      console.log('Linked PR status:');
      for (const pr of linkedPRs) {
        console.log(`  ${pr.repoName}: #${pr.number} - ${pr.state}, approved=${pr.approved}, checks=${pr.checksPass}`);
      }
    });

    it('can generate manifest PR body with all linked PRs', async () => {
      const { generateManifestPRBody, getLinkedPRInfo } = await import('../github.js');

      const linkedPRs: LinkedPR[] = [];
      for (const pr of createdPRs) {
        const repoName = TEST_REPOS.find((r) => r.repo === pr.repo)?.name ?? pr.repo;
        const info = await getLinkedPRInfo(pr.owner, pr.repo, pr.number, repoName);
        linkedPRs.push(info);
      }

      const body = generateManifestPRBody('Multi-repo feature', linkedPRs, 'This PR spans multiple repos.');

      expect(body).toContain('Cross-Repository PR');
      expect(body).toContain('repo1');
      expect(body).toContain('repo2');
      expect(body).toContain('codi-repo:links:');

      console.log('Generated manifest PR body:');
      console.log(body.slice(0, 500) + '...');
    });

    it('can parse linked PRs from manifest body', async () => {
      const { generateManifestPRBody, parseLinkedPRsFromBody, getLinkedPRInfo } = await import('../github.js');

      const linkedPRs: LinkedPR[] = [];
      for (const pr of createdPRs) {
        const repoName = TEST_REPOS.find((r) => r.repo === pr.repo)?.name ?? pr.repo;
        const info = await getLinkedPRInfo(pr.owner, pr.repo, pr.number, repoName);
        linkedPRs.push(info);
      }

      const body = generateManifestPRBody('Test', linkedPRs);
      const parsed = parseLinkedPRsFromBody(body);

      expect(parsed.length).toBe(TEST_REPOS.length);
      expect(parsed.map((p) => p.repoName).sort()).toEqual(['repo1', 'repo2']);

      console.log('Parsed links:', parsed);
    });
  });

  describe('Cross-Repo Merge Readiness', () => {
    it('detects when not all PRs are ready to merge', async () => {
      const { getLinkedPRInfo } = await import('../github.js');

      let allReady = true;
      const issues: string[] = [];

      for (const pr of createdPRs) {
        const repoName = TEST_REPOS.find((r) => r.repo === pr.repo)?.name ?? pr.repo;
        const info = await getLinkedPRInfo(pr.owner, pr.repo, pr.number, repoName);

        if (!info.approved) {
          allReady = false;
          issues.push(`${repoName}: not approved`);
        }
        if (!info.mergeable) {
          allReady = false;
          issues.push(`${repoName}: not mergeable`);
        }
      }

      // New PRs without approval should not be ready
      expect(allReady).toBe(false);
      expect(issues.length).toBeGreaterThan(0);

      console.log('Merge readiness issues:', issues);
    });
  });

  describe('Cross-Repo Merge (optional)', () => {
    const runMergeTest = process.env.TEST_MERGE === '1';

    it.skipIf(!runMergeTest)('can merge all linked PRs atomically', async () => {
      const { getOctokit, mergePullRequest } = await import('../github.js');
      const octokit = getOctokit();

      // For this test, we need to create fresh PRs that we can merge
      const mergeBranch = `test/merge-multi-${Date.now()}`;
      const mergePRs: { owner: string; repo: string; number: number }[] = [];

      // Setup: create branch and PR in each repo
      for (const { repo } of TEST_REPOS) {
        const { data: mainRef } = await octokit.git.getRef({
          owner: TEST_OWNER,
          repo,
          ref: 'heads/main',
        });

        await octokit.git.createRef({
          owner: TEST_OWNER,
          repo,
          ref: `refs/heads/${mergeBranch}`,
          sha: mainRef.object.sha,
        });

        await octokit.repos.createOrUpdateFileContents({
          owner: TEST_OWNER,
          repo,
          path: `merge-test/${mergeBranch.replace(/\//g, '-')}.md`,
          message: `[Merge Test] Add file`,
          content: Buffer.from(`Merge test at ${new Date().toISOString()}`).toString('base64'),
          branch: mergeBranch,
        });

        const { data: pr } = await octokit.pulls.create({
          owner: TEST_OWNER,
          repo,
          head: mergeBranch,
          base: 'main',
          title: `[Merge Test] ${repo}`,
          body: 'Merge test PR',
        });

        mergePRs.push({ owner: TEST_OWNER, repo, number: pr.number });
        console.log(`Created merge PR in ${repo}: #${pr.number}`);
      }

      // Wait for GitHub to calculate mergeability
      await new Promise((resolve) => setTimeout(resolve, 3000));

      // Merge all PRs
      const mergeResults: { repo: string; success: boolean }[] = [];

      for (const pr of mergePRs) {
        const success = await mergePullRequest(pr.owner, pr.repo, pr.number, {
          method: 'squash',
          deleteBranch: true,
        });

        mergeResults.push({ repo: pr.repo, success });
        console.log(`Merged ${pr.repo}#${pr.number}: ${success}`);
      }

      // All should succeed
      expect(mergeResults.every((r) => r.success)).toBe(true);
      console.log('All PRs merged successfully!');
    });
  });
});
