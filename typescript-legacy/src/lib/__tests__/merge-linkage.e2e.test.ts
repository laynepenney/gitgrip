/**
 * Merge Linkage E2E tests
 *
 * Tests the full cross-repo merge workflow with a manifest repo:
 * - Create PRs in child repos (repo1, repo2)
 * - Create manifest PR that links them
 * - Verify linkage is correct
 * - (Optional) Merge all PRs atomically
 *
 * Test repos:
 * - codi-repo-test-manifest (manifest/orchestrator)
 * - codi-repo-test (repo1)
 * - codi-repo-test-2 (repo2)
 *
 * Run with: GITHUB_E2E=1 npx vitest run src/lib/__tests__/merge-linkage.e2e.test.ts
 * Run with merge: GITHUB_E2E=1 TEST_MERGE=1 npx vitest run src/lib/__tests__/merge-linkage.e2e.test.ts
 */

import { describe, it, expect, beforeAll, afterAll } from 'vitest';
import type { LinkedPR } from '../../types.js';

const runE2E = process.env.GITHUB_E2E === '1';
const runMerge = process.env.TEST_MERGE === '1';

describe.skipIf(!runE2E)('Merge Linkage E2E Tests', () => {
  const TEST_OWNER = 'laynepenney';

  // All three test repos
  const MANIFEST_REPO = 'codi-repo-test-manifest';
  const CHILD_REPOS = [
    { name: 'repo1', repo: 'codi-repo-test' },
    { name: 'repo2', repo: 'codi-repo-test-2' },
  ];

  let testBranchName: string;
  let manifestPRNumber: number | null = null;
  const childPRs: { name: string; repo: string; number: number }[] = [];

  beforeAll(() => {
    testBranchName = `test/merge-linkage-${Date.now()}`;
    console.log(`\n=== Merge Linkage Test ===`);
    console.log(`Branch: ${testBranchName}`);
    console.log(`Manifest: ${MANIFEST_REPO}`);
    console.log(`Children: ${CHILD_REPOS.map((r) => r.repo).join(', ')}`);
    console.log(`Merge test: ${runMerge ? 'ENABLED' : 'disabled'}\n`);
  });

  afterAll(async () => {
    const { getOctokit } = await import('../github.js');
    const octokit = getOctokit();

    console.log('\n=== Cleanup ===');

    // Close manifest PR
    if (manifestPRNumber && !runMerge) {
      try {
        await octokit.pulls.update({
          owner: TEST_OWNER,
          repo: MANIFEST_REPO,
          pull_number: manifestPRNumber,
          state: 'closed',
        });
        console.log(`Closed manifest PR #${manifestPRNumber}`);
      } catch (e) {
        console.log(`Failed to close manifest PR: ${e}`);
      }
    }

    // Close child PRs
    for (const pr of childPRs) {
      if (!runMerge) {
        try {
          await octokit.pulls.update({
            owner: TEST_OWNER,
            repo: pr.repo,
            pull_number: pr.number,
            state: 'closed',
          });
          console.log(`Closed ${pr.repo}#${pr.number}`);
        } catch (e) {
          console.log(`Failed to close ${pr.repo}#${pr.number}: ${e}`);
        }
      }
    }

    // Delete branches from all repos
    const allRepos = [MANIFEST_REPO, ...CHILD_REPOS.map((r) => r.repo)];
    for (const repo of allRepos) {
      if (!runMerge) {
        try {
          await octokit.git.deleteRef({
            owner: TEST_OWNER,
            repo,
            ref: `heads/${testBranchName}`,
          });
          console.log(`Deleted branch from ${repo}`);
        } catch {
          // Branch may not exist or already deleted
        }
      }
    }
  });

  describe('Setup: Create branches in all repos', () => {
    it('creates branch in manifest repo', async () => {
      const { getOctokit } = await import('../github.js');
      const octokit = getOctokit();

      const { data: mainRef } = await octokit.git.getRef({
        owner: TEST_OWNER,
        repo: MANIFEST_REPO,
        ref: 'heads/main',
      });

      await octokit.git.createRef({
        owner: TEST_OWNER,
        repo: MANIFEST_REPO,
        ref: `refs/heads/${testBranchName}`,
        sha: mainRef.object.sha,
      });

      console.log(`Created branch in ${MANIFEST_REPO}`);
    });

    it('creates branch in all child repos', async () => {
      const { getOctokit } = await import('../github.js');
      const octokit = getOctokit();

      for (const { repo } of CHILD_REPOS) {
        const { data: mainRef } = await octokit.git.getRef({
          owner: TEST_OWNER,
          repo,
          ref: 'heads/main',
        });

        await octokit.git.createRef({
          owner: TEST_OWNER,
          repo,
          ref: `refs/heads/${testBranchName}`,
          sha: mainRef.object.sha,
        });

        console.log(`Created branch in ${repo}`);
      }
    });
  });

  describe('Setup: Create commits in child repos', () => {
    it('creates commit in each child repo', async () => {
      const { getOctokit } = await import('../github.js');
      const octokit = getOctokit();

      for (const { name, repo } of CHILD_REPOS) {
        const content = `# Merge Linkage Test\n\nRepo: ${name}\nBranch: ${testBranchName}\nTime: ${new Date().toISOString()}\n`;

        const { data: file } = await octokit.repos.createOrUpdateFileContents({
          owner: TEST_OWNER,
          repo,
          path: `merge-linkage-test/${testBranchName.replace(/\//g, '-')}.md`,
          message: `[Merge Linkage Test] Add test file in ${name}`,
          content: Buffer.from(content).toString('base64'),
          branch: testBranchName,
        });

        console.log(`Created commit in ${repo}: ${file.commit.sha?.slice(0, 7)}`);
      }
    });
  });

  describe('Create linked PRs in child repos', () => {
    it('creates PR in each child repo', async () => {
      const { createPullRequest } = await import('../github.js');

      for (const { name, repo } of CHILD_REPOS) {
        const pr = await createPullRequest(
          TEST_OWNER,
          repo,
          testBranchName,
          'main',
          `[cross-repo] Merge linkage test - ${name}`,
          `Part of merge linkage test.\n\nThis PR will be linked to a manifest PR.`,
          false
        );

        childPRs.push({ name, repo, number: pr.number });
        console.log(`Created child PR: ${repo}#${pr.number}`);
      }

      expect(childPRs.length).toBe(CHILD_REPOS.length);
    });
  });

  describe('Create manifest PR with linkage', () => {
    it('creates commit in manifest repo with version bump', async () => {
      const { getOctokit } = await import('../github.js');
      const octokit = getOctokit();

      // Create a commit that represents the "release" or "version update"
      const content = `# Merge Linkage Test Release\n\nBranch: ${testBranchName}\nTime: ${new Date().toISOString()}\n\nLinked PRs:\n${childPRs.map((pr) => `- ${pr.repo}#${pr.number}`).join('\n')}\n`;

      await octokit.repos.createOrUpdateFileContents({
        owner: TEST_OWNER,
        repo: MANIFEST_REPO,
        path: `releases/${testBranchName.replace(/\//g, '-')}.md`,
        message: `[Merge Linkage Test] Version bump`,
        content: Buffer.from(content).toString('base64'),
        branch: testBranchName,
      });

      console.log('Created version commit in manifest repo');
    });

    it('creates manifest PR with linked PRs in body', async () => {
      const { createPullRequest, generateManifestPRBody, getLinkedPRInfo } = await import('../github.js');

      // Get linked PR info for all child PRs
      const linkedPRs: LinkedPR[] = [];
      for (const { name, repo, number } of childPRs) {
        const info = await getLinkedPRInfo(TEST_OWNER, repo, number, name);
        linkedPRs.push(info);
      }

      // Generate manifest PR body with links
      const body = generateManifestPRBody(
        'Merge Linkage Test',
        linkedPRs,
        'This is a test of the cross-repo merge linkage system.'
      );

      // Create manifest PR
      const pr = await createPullRequest(
        TEST_OWNER,
        MANIFEST_REPO,
        testBranchName,
        'main',
        `[cross-repo] Merge Linkage Test`,
        body,
        false
      );

      manifestPRNumber = pr.number;
      console.log(`Created manifest PR: ${MANIFEST_REPO}#${manifestPRNumber}`);
      console.log(`URL: ${pr.url}`);
    });

    it('manifest PR body contains all linked PRs', async () => {
      const { getPullRequest, parseLinkedPRsFromBody } = await import('../github.js');

      expect(manifestPRNumber).not.toBeNull();

      const pr = await getPullRequest(TEST_OWNER, MANIFEST_REPO, manifestPRNumber!);
      const links = parseLinkedPRsFromBody(pr.body);

      expect(links.length).toBe(CHILD_REPOS.length);

      for (const { name } of CHILD_REPOS) {
        const found = links.find((l) => l.repoName === name);
        expect(found).toBeDefined();
      }

      console.log('Verified linkage in manifest PR body');
      console.log('Links:', links);
    });
  });

  describe('Update child PRs with manifest reference', () => {
    it('updates each child PR to reference manifest PR', async () => {
      const { getOctokit, getPullRequest } = await import('../github.js');
      const octokit = getOctokit();

      expect(manifestPRNumber).not.toBeNull();

      for (const { name, repo, number } of childPRs) {
        const pr = await getPullRequest(TEST_OWNER, repo, number);

        const newBody = `Part of: ${TEST_OWNER}/${MANIFEST_REPO}#${manifestPRNumber}\n\n${pr.body}`;

        await octokit.pulls.update({
          owner: TEST_OWNER,
          repo,
          pull_number: number,
          body: newBody,
        });

        console.log(`Updated ${repo}#${number} to reference manifest PR`);
      }
    });

    it('child PRs reference manifest PR', async () => {
      const { getPullRequest } = await import('../github.js');

      for (const { repo, number } of childPRs) {
        const pr = await getPullRequest(TEST_OWNER, repo, number);
        expect(pr.body).toContain(`${MANIFEST_REPO}#${manifestPRNumber}`);
      }

      console.log('Verified all child PRs reference manifest');
    });
  });

  describe('Verify cross-repo status', () => {
    it('can get status of all linked PRs', async () => {
      const { getLinkedPRInfo } = await import('../github.js');

      console.log('\n=== Cross-Repo Status ===');

      // Check manifest PR
      const manifestInfo = await getLinkedPRInfo(TEST_OWNER, MANIFEST_REPO, manifestPRNumber!, 'manifest');
      console.log(`Manifest: #${manifestInfo.number} - ${manifestInfo.state}`);

      // Check child PRs
      for (const { name, repo, number } of childPRs) {
        const info = await getLinkedPRInfo(TEST_OWNER, repo, number, name);
        console.log(`  ${name}: #${info.number} - ${info.state}, approved=${info.approved}, mergeable=${info.mergeable}`);
      }
    });

    it('all PRs are open', async () => {
      const { getLinkedPRInfo } = await import('../github.js');

      const manifestInfo = await getLinkedPRInfo(TEST_OWNER, MANIFEST_REPO, manifestPRNumber!, 'manifest');
      expect(manifestInfo.state).toBe('open');

      for (const { name, repo, number } of childPRs) {
        const info = await getLinkedPRInfo(TEST_OWNER, repo, number, name);
        expect(info.state).toBe('open');
      }
    });
  });

  describe.skipIf(!runMerge)('Atomic merge of all linked PRs', () => {
    it('waits for GitHub to calculate mergeability', async () => {
      // GitHub needs time to calculate mergeability
      console.log('Waiting for mergeability calculation...');
      await new Promise((resolve) => setTimeout(resolve, 3000));
    });

    it('merges all child PRs first', async () => {
      const { mergePullRequest, getLinkedPRInfo } = await import('../github.js');

      console.log('\n=== Merging Child PRs ===');

      for (const { name, repo, number } of childPRs) {
        // Check if mergeable
        const info = await getLinkedPRInfo(TEST_OWNER, repo, number, name);
        console.log(`${name}: mergeable=${info.mergeable}`);

        const merged = await mergePullRequest(TEST_OWNER, repo, number, {
          method: 'squash',
          deleteBranch: true,
        });

        expect(merged).toBe(true);
        console.log(`Merged ${repo}#${number}`);
      }
    }, 30000); // 30s timeout for merging multiple PRs

    it('merges manifest PR last', async () => {
      const { mergePullRequest } = await import('../github.js');

      expect(manifestPRNumber).not.toBeNull();

      // Wait a bit for GitHub to update
      await new Promise((resolve) => setTimeout(resolve, 1000));

      const merged = await mergePullRequest(TEST_OWNER, MANIFEST_REPO, manifestPRNumber!, {
        method: 'squash',
        deleteBranch: true,
      });

      expect(merged).toBe(true);
      console.log(`Merged manifest PR #${manifestPRNumber}`);
    });

    it('all PRs are now merged', async () => {
      const { getLinkedPRInfo } = await import('../github.js');

      const manifestInfo = await getLinkedPRInfo(TEST_OWNER, MANIFEST_REPO, manifestPRNumber!, 'manifest');
      expect(manifestInfo.state).toBe('merged');

      for (const { name, repo, number } of childPRs) {
        const info = await getLinkedPRInfo(TEST_OWNER, repo, number, name);
        expect(info.state).toBe('merged');
      }

      console.log('\n=== All PRs Merged Successfully! ===');
    });
  });
});
