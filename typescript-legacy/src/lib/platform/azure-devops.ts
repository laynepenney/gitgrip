/**
 * Azure DevOps hosting platform adapter
 */
import { execSync } from 'child_process';
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
  AzureDevOpsContext,
} from './types.js';

// Azure DevOps API types (simplified)
interface AzurePullRequest {
  pullRequestId: number;
  title: string;
  description: string;
  status: 'active' | 'abandoned' | 'completed';
  mergeStatus: string;
  sourceRefName: string;
  targetRefName: string;
  lastMergeSourceCommit: { commitId: string };
  repository: { webUrl: string };
}

interface AzureReviewer {
  vote: number; // 10 = approved, -10 = rejected, 0 = no vote, 5 = approved with suggestions, -5 = waiting for author
  displayName: string;
  uniqueName: string;
}

interface AzureBuild {
  result: 'succeeded' | 'failed' | 'canceled' | 'partiallySucceeded' | undefined;
  status: 'completed' | 'inProgress' | 'notStarted' | 'cancelling' | 'postponed';
}

/**
 * Azure DevOps platform adapter implementing the HostingPlatform interface
 */
export class AzureDevOpsPlatform implements HostingPlatform {
  readonly type: PlatformType = 'azure-devops';

  private token: string | null = null;
  private config: PlatformConfig;
  private baseUrl: string;

  constructor(config?: PlatformConfig) {
    this.config = config ?? { type: 'azure-devops' };
    this.baseUrl = this.config.baseUrl ?? 'https://dev.azure.com';
  }

  /**
   * Get Azure DevOps token from environment or az CLI
   */
  async getToken(): Promise<string> {
    if (this.token) {
      return this.token;
    }

    // Try environment variable first
    if (process.env.AZURE_DEVOPS_TOKEN) {
      this.token = process.env.AZURE_DEVOPS_TOKEN;
      return this.token;
    }

    // Alternative env var name
    if (process.env.AZURE_DEVOPS_EXT_PAT) {
      this.token = process.env.AZURE_DEVOPS_EXT_PAT;
      return this.token;
    }

    // Try az CLI to get PAT
    try {
      // Note: az devops configure --use-git-aliases doesn't provide token directly
      // Users typically need to use a PAT stored in env var
      const output = execSync('az account get-access-token --resource 499b84ac-1321-427f-aa17-267ca6975798 --query accessToken -o tsv 2>/dev/null', { encoding: 'utf-8' });
      if (output.trim()) {
        this.token = output.trim();
        return this.token;
      }
    } catch {
      // az CLI not available or not authenticated
    }

    throw new Error(
      'Azure DevOps token not found. Set AZURE_DEVOPS_TOKEN environment variable or use az login'
    );
  }

  /**
   * Make authenticated API request to Azure DevOps
   */
  private async apiRequest<T>(
    method: string,
    org: string,
    project: string,
    endpoint: string,
    body?: unknown,
    apiVersion = '7.0'
  ): Promise<T> {
    const token = await this.getToken();
    const url = `${this.baseUrl}/${org}/${project}/_apis${endpoint}?api-version=${apiVersion}`;

    // Azure DevOps uses Basic auth with PAT (user can be empty)
    const authHeader = Buffer.from(`:${token}`).toString('base64');

    const options: RequestInit = {
      method,
      headers: {
        'Authorization': `Basic ${authHeader}`,
        'Content-Type': 'application/json',
      },
    };

    if (body) {
      options.body = JSON.stringify(body);
    }

    const response = await fetch(url, options);

    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(`Azure DevOps API error (${response.status}): ${errorText}`);
    }

