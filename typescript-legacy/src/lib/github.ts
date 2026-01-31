/**
 * GitHub API operations
 *
 * This module provides backward-compatible exports that delegate to the
 * platform abstraction. For new code, prefer using the platform module directly.
 *
 * @deprecated Use the platform abstraction (./platform/index.js) for multi-platform support
 */

import { getGitHubPlatform, GitHubPlatform } from './platform/github.js';
import { Octokit } from '@octokit/rest';
import { execSync } from 'child_process';
import type { LinkedPR, RepoInfo, PRCreateOptions, PRMergeOptions } from '../types.js';
import type { PRReview, StatusCheckResult } from './platform/types.js';

// Re-export the GitHub platform for backward compatibility
export { getGitHubPlatform };

// Singleton Octokit instance for backward compatibility with tests
let octokitInstance: Octokit | null = null;

/**
 * Get or create Octokit instance (for backward compatibility with tests)
 * @deprecated Use getPlatformAdapter('github') instead
 */
export function getOctokit(): Octokit {
  if (!octokitInstance) {
    const token = getGitHubToken();
    octokitInstance = new Octokit({ auth: token });
  }
  return octokitInstance;
}

/**
 * Get GitHub token from environment or gh CLI
 * @deprecated Use getPlatformAdapter('github').getToken() instead
 */
export function getGitHubToken(): string {
  // Try environment variable first
  if (process.env.GITHUB_TOKEN) {
    return process.env.GITHUB_TOKEN;
  }

  // Try gh CLI
  try {
    const token = execSync('gh auth token', { encoding: 'utf-8' }).trim();
    if (token) {
      return token;
    }
  } catch {
    // gh CLI not available or not authenticated
  }

  throw new Error(
    'GitHub token not found. Set GITHUB_TOKEN environment variable or run "gh auth login"'
  );
}

/**
 * Create a pull request
 * @deprecated Use getPlatformAdapter(repoInfo.platformType).createPullRequest() instead
 */
export async function createPullRequest(
  owner: string,
  repo: string,
  head: string,
  base: string,
  title: string,
  body: string,
  draft = false
): Promise<{ number: number; url: string }> {
  const platform = getGitHubPlatform();
  return platform.createPullRequest(owner, repo, head, base, title, body, draft);
}

/**
 * Update a pull request body
 * @deprecated Use getPlatformAdapter(repoInfo.platformType).updatePullRequestBody() instead
 */
export async function updatePullRequestBody(
  owner: string,
  repo: string,
  pullNumber: number,
  body: string
): Promise<void> {
  const platform = getGitHubPlatform();
  return platform.updatePullRequestBody(owner, repo, pullNumber, body);
}

/**
 * Get pull request details
 * @deprecated Use getPlatformAdapter(repoInfo.platformType).getPullRequest() instead
 */
export async function getPullRequest(
  owner: string,
  repo: string,
  pullNumber: number
): Promise<{
  number: number;
  url: string;
  title: string;
  body: string;
  state: 'open' | 'closed';
  merged: boolean;
  mergeable: boolean | null;
  head: { ref: string; sha: string };
  base: { ref: string };
}> {
  const platform = getGitHubPlatform();
  const pr = await platform.getPullRequest(owner, repo, pullNumber);

  // Map the platform state back to the original API's expected type
  // (The original API doesn't include 'merged' as a state - merged is determined by the merged field)
  const state: 'open' | 'closed' = pr.merged ? 'closed' : pr.state === 'merged' ? 'closed' : pr.state;

  return {
    ...pr,
    state,
  };
}

/**
 * Get reviews for a pull request
 * @deprecated Use getPlatformAdapter(repoInfo.platformType).getPullRequestReviews() instead
 */
export async function getPullRequestReviews(
  owner: string,
  repo: string,
  pullNumber: number
): Promise<{ state: string; user: string }[]> {
  const platform = getGitHubPlatform();
  return platform.getPullRequestReviews(owner, repo, pullNumber);
}

/**
 * Check if a PR is approved
 * @deprecated Use getPlatformAdapter(repoInfo.platformType).isPullRequestApproved() instead
 */
export async function isPullRequestApproved(
  owner: string,
  repo: string,
  pullNumber: number
): Promise<boolean> {
  const platform = getGitHubPlatform();
  return platform.isPullRequestApproved(owner, repo, pullNumber);
}

/**
 * Get combined status checks for a PR
 * @deprecated Use getPlatformAdapter(repoInfo.platformType).getStatusChecks() instead
 */
export async function getStatusChecks(
  owner: string,
  repo: string,
  ref: string
): Promise<{ state: 'success' | 'failure' | 'pending'; statuses: { context: string; state: string }[] }> {
  const platform = getGitHubPlatform();
  return platform.getStatusChecks(owner, repo, ref);
}

/**
 * Merge a pull request
 * @deprecated Use getPlatformAdapter(repoInfo.platformType).mergePullRequest() instead
 */
