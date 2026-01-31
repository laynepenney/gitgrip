/**
 * GitHub hosting platform adapter
 */
import { Octokit } from '@octokit/rest';
import { execSync } from 'child_process';
import { withRetry } from '../retry.js';
import type {
  HostingPlatform,
  PlatformType,
  PlatformConfig,
  ParsedRepoInfo,
  PullRequest,
  PRCreateResult,
  PRMergeOptions,
  PRReview,
  StatusCheckResult,
  AllowedMergeMethods,
} from './types.js';

/**
 * GitHub platform adapter implementing the HostingPlatform interface
 */
export class GitHubPlatform implements HostingPlatform {
  readonly type: PlatformType = 'github';

  private octokit: Octokit | null = null;
  private config: PlatformConfig;

  constructor(config?: PlatformConfig) {
    this.config = config ?? { type: 'github' };
  }

  /**
   * Get GitHub token from environment or gh CLI
   */
  async getToken(): Promise<string> {
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
   * Get or create Octokit instance
   */
  private async getOctokit(): Promise<Octokit> {
    if (!this.octokit) {
      const token = await this.getToken();
      const options: { auth: string; baseUrl?: string } = { auth: token };

      // Support GitHub Enterprise
      if (this.config.baseUrl) {
        options.baseUrl = `${this.config.baseUrl}/api/v3`;
      }

      this.octokit = new Octokit(options);
    }
    return this.octokit;
  }

  /**
   * Create a pull request
   */
  async createPullRequest(
    owner: string,
    repo: string,
    head: string,
    base: string,
    title: string,
    body = '',
    draft = false
  ): Promise<PRCreateResult> {
    const octokit = await this.getOctokit();
    const response = await withRetry(() =>
      octokit.pulls.create({
        owner,
        repo,
        head,
        base,
        title,
        body,
        draft,
      })
    );

    return {
      number: response.data.number,
      url: response.data.html_url,
    };
  }

  /**
   * Get pull request details
   */
  async getPullRequest(
    owner: string,
    repo: string,
    pullNumber: number
  ): Promise<PullRequest> {
    const octokit = await this.getOctokit();
    const response = await withRetry(() =>
      octokit.pulls.get({
        owner,
        repo,
        pull_number: pullNumber,
      })
    );

    return {
      number: response.data.number,
      url: response.data.html_url,
      title: response.data.title,
      body: response.data.body ?? '',
      state: response.data.state as 'open' | 'closed',
      merged: response.data.merged,
      mergeable: response.data.mergeable,
      head: {
        ref: response.data.head.ref,
        sha: response.data.head.sha,
      },
      base: {
        ref: response.data.base.ref,
      },
    };
  }

  /**
   * Update pull request body
   */
  async updatePullRequestBody(
    owner: string,
    repo: string,
    pullNumber: number,
    body: string
  ): Promise<void> {
    const octokit = await this.getOctokit();
    await withRetry(() =>
      octokit.pulls.update({
        owner,
        repo,
        pull_number: pullNumber,
        body,
      })
    );
  }

  /**
   * Merge a pull request
   */
  async mergePullRequest(
    owner: string,
    repo: string,
    pullNumber: number,
    options: PRMergeOptions = {}
  ): Promise<boolean> {
    const octokit = await this.getOctokit();
    const mergeMethod = options.method ?? 'merge';

    try {
      await withRetry(() =>
        octokit.pulls.merge({
          owner,
          repo,
          pull_number: pullNumber,
          merge_method: mergeMethod,
        })
      );

      // Delete branch if requested
      if (options.deleteBranch) {
        const pr = await this.getPullRequest(owner, repo, pullNumber);
        try {
          await withRetry(() =>
            octokit.git.deleteRef({
              owner,
              repo,
              ref: `heads/${pr.head.ref}`,
            })
          );
        } catch {
          // Branch deletion failure is not critical
        }
      }

      return true;
    } catch {
      return false;
    }
  }

  /**
   * Find PR by branch name
   */
  async findPRByBranch(
    owner: string,
    repo: string,
    branch: string
  ): Promise<PRCreateResult | null> {
    const octokit = await this.getOctokit();
    const response = await withRetry(() =>
      octokit.pulls.list({
        owner,
        repo,
        head: `${owner}:${branch}`,
        state: 'open',
      })
    );

    if (response.data.length > 0) {
      return {
        number: response.data[0].number,
        url: response.data[0].html_url,
      };
    }
    return null;
  }

  /**
   * Check if PR is approved
   */
  async isPullRequestApproved(
    owner: string,
    repo: string,
    pullNumber: number
  ): Promise<boolean> {
    const reviews = await this.getPullRequestReviews(owner, repo, pullNumber);
    // Consider approved if at least one APPROVED review and no CHANGES_REQUESTED
    const hasApproval = reviews.some((r) => r.state === 'APPROVED');
    const hasChangesRequested = reviews.some((r) => r.state === 'CHANGES_REQUESTED');
    return hasApproval && !hasChangesRequested;
  }

  /**
   * Get PR reviews
   */
  async getPullRequestReviews(
    owner: string,
    repo: string,
    pullNumber: number
  ): Promise<PRReview[]> {
    const octokit = await this.getOctokit();
    const response = await withRetry(() =>
      octokit.pulls.listReviews({
        owner,
        repo,
        pull_number: pullNumber,
      })
    );

    return response.data.map((review) => ({
      state: review.state,
      user: review.user?.login ?? 'unknown',
    }));
  }

  /**
   * Get status checks for a commit
   * Combines both legacy status API and modern Check Runs API (GitHub Actions)
   */
  async getStatusChecks(
    owner: string,
    repo: string,
    ref: string
  ): Promise<StatusCheckResult> {
    const octokit = await this.getOctokit();

    // Get legacy status checks
    const statusResponse = await withRetry(() =>
      octokit.repos.getCombinedStatusForRef({
        owner,
        repo,
        ref,
      })
    );

    // Get modern check runs (GitHub Actions)
    let checkRuns: { name: string; conclusion: string | null; status: string }[] = [];
    try {
      const checksResponse = await withRetry(() =>
        octokit.checks.listForRef({
          owner,
          repo,
          ref,
        })
      );
      checkRuns = checksResponse.data.check_runs.map((run) => ({
        name: run.name,
        conclusion: run.conclusion,
        status: run.status,
      }));
    } catch {
      // Check runs API might not be available, ignore error
    }

    // Combine statuses from both APIs
    const statuses = statusResponse.data.statuses.map((s) => ({
      context: s.context,
      state: s.state,
    }));

    // Add check runs to statuses
    for (const run of checkRuns) {
      let state: string;
      if (run.status !== 'completed') {
        state = 'pending';
      } else if (run.conclusion === 'success') {
        state = 'success';
      } else if (run.conclusion === 'skipped') {
        state = 'skipped';
      } else if (run.conclusion === 'failure' || run.conclusion === 'timed_out' || run.conclusion === 'cancelled') {
        state = 'failure';
      } else {
        state = 'pending';
      }
      statuses.push({ context: run.name, state });
    }

    // Determine overall state
    // If there are no checks at all, consider it success (no checks required)
    if (statuses.length === 0) {
      return { state: 'success', statuses: [] };
    }

    // If any check failed, overall is failure
    if (statuses.some((s) => s.state === 'failure')) {
      return { state: 'failure', statuses };
    }

    // If any check is pending, overall is pending
    if (statuses.some((s) => s.state === 'pending')) {
      return { state: 'pending', statuses };
    }

    // All checks passed (including skipped)
    return { state: 'success', statuses };
  }

  /**
   * Get allowed merge methods for a repository
   */
  async getAllowedMergeMethods(
    owner: string,
    repo: string
  ): Promise<AllowedMergeMethods> {
    const octokit = await this.getOctokit();
    const response = await withRetry(() => octokit.repos.get({ owner, repo }));

    return {
      merge: response.data.allow_merge_commit ?? true,
      squash: response.data.allow_squash_merge ?? true,
      rebase: response.data.allow_rebase_merge ?? true,
    };
  }

  /**
   * Get the diff for a pull request
   */
  async getPullRequestDiff(
    owner: string,
    repo: string,
    pullNumber: number
  ): Promise<string> {
    const octokit = await this.getOctokit();
    const response = await withRetry(() =>
      octokit.pulls.get({
        owner,
        repo,
        pull_number: pullNumber,
        mediaType: {
          format: 'diff',
        },
      })
    );
    // The response is a string when format is 'diff'
    return response.data as unknown as string;
  }

  /**
   * Parse GitHub URL to extract owner/repo
   */
  parseRepoUrl(url: string): ParsedRepoInfo | null {
    // SSH format: git@github.com:owner/repo.git
    const sshMatch = url.match(/git@github\.com:([^/]+)\/(.+?)(?:\.git)?$/);
    if (sshMatch) {
      return { owner: sshMatch[1], repo: sshMatch[2] };
    }

    // HTTPS format: https://github.com/owner/repo.git
    const httpsMatch = url.match(/https?:\/\/github\.com\/([^/]+)\/(.+?)(?:\.git)?$/);
    if (httpsMatch) {
      return { owner: httpsMatch[1], repo: httpsMatch[2] };
    }

    // GitHub Enterprise SSH: git@github.company.com:owner/repo.git
    if (this.config.baseUrl) {
      const host = new URL(this.config.baseUrl).host;
      const escapedHost = host.replace(/\./g, '\\.');
      const enterpriseSshRegex = new RegExp(`git@${escapedHost}:([^/]+)/(.+?)(?:\\.git)?$`);
      const enterpriseSshMatch = url.match(enterpriseSshRegex);
      if (enterpriseSshMatch) {
        return { owner: enterpriseSshMatch[1], repo: enterpriseSshMatch[2] };
      }

      // GitHub Enterprise HTTPS
      const enterpriseHttpsRegex = new RegExp(`https?://${escapedHost}/([^/]+)/(.+?)(?:\\.git)?$`);
      const enterpriseHttpsMatch = url.match(enterpriseHttpsRegex);
      if (enterpriseHttpsMatch) {
        return { owner: enterpriseHttpsMatch[1], repo: enterpriseHttpsMatch[2] };
      }
    }

    return null;
  }

  /**
   * Check if URL matches GitHub
   */
  matchesUrl(url: string): boolean {
    return this.parseRepoUrl(url) !== null;
  }

  /**
   * Generate HTML comment for linked PR tracking
   */
  generateLinkedPRComment(links: { repoName: string; number: number }[]): string {
    const prLinks = links.map((pr) => `${pr.repoName}#${pr.number}`).join(',');
    return `<!-- codi-repo:links:${prLinks} -->`;
  }

  /**
   * Parse linked PRs from PR body
   */
  parseLinkedPRComment(body: string): { repoName: string; number: number }[] {
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
}

// Default instance cache (keyed by baseUrl for proper config handling)
const instanceCache = new Map<string, GitHubPlatform>();

/**
 * Get a GitHub platform instance (cached by config)
 * @deprecated Use getPlatformAdapter('github', config) from platform/index.ts instead
 */
export function getGitHubPlatform(config?: PlatformConfig): GitHubPlatform {
  const cacheKey = config?.baseUrl ?? 'default';
  let instance = instanceCache.get(cacheKey);
  if (!instance) {
    instance = new GitHubPlatform(config);
    instanceCache.set(cacheKey, instance);
  }
  return instance;
}

/**
 * Create a new GitHub platform instance (for custom configurations)
 */
export function createGitHubPlatform(config?: PlatformConfig): GitHubPlatform {
  return new GitHubPlatform(config);
}