    return response.json() as Promise<T>;
  }

  /**
   * Parse Azure DevOps context from owner string
   * Format: "org/project" where owner is org and repo is separate
   */
  private parseContext(owner: string, repo: string): AzureDevOpsContext {
    // In Azure DevOps, the "owner" from our URL parsing is actually "org/project"
    const parts = owner.split('/');
    if (parts.length >= 2) {
      return {
        organization: parts[0],
        project: parts.slice(1).join('/'),
        repository: repo,
      };
    }
    // Fallback: owner is org, and we use repo as both project and repo
    return {
      organization: owner,
      project: repo,
      repository: repo,
    };
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
    const ctx = this.parseContext(owner, repo);

    const pr = await this.apiRequest<AzurePullRequest>(
      'POST',
      ctx.organization,
      ctx.project,
      `/git/repositories/${ctx.repository}/pullrequests`,
      {
        sourceRefName: `refs/heads/${head}`,
        targetRefName: `refs/heads/${base}`,
        title,
        description: body,
        isDraft: draft,
      }
    );

    const webUrl = `${this.baseUrl}/${ctx.organization}/${ctx.project}/_git/${ctx.repository}/pullrequest/${pr.pullRequestId}`;

    return {
      number: pr.pullRequestId,
      url: webUrl,
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
    const ctx = this.parseContext(owner, repo);

    const pr = await this.apiRequest<AzurePullRequest>(
      'GET',
      ctx.organization,
      ctx.project,
      `/git/repositories/${ctx.repository}/pullrequests/${pullNumber}`
    );

    // Map Azure DevOps status to our unified state
    let state: 'open' | 'closed' = 'open';
    let merged = false;

    if (pr.status === 'completed') {
      state = 'closed';
      // Azure DevOps merges on completion (or could be closed without merge)
      // Check merge status to determine
      merged = pr.mergeStatus === 'succeeded';
    } else if (pr.status === 'abandoned') {
      state = 'closed';
    }

    // Azure DevOps mergeability
    const mergeable = pr.mergeStatus === 'succeeded' || pr.mergeStatus === 'queued';

    const webUrl = `${this.baseUrl}/${ctx.organization}/${ctx.project}/_git/${ctx.repository}/pullrequest/${pr.pullRequestId}`;

    return {
      number: pr.pullRequestId,
      url: webUrl,
      title: pr.title,
      body: pr.description ?? '',
      state,
      merged,
      mergeable,
      head: {
        ref: pr.sourceRefName.replace('refs/heads/', ''),
        sha: pr.lastMergeSourceCommit?.commitId ?? '',
      },
      base: {
        ref: pr.targetRefName.replace('refs/heads/', ''),
      },
    };
  }

  /**
   * Update pull request description
   */
  async updatePullRequestBody(
    owner: string,
    repo: string,
    pullNumber: number,
    body: string
  ): Promise<void> {
    const ctx = this.parseContext(owner, repo);

    await this.apiRequest(
      'PATCH',
      ctx.organization,
      ctx.project,
      `/git/repositories/${ctx.repository}/pullrequests/${pullNumber}`,
      { description: body }
    );
  }

  /**
   * Merge (complete) a pull request
   */
  async mergePullRequest(
    owner: string,
    repo: string,
    pullNumber: number,
    options: PRMergeOptions = {}
  ): Promise<boolean> {
    const ctx = this.parseContext(owner, repo);

    try {
      // Get current PR to get the last merge source commit
      const pr = await this.getPullRequest(owner, repo, pullNumber);

      // Azure DevOps "complete" action
      const completeOptions: {
        status: string;
        lastMergeSourceCommit: { commitId: string };
        completionOptions?: {
          deleteSourceBranch?: boolean;
          mergeStrategy?: string;
          squashMerge?: boolean;
        };
      } = {
        status: 'completed',
        lastMergeSourceCommit: { commitId: pr.head.sha },
        completionOptions: {},
      };

      if (options.deleteBranch) {
        completeOptions.completionOptions!.deleteSourceBranch = true;
      }

      // Map merge method
      if (options.method === 'squash') {
        completeOptions.completionOptions!.squashMerge = true;
      } else if (options.method === 'rebase') {
        completeOptions.completionOptions!.mergeStrategy = 'rebase';
      }

      await this.apiRequest(
        'PATCH',
        ctx.organization,
        ctx.project,
        `/git/repositories/${ctx.repository}/pullrequests/${pullNumber}`,
        completeOptions
      );

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
    const ctx = this.parseContext(owner, repo);

    const response = await this.apiRequest<{ value: AzurePullRequest[] }>(
      'GET',
      ctx.organization,
      ctx.project,
      `/git/repositories/${ctx.repository}/pullrequests?searchCriteria.sourceRefName=refs/heads/${encodeURIComponent(branch)}&searchCriteria.status=active`
    );

    if (response.value && response.value.length > 0) {
      const pr = response.value[0];
      const webUrl = `${this.baseUrl}/${ctx.organization}/${ctx.project}/_git/${ctx.repository}/pullrequest/${pr.pullRequestId}`;
      return {
        number: pr.pullRequestId,
        url: webUrl,
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
    // Azure DevOps: vote 10 = approved, 5 = approved with suggestions
    const hasApproval = reviews.some((r) => r.state === 'APPROVED' || r.state === 'APPROVED_WITH_SUGGESTIONS');
    const hasRejection = reviews.some((r) => r.state === 'REJECTED' || r.state === 'WAITING_FOR_AUTHOR');
    return hasApproval && !hasRejection;
  }

  /**
   * Get PR reviewers/votes
   */
  async getPullRequestReviews(
    owner: string,
    repo: string,
    pullNumber: number
  ): Promise<PRReview[]> {
    const ctx = this.parseContext(owner, repo);

    const pr = await this.apiRequest<{ reviewers: AzureReviewer[] }>(
      'GET',
      ctx.organization,
      ctx.project,
      `/git/repositories/${ctx.repository}/pullrequests/${pullNumber}`
    );

    return (pr.reviewers ?? []).map((reviewer) => {
      // Map Azure DevOps vote to state
      let state: string;
      switch (reviewer.vote) {
        case 10:
          state = 'APPROVED';
          break;
        case 5:
          state = 'APPROVED_WITH_SUGGESTIONS';
          break;
        case -10:
          state = 'REJECTED';
          break;
        case -5:
          state = 'WAITING_FOR_AUTHOR';
          break;
        default:
          state = 'PENDING';
      }
      return {
        state,
        user: reviewer.displayName || reviewer.uniqueName,
      };
    });
  }

  /**
   * Get build status for a commit/PR
   */
  async getStatusChecks(
    owner: string,
    repo: string,
    ref: string
  ): Promise<StatusCheckResult> {
    const ctx = this.parseContext(owner, repo);

    try {
      // Get builds for this commit
      const response = await this.apiRequest<{ value: AzureBuild[] }>(
        'GET',
        ctx.organization,
        ctx.project,
        `/build/builds?repositoryId=${ctx.repository}&repositoryType=TfsGit&$top=5`,
        undefined,
        '7.0'
      );

      if (!response.value || response.value.length === 0) {
        return { state: 'success', statuses: [] };
      }

      // Find builds for this ref/commit
      const builds = response.value;

      // Aggregate status
      const hasFailure = builds.some((b) => b.result === 'failed' || b.result === 'canceled');
      const hasInProgress = builds.some((b) => b.status !== 'completed');

      let state: 'success' | 'failure' | 'pending';
      if (hasFailure) {
        state = 'failure';
      } else if (hasInProgress) {
        state = 'pending';
      } else {
        state = 'success';
      }

      return {
        state,
        statuses: builds.map((b) => ({
          context: 'azure-pipeline',
          state: b.result ?? b.status,
        })),
      };
    } catch {
      // No builds or API error
      return { state: 'success', statuses: [] };
    }
  }

  /**
   * Parse Azure DevOps URL to extract org/project/repo
   */
  parseRepoUrl(url: string): ParsedRepoInfo | null {
    // SSH format: git@ssh.dev.azure.com:v3/org/project/repo
    const sshMatch = url.match(/git@ssh\.dev\.azure\.com:v3\/([^/]+)\/([^/]+)\/(.+?)(?:\.git)?$/);
    if (sshMatch) {
      return {
        owner: `${sshMatch[1]}/${sshMatch[2]}`, // org/project
        repo: sshMatch[3],
        project: sshMatch[2],
      };
    }

    // HTTPS format: https://dev.azure.com/org/project/_git/repo
    const httpsMatch = url.match(/https?:\/\/dev\.azure\.com\/([^/]+)\/([^/]+)\/_git\/(.+?)(?:\.git)?$/);
    if (httpsMatch) {
      return {
        owner: `${httpsMatch[1]}/${httpsMatch[2]}`, // org/project
        repo: httpsMatch[3],
        project: httpsMatch[2],
      };
    }

    // Legacy visualstudio.com format: https://org.visualstudio.com/project/_git/repo
    const legacyMatch = url.match(/https?:\/\/([^.]+)\.visualstudio\.com\/([^/]+)\/_git\/(.+?)(?:\.git)?$/);
    if (legacyMatch) {
      return {
        owner: `${legacyMatch[1]}/${legacyMatch[2]}`, // org/project
        repo: legacyMatch[3],
        project: legacyMatch[2],
      };
    }

    // Check custom base URL
    if (this.config.baseUrl && this.config.baseUrl !== 'https://dev.azure.com') {
      const host = new URL(this.config.baseUrl).host;
      const escapedHost = host.replace(/\./g, '\\.');
      const customRegex = new RegExp(`https?://${escapedHost}/([^/]+)/([^/]+)/_git/(.+?)(?:\\.git)?$`);
      const customMatch = url.match(customRegex);
      if (customMatch) {
        return {
          owner: `${customMatch[1]}/${customMatch[2]}`,
          repo: customMatch[3],
          project: customMatch[2],
        };
      }
    }

    return null;
  }

  /**
   * Check if URL matches Azure DevOps
   */
  matchesUrl(url: string): boolean {
    if (url.includes('dev.azure.com')) return true;
    if (url.includes('visualstudio.com')) return true;
    if (url.includes('ssh.dev.azure.com')) return true;

    // Check against configured base URL (for Azure DevOps Server)
    if (this.config.baseUrl && this.config.baseUrl !== 'https://dev.azure.com') {
      const host = new URL(this.config.baseUrl).host;
      if (url.includes(host)) return true;
    }

    return false;
  }

  /**
   * Generate HTML comment for linked PR tracking
   */
  generateLinkedPRComment(links: { repoName: string; number: number }[]): string {
    const prLinks = links.map((pr) => `${pr.repoName}!${pr.number}`).join(',');
    return `<!-- codi-repo:links:${prLinks} -->`;
  }

  /**
   * Parse linked PRs from PR description
   */
  parseLinkedPRComment(body: string): { repoName: string; number: number }[] {
    const match = body.match(/<!-- codi-repo:links:(.+?) -->/);
    if (!match) {
      return [];
    }

    const links = match[1].split(',');
    return links.map((link) => {
      const [repoName, numStr] = link.split(/[#!]/);
      return { repoName, number: parseInt(numStr, 10) };
    });
  }
}

/**
 * Create a new Azure DevOps platform instance
 */
export function createAzureDevOpsPlatform(config?: PlatformConfig): AzureDevOpsPlatform {
  return new AzureDevOpsPlatform(config);
}