export async function mergePullRequest(
  owner: string,
  repo: string,
  pullNumber: number,
  options: PRMergeOptions = {}
): Promise<boolean> {
  const platform = getGitHubPlatform();
  return platform.mergePullRequest(owner, repo, pullNumber, options);
}

/**
 * Get full linked PR information
 * @deprecated Use linker.getLinkedPRInfo() with RepoInfo instead
 */
export async function getLinkedPRInfo(
  owner: string,
  repo: string,
  pullNumber: number,
  repoName: string
): Promise<LinkedPR> {
  const platform = getGitHubPlatform();
  const pr = await platform.getPullRequest(owner, repo, pullNumber);
  const approved = await platform.isPullRequestApproved(owner, repo, pullNumber);
  const checks = await platform.getStatusChecks(owner, repo, pr.head.sha);

  let state: 'open' | 'closed' | 'merged';
  if (pr.merged) {
    state = 'merged';
  } else {
    state = pr.state;
  }

  return {
    repoName,
    owner,
    repo,
    number: pr.number,
    url: pr.url,
    state,
    approved,
    checksPass: checks.state === 'success',
    mergeable: pr.mergeable ?? false,
    platformType: 'github',
  };
}

/**
 * Find PRs with a specific branch name
 * @deprecated Use getPlatformAdapter(repoInfo.platformType).findPRByBranch() instead
 */
export async function findPRByBranch(
  owner: string,
  repo: string,
  branch: string
): Promise<{ number: number; url: string } | null> {
  const platform = getGitHubPlatform();
  return platform.findPRByBranch(owner, repo, branch);
}

/**
 * Create PRs for all repos with changes
 * @deprecated Use the new multi-platform PR creation flow
 */
export async function createLinkedPRs(
  repos: RepoInfo[],
  branchName: string,
  options: PRCreateOptions,
  manifestPRNumber?: number
): Promise<LinkedPR[]> {
  const platform = getGitHubPlatform();
  const linkedPRs: LinkedPR[] = [];

  for (const repo of repos) {
    // Check if PR already exists
    const existing = await platform.findPRByBranch(repo.owner, repo.repo, branchName);
    if (existing) {
      const info = await getLinkedPRInfo(repo.owner, repo.repo, existing.number, repo.name);
      linkedPRs.push(info);
      continue;
    }

    // Create title with manifest reference if available
    const title = manifestPRNumber
      ? `[manifest#${manifestPRNumber}] ${options.title}`
      : options.title;

    // Create body with cross-reference
    let body = options.body ?? '';
    if (manifestPRNumber) {
      body = `Part of manifest PR #${manifestPRNumber}\n\n${body}`;
    }

    const pr = await platform.createPullRequest(
      repo.owner,
      repo.repo,
      branchName,
      options.base ?? repo.default_branch,
      title,
      body,
      options.draft
    );

    const info = await getLinkedPRInfo(repo.owner, repo.repo, pr.number, repo.name);
    linkedPRs.push(info);
  }

  return linkedPRs;
}

/**
 * Generate manifest PR body with linked PR table
 * @deprecated Use linker.generateManifestPRBody() instead
 */
export function generateManifestPRBody(
  title: string,
  linkedPRs: LinkedPR[],
  additionalBody?: string
): string {
  const prTable = linkedPRs
    .map((pr) => {
      const statusIcon = pr.state === 'merged' ? ':white_check_mark:' : pr.state === 'open' ? ':hourglass:' : ':x:';
      const approvalIcon = pr.approved ? ':white_check_mark:' : ':hourglass:';
      const checksIcon = pr.checksPass ? ':white_check_mark:' : ':hourglass:';
      return `| ${pr.repoName} | [#${pr.number}](${pr.url}) | ${statusIcon} ${pr.state} | ${approvalIcon} | ${checksIcon} |`;
    })
    .join('\n');

  const prLinks = linkedPRs.map((pr) => `${pr.repoName}#${pr.number}`).join(',');

  return `## Cross-Repository PR

${additionalBody ?? ''}

### Linked Pull Requests

| Repository | PR | Status | Approved | Checks |
|------------|-----|--------|----------|--------|
${prTable}

**Merge Policy:** All-or-nothing - all linked PRs must be approved before merge.

---
<!-- codi-repo:links:${prLinks} -->
`;
}

/**
 * Parse linked PRs from manifest PR body
 * @deprecated Use linker.parseLinkedPRsFromBody() instead
 */
export function parseLinkedPRsFromBody(body: string): { repoName: string; number: number }[] {
  const match = body.match(/<!-- codi-repo:links:(.+?) -->/);
  if (!match) {
    return [];
  }

  const links = match[1].split(',');
  return links.map((link) => {
    const [repoName, numStr] = link.split('#');
    return { repoName, number: parseInt(numStr, 10) };
  });
}
