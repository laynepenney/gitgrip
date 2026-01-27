/**
 * E2E tests for GitHub API integration
 *
 * These tests require:
 * 1. GITHUB_TOKEN environment variable (or `gh auth login`)
 * 2. Access to test repositories
 *
 * Run with: GITHUB_E2E=1 npx vitest run src/lib/__tests__/github.e2e.test.ts
 */

import { describe, it, expect, beforeAll, afterAll } from 'vitest';

// Skip if not running E2E tests
const runE2E = process.env.GITHUB_E2E === '1';

describe.skipIf(!runE2E)('GitHub API E2E Tests', () => {
  const TEST_OWNER = process.env.TEST_GITHUB_OWNER || 'laynepenney';
  const TEST_REPO = process.env.TEST_GITHUB_REPO || 'codi-repo-test';

  beforeAll(() => {
    if (!process.env.GITHUB_TOKEN) {
      console.log('Attempting to use gh CLI for authentication...');
    }
  });

  describe('Authentication', () => {
    it('can authenticate with GitHub', async () => {
      const { getGitHubToken } = await import('../github.js');
      const token = getGitHubToken();
      expect(token).toBeTruthy();
      expect(token.length).toBeGreaterThan(10);
    });

    it('can create Octokit instance', async () => {
      const { getOctokit } = await import('../github.js');
      const octokit = getOctokit();
      expect(octokit).toBeDefined();
      expect(octokit.pulls).toBeDefined();
    });
  });

  describe('Repository Access', () => {
    it('can get repository info', async () => {
      const { getOctokit } = await import('../github.js');
      const octokit = getOctokit();

      const { data } = await octokit.repos.get({
        owner: TEST_OWNER,
        repo: TEST_REPO,
      });

      expect(data.full_name).toBe(`${TEST_OWNER}/${TEST_REPO}`);
      expect(data.private).toBe(true);
      console.log(`Repository: ${data.full_name}, Default branch: ${data.default_branch}`);
    });

    it('can list PRs for a repository', async () => {
      const { getOctokit } = await import('../github.js');
      const octokit = getOctokit();

      const { data } = await octokit.pulls.list({
        owner: TEST_OWNER,
        repo: TEST_REPO,
        state: 'all',
        per_page: 10,
      });

      expect(Array.isArray(data)).toBe(true);
      console.log(`Found ${data.length} PRs in ${TEST_OWNER}/${TEST_REPO}`);
    });
  });

  describe('Full PR Workflow', () => {
    let testBranchName: string;
    let createdPRNumber: number | null = null;
    let testFileSha: string;

    beforeAll(() => {
      // Unique branch name for this test run
      testBranchName = `test/e2e-${Date.now()}`;
    });

    afterAll(async () => {
      // Cleanup: close PR and delete branch
      const { getOctokit } = await import('../github.js');
      const octokit = getOctokit();

      if (createdPRNumber) {
        try {
          await octokit.pulls.update({
            owner: TEST_OWNER,
            repo: TEST_REPO,
            pull_number: createdPRNumber,
            state: 'closed',
          });
          console.log(`Closed PR #${createdPRNumber}`);
        } catch (e) {
          console.log(`Failed to close PR: ${e}`);
        }
      }

      try {
        await octokit.git.deleteRef({
          owner: TEST_OWNER,
          repo: TEST_REPO,
          ref: `heads/${testBranchName}`,
        });
        console.log(`Deleted branch ${testBranchName}`);
      } catch (e) {
        console.log(`Failed to delete branch: ${e}`);
      }
    });

    it('can create a test branch', async () => {
      const { getOctokit } = await import('../github.js');
      const octokit = getOctokit();

      // Get the SHA of main branch
      const { data: mainRef } = await octokit.git.getRef({
        owner: TEST_OWNER,
        repo: TEST_REPO,
        ref: 'heads/main',
      });

      const mainSha = mainRef.object.sha;
      console.log(`Main branch SHA: ${mainSha}`);

      // Create new branch from main
      const { data: newRef } = await octokit.git.createRef({
        owner: TEST_OWNER,
        repo: TEST_REPO,
        ref: `refs/heads/${testBranchName}`,
        sha: mainSha,
      });

      expect(newRef.ref).toBe(`refs/heads/${testBranchName}`);
      console.log(`Created branch: ${testBranchName}`);
    });

    it('can create a commit on the test branch', async () => {
      const { getOctokit } = await import('../github.js');
      const octokit = getOctokit();

      // Create a test file
      const testContent = `# E2E Test File\n\nCreated at: ${new Date().toISOString()}\nBranch: ${testBranchName}\n`;

      const { data: file } = await octokit.repos.createOrUpdateFileContents({
        owner: TEST_OWNER,
        repo: TEST_REPO,
        path: `test-files/${testBranchName.replace(/\//g, '-')}.md`,
        message: `[E2E Test] Add test file for ${testBranchName}`,
        content: Buffer.from(testContent).toString('base64'),
        branch: testBranchName,
      });

      expect(file.commit).toBeDefined();
      expect(file.content?.sha).toBeDefined();
      testFileSha = file.content!.sha!;
      console.log(`Created commit: ${file.commit.sha}`);
    });

    it('can create a pull request', async () => {
      const { createPullRequest } = await import('../github.js');

      const pr = await createPullRequest(
        TEST_OWNER,
        TEST_REPO,
        testBranchName,
        'main',
        `[E2E Test] Test PR from ${testBranchName}`,
        `This PR was created by automated E2E tests.\n\nTest run: ${new Date().toISOString()}`,
        false
      );

      expect(pr.number).toBeGreaterThan(0);
      expect(pr.url).toContain(`${TEST_OWNER}/${TEST_REPO}/pull/`);
      createdPRNumber = pr.number;
      console.log(`Created PR #${pr.number}: ${pr.url}`);
    });

    it('can get pull request details', async () => {
      const { getPullRequest } = await import('../github.js');

      expect(createdPRNumber).not.toBeNull();
      const pr = await getPullRequest(TEST_OWNER, TEST_REPO, createdPRNumber!);

      expect(pr.number).toBe(createdPRNumber);
      expect(pr.state).toBe('open');
      expect(pr.merged).toBe(false);
      expect(pr.head.ref).toBe(testBranchName);
      expect(pr.base.ref).toBe('main');
      console.log(`PR state: ${pr.state}, mergeable: ${pr.mergeable}`);
    });

    it('can check PR approval status', async () => {
      const { isPullRequestApproved } = await import('../github.js');

      expect(createdPRNumber).not.toBeNull();
      const approved = await isPullRequestApproved(TEST_OWNER, TEST_REPO, createdPRNumber!);

      // New PR shouldn't be approved
      expect(approved).toBe(false);
      console.log(`PR approved: ${approved}`);
    });

    it('can get status checks', async () => {
      const { getStatusChecks, getPullRequest } = await import('../github.js');

      expect(createdPRNumber).not.toBeNull();
      const pr = await getPullRequest(TEST_OWNER, TEST_REPO, createdPRNumber!);
      const checks = await getStatusChecks(TEST_OWNER, TEST_REPO, pr.head.sha);

      // Test repo likely has no CI, so status might be pending or success (no checks = success)
      expect(['success', 'pending']).toContain(checks.state);
      console.log(`Status checks: ${checks.state}, count: ${checks.statuses.length}`);
    });

    it('can find PR by branch name', async () => {
      const { findPRByBranch } = await import('../github.js');

      const pr = await findPRByBranch(TEST_OWNER, TEST_REPO, testBranchName);

      expect(pr).not.toBeNull();
      expect(pr!.number).toBe(createdPRNumber);
      console.log(`Found PR by branch: #${pr!.number}`);
    });

    it('can get linked PR info', async () => {
      const { getLinkedPRInfo } = await import('../github.js');

      expect(createdPRNumber).not.toBeNull();
      const info = await getLinkedPRInfo(TEST_OWNER, TEST_REPO, createdPRNumber!, 'test-repo');

      expect(info.repoName).toBe('test-repo');
      expect(info.number).toBe(createdPRNumber);
      expect(info.state).toBe('open');
      expect(info.approved).toBe(false);
      expect(typeof info.checksPass).toBe('boolean');
      expect(typeof info.mergeable).toBe('boolean');
      console.log(`Linked PR info: state=${info.state}, approved=${info.approved}, checksPass=${info.checksPass}`);
    });

    it('can update PR body', async () => {
      const { updatePullRequestBody, getPullRequest } = await import('../github.js');

      expect(createdPRNumber).not.toBeNull();

      const newBody = `Updated body at ${new Date().toISOString()}\n\n<!-- codi-repo:links:test-repo#${createdPRNumber} -->`;
      await updatePullRequestBody(TEST_OWNER, TEST_REPO, createdPRNumber!, newBody);

      const pr = await getPullRequest(TEST_OWNER, TEST_REPO, createdPRNumber!);
      expect(pr.body).toContain('Updated body');
      expect(pr.body).toContain('codi-repo:links');
      console.log('PR body updated successfully');
    });

    it('can parse linked PRs from body', async () => {
      const { parseLinkedPRsFromBody, getPullRequest } = await import('../github.js');

      expect(createdPRNumber).not.toBeNull();
      const pr = await getPullRequest(TEST_OWNER, TEST_REPO, createdPRNumber!);

      const links = parseLinkedPRsFromBody(pr.body);
      expect(links.length).toBe(1);
      expect(links[0].repoName).toBe('test-repo');
      expect(links[0].number).toBe(createdPRNumber);
      console.log(`Parsed links: ${JSON.stringify(links)}`);
    });
  });

  describe('PR Merge (optional - skipped by default)', () => {
    // This test actually merges a PR - only run if explicitly enabled
    const runMergeTest = process.env.TEST_MERGE === '1';

    it.skipIf(!runMergeTest)('can merge a pull request', async () => {
      const { getOctokit, createPullRequest, mergePullRequest } = await import('../github.js');
      const octokit = getOctokit();

      const mergeBranch = `test/merge-${Date.now()}`;

      // Create branch
      const { data: mainRef } = await octokit.git.getRef({
        owner: TEST_OWNER,
        repo: TEST_REPO,
        ref: 'heads/main',
      });

      await octokit.git.createRef({
        owner: TEST_OWNER,
        repo: TEST_REPO,
        ref: `refs/heads/${mergeBranch}`,
        sha: mainRef.object.sha,
      });

      // Create commit
      await octokit.repos.createOrUpdateFileContents({
        owner: TEST_OWNER,
        repo: TEST_REPO,
        path: `merged-files/${mergeBranch.replace(/\//g, '-')}.md`,
        message: `[E2E Test] Merge test file`,
        content: Buffer.from(`Merge test at ${new Date().toISOString()}`).toString('base64'),
        branch: mergeBranch,
      });

      // Create PR
      const pr = await createPullRequest(
        TEST_OWNER,
        TEST_REPO,
        mergeBranch,
        'main',
        `[E2E Test] Merge test PR`,
        'This PR will be merged by E2E tests.',
        false
      );

      console.log(`Created PR for merge: #${pr.number}`);

      // Wait a moment for GitHub to calculate mergeability
      await new Promise((resolve) => setTimeout(resolve, 2000));

      // Merge it
      const merged = await mergePullRequest(TEST_OWNER, TEST_REPO, pr.number, {
        method: 'squash',
        deleteBranch: true,
      });

      expect(merged).toBe(true);
      console.log(`Merged PR #${pr.number}`);
    });
  });
});
