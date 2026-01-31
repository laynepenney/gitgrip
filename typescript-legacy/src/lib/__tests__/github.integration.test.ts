import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { Octokit } from '@octokit/rest';

// Mock Octokit before importing the module
vi.mock('@octokit/rest', () => {
  const mockOctokit = {
    pulls: {
      create: vi.fn(),
      get: vi.fn(),
      list: vi.fn(),
      listReviews: vi.fn(),
      update: vi.fn(),
      merge: vi.fn(),
    },
    repos: {
      getCombinedStatusForRef: vi.fn(),
    },
    git: {
      deleteRef: vi.fn(),
    },
  };
  return {
    Octokit: vi.fn(() => mockOctokit),
  };
});

// Mock the token retrieval
vi.mock('child_process', () => ({
  execSync: vi.fn(() => 'mock-github-token'),
}));

// Import after mocks are set up
import {
  createPullRequest,
  getPullRequest,
  isPullRequestApproved,
  getStatusChecks,
  mergePullRequest,
  findPRByBranch,
  getLinkedPRInfo,
} from '../github.js';

describe('GitHub API Integration', () => {
  let mockOctokit: any;

  beforeEach(() => {
    // Get the mocked instance
    mockOctokit = new Octokit();
    vi.clearAllMocks();
  });

  describe('createPullRequest', () => {
    it('creates a PR and returns number and URL', async () => {
      mockOctokit.pulls.create.mockResolvedValue({
        data: {
          number: 42,
          html_url: 'https://github.com/owner/repo/pull/42',
        },
      });

      const result = await createPullRequest(
        'owner',
        'repo',
        'feature-branch',
        'main',
        'Add feature',
        'Description here',
        false
      );

      expect(result).toEqual({
        number: 42,
        url: 'https://github.com/owner/repo/pull/42',
      });

      expect(mockOctokit.pulls.create).toHaveBeenCalledWith({
        owner: 'owner',
        repo: 'repo',
        head: 'feature-branch',
        base: 'main',
        title: 'Add feature',
        body: 'Description here',
        draft: false,
      });
    });

    it('creates a draft PR when requested', async () => {
      mockOctokit.pulls.create.mockResolvedValue({
        data: { number: 1, html_url: 'https://github.com/o/r/pull/1' },
      });

      await createPullRequest('o', 'r', 'branch', 'main', 'Title', 'Body', true);

      expect(mockOctokit.pulls.create).toHaveBeenCalledWith(
        expect.objectContaining({ draft: true })
      );
    });
  });

  describe('getPullRequest', () => {
    it('returns PR details', async () => {
      mockOctokit.pulls.get.mockResolvedValue({
        data: {
          number: 42,
          html_url: 'https://github.com/owner/repo/pull/42',
          title: 'My PR',
          body: 'Description',
          state: 'open',
          merged: false,
          mergeable: true,
          head: { ref: 'feature', sha: 'abc123' },
          base: { ref: 'main' },
        },
      });

      const result = await getPullRequest('owner', 'repo', 42);

      expect(result).toEqual({
        number: 42,
        url: 'https://github.com/owner/repo/pull/42',
        title: 'My PR',
        body: 'Description',
        state: 'open',
        merged: false,
        mergeable: true,
        head: { ref: 'feature', sha: 'abc123' },
        base: { ref: 'main' },
      });
    });
  });

  describe('isPullRequestApproved', () => {
    it('returns true when PR has approval and no changes requested', async () => {
      mockOctokit.pulls.listReviews.mockResolvedValue({
        data: [
          { state: 'APPROVED', user: { login: 'reviewer1' } },
          { state: 'COMMENTED', user: { login: 'reviewer2' } },
        ],
      });

      const result = await isPullRequestApproved('owner', 'repo', 42);
      expect(result).toBe(true);
    });

    it('returns false when changes are requested', async () => {
      mockOctokit.pulls.listReviews.mockResolvedValue({
        data: [
          { state: 'APPROVED', user: { login: 'reviewer1' } },
          { state: 'CHANGES_REQUESTED', user: { login: 'reviewer2' } },
        ],
      });

      const result = await isPullRequestApproved('owner', 'repo', 42);
      expect(result).toBe(false);
    });

    it('returns false when no approvals', async () => {
      mockOctokit.pulls.listReviews.mockResolvedValue({
        data: [{ state: 'COMMENTED', user: { login: 'reviewer1' } }],
      });

      const result = await isPullRequestApproved('owner', 'repo', 42);
      expect(result).toBe(false);
    });
  });

  describe('getStatusChecks', () => {
    it('returns combined status', async () => {
      mockOctokit.repos.getCombinedStatusForRef.mockResolvedValue({
        data: {
          state: 'success',
          statuses: [
            { context: 'ci/test', state: 'success' },
            { context: 'ci/lint', state: 'success' },
          ],
        },
      });

      const result = await getStatusChecks('owner', 'repo', 'abc123');

      expect(result).toEqual({
        state: 'success',
        statuses: [
          { context: 'ci/test', state: 'success' },
          { context: 'ci/lint', state: 'success' },
        ],
      });
    });

    it('returns pending when checks are running', async () => {
      mockOctokit.repos.getCombinedStatusForRef.mockResolvedValue({
        data: {
          state: 'pending',
          statuses: [{ context: 'ci/test', state: 'pending' }],
        },
      });

      const result = await getStatusChecks('owner', 'repo', 'abc123');
      expect(result.state).toBe('pending');
    });
  });

  describe('mergePullRequest', () => {
    it('merges PR successfully', async () => {
      mockOctokit.pulls.merge.mockResolvedValue({ data: {} });

      const result = await mergePullRequest('owner', 'repo', 42);
      expect(result).toBe(true);

      expect(mockOctokit.pulls.merge).toHaveBeenCalledWith({
        owner: 'owner',
        repo: 'repo',
        pull_number: 42,
        merge_method: 'merge',
      });
    });

    it('uses squash merge when specified', async () => {
      mockOctokit.pulls.merge.mockResolvedValue({ data: {} });

      await mergePullRequest('owner', 'repo', 42, { method: 'squash' });

      expect(mockOctokit.pulls.merge).toHaveBeenCalledWith(
        expect.objectContaining({ merge_method: 'squash' })
      );
    });

    it('deletes branch after merge when requested', async () => {
      mockOctokit.pulls.merge.mockResolvedValue({ data: {} });
      mockOctokit.pulls.get.mockResolvedValue({
        data: {
          number: 42,
          html_url: 'url',
          title: 'T',
          body: '',
          state: 'closed',
          merged: true,
          mergeable: null,
          head: { ref: 'feature', sha: 'abc' },
          base: { ref: 'main' },
        },
      });
      mockOctokit.git.deleteRef.mockResolvedValue({});

      await mergePullRequest('owner', 'repo', 42, { deleteBranch: true });

      expect(mockOctokit.git.deleteRef).toHaveBeenCalledWith({
        owner: 'owner',
        repo: 'repo',
        ref: 'heads/feature',
      });
    });

    it('returns false on merge failure', async () => {
      mockOctokit.pulls.merge.mockRejectedValue(new Error('Merge conflict'));

      const result = await mergePullRequest('owner', 'repo', 42);
      expect(result).toBe(false);
    });
  });

  describe('findPRByBranch', () => {
    it('returns PR if found', async () => {
      mockOctokit.pulls.list.mockResolvedValue({
        data: [
          { number: 42, html_url: 'https://github.com/owner/repo/pull/42' },
        ],
      });

      const result = await findPRByBranch('owner', 'repo', 'feature');

      expect(result).toEqual({
        number: 42,
        url: 'https://github.com/owner/repo/pull/42',
      });

      expect(mockOctokit.pulls.list).toHaveBeenCalledWith({
        owner: 'owner',
        repo: 'repo',
        head: 'owner:feature',
        state: 'open',
      });
    });

    it('returns null if no PR found', async () => {
      mockOctokit.pulls.list.mockResolvedValue({ data: [] });

      const result = await findPRByBranch('owner', 'repo', 'feature');
      expect(result).toBeNull();
    });
  });

  describe('getLinkedPRInfo', () => {
    it('returns full PR info with all status fields', async () => {
      mockOctokit.pulls.get.mockResolvedValue({
        data: {
          number: 42,
          html_url: 'https://github.com/owner/repo/pull/42',
          title: 'Title',
          body: 'Body',
          state: 'open',
          merged: false,
          mergeable: true,
          head: { ref: 'feature', sha: 'abc123' },
          base: { ref: 'main' },
        },
      });

      mockOctokit.pulls.listReviews.mockResolvedValue({
        data: [{ state: 'APPROVED', user: { login: 'reviewer' } }],
      });

      mockOctokit.repos.getCombinedStatusForRef.mockResolvedValue({
        data: { state: 'success', statuses: [] },
      });

      const result = await getLinkedPRInfo('owner', 'repo', 42, 'my-repo');

      expect(result).toEqual({
        repoName: 'my-repo',
        owner: 'owner',
        repo: 'repo',
        number: 42,
        url: 'https://github.com/owner/repo/pull/42',
        state: 'open',
        approved: true,
        checksPass: true,
        mergeable: true,
        platformType: 'github',
      });
    });

    it('detects merged state', async () => {
      mockOctokit.pulls.get.mockResolvedValue({
        data: {
          number: 42,
          html_url: 'url',
          title: 'T',
          body: '',
          state: 'closed',
          merged: true,
          mergeable: null,
          head: { ref: 'f', sha: 'abc' },
          base: { ref: 'main' },
        },
      });

      mockOctokit.pulls.listReviews.mockResolvedValue({ data: [] });
      mockOctokit.repos.getCombinedStatusForRef.mockResolvedValue({
        data: { state: 'success', statuses: [] },
      });

      const result = await getLinkedPRInfo('owner', 'repo', 42, 'test');
      expect(result.state).toBe('merged');
    });
  });
});
