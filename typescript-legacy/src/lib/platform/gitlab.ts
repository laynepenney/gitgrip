/**
 * GitLab hosting platform adapter
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
} from './types.js';

// GitLab API types (simplified)
interface GitLabMergeRequest {
  iid: number;
  web_url: string;
  title: string;
  description: string;
  state: 'opened' | 'closed' | 'merged';
  merge_status: string;
  source_branch: string;
  target_branch: string;
  sha: string;
  detailed_merge_status?: string;
}

interface GitLabApproval {
  approved: boolean;
  approved_by: { user: { username: string } }[];
}

interface GitLabPipeline {
  status: 'success' | 'failed' | 'running' | 'pending' | 'canceled' | 'skipped';
  web_url: string;
}

/**
 * GitLab platform adapter implementing the HostingPlatform interface
 */
export class GitLabPlatform implements HostingPlatform {
  readonly type: PlatformType = 'gitlab';

  private token: string | null = null;
  private config: PlatformConfig;
  private baseUrl: string;

  constructor(config?: PlatformConfig) {
    this.config = config ?? { type: 'gitlab' };
    this.baseUrl = this.config.baseUrl ?? 'https://gitlab.com';
  }

  /**
   * Get GitLab token from environment or glab CLI
   */
  async getToken(): Promise<string> {
    if (this.token) {
      return this.token;
    }

    // Try environment variable first
    if (process.env.GITLAB_TOKEN) {
      this.token = process.env.GITLAB_TOKEN;
      return this.token;
    }

    // Try glab CLI
    try {
      const output = execSync('glab auth status -t 2>&1', { encoding: 'utf-8' });
      // Parse token from glab output: "Token: glpat-..."
      const tokenMatch = output.match(/Token:\s+(\S+)/);
      if (tokenMatch) {
        this.token = tokenMatch[1];
        return this.token;
      }
    } catch {
      // glab CLI not available or not authenticated
    }

    throw new Error(
      'GitLab token not found. Set GITLAB_TOKEN environment variable or run "glab auth login"'
    );
  }

  /**
   * Make authenticated API request to GitLab
   */
  private async apiRequest<T>(
    method: string,
    endpoint: string,
    body?: unknown
  ): Promise<T> {
    const token = await this.getToken();
    const url = `${this.baseUrl}/api/v4${endpoint}`;

    const options: RequestInit = {
      method,
      headers: {
        'PRIVATE-TOKEN': token,
        'Content-Type': 'application/json',
      },
    };

    if (body) {
      options.body = JSON.stringify(body);
    }

    const response = await fetch(url, options);

    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(`GitLab API error (${response.status}): ${errorText}`);
    }

    return response.json() as Promise<T>;
  }

  /**
   * Encode project path for GitLab API (owner/repo -> owner%2Frepo)
   */
  private encodeProject(owner: string, repo: string): string {
    return encodeURIComponent(`${owner}/${repo}`);
  }

  /**
   * Create a merge request
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
    const projectId = this.encodeProject(owner, repo);
    const mrTitle = draft ? `Draft: ${title}` : title;

    const mr = await this.apiRequest<GitLabMergeRequest>(
      'POST',
      `/projects/${projectId}/merge_requests`,
      {
        source_branch: head,
        target_branch: base,
        title: mrTitle,
        description: body,
      }
    );

    return {
      number: mr.iid,
      url: mr.web_url,
    };
  }

  /**
   * Get merge request details
   */
  async getPullRequest(
    owner: string,
    repo: string,
    pullNumber: number
  ): Promise<PullRequest> {
    const projectId = this.encodeProject(owner, repo);
    const mr = await this.apiRequest<GitLabMergeRequest>(
      'GET',
      `/projects/${projectId}/merge_requests/${pullNumber}`
    );

    // Map GitLab state to our unified state
    let state: 'open' | 'closed' = 'open';
    let merged = false;

    if (mr.state === 'merged') {
      state = 'closed';
      merged = true;
    } else if (mr.state === 'closed') {
      state = 'closed';
    }

    // GitLab uses detailed_merge_status for mergeability
    const mergeable = mr.detailed_merge_status === 'mergeable' ||
      mr.merge_status === 'can_be_merged';

    return {
      number: mr.iid,
      url: mr.web_url,
      title: mr.title,
      body: mr.description ?? '',
      state,
      merged,
      mergeable,
      head: {
        ref: mr.source_branch,
        sha: mr.sha,
      },
      base: {
        ref: mr.target_branch,
      },
    };
  }

  /**
   * Update merge request description
   */
  async updatePullRequestBody(
    owner: string,
    repo: string,
    pullNumber: number,
    body: string
  ): Promise<void> {
    const projectId = this.encodeProject(owner, repo);
    await this.apiRequest(
      'PUT',
      `/projects/${projectId}/merge_requests/${pullNumber}`,
      { description: body }
    );
  }

  /**
   * Merge a merge request
   */
  async mergePullRequest(
    owner: string,
    repo: string,
    pullNumber: number,
    options: PRMergeOptions = {}
  ): Promise<boolean> {
    const projectId = this.encodeProject(owner, repo);

    try {
      // GitLab merge options
      const mergeParams: {
        squash?: boolean;
        should_remove_source_branch?: boolean;
      } = {};

      if (options.method === 'squash') {
        mergeParams.squash = true;
      }

      if (options.deleteBranch) {
        mergeParams.should_remove_source_branch = true;
      }

      await this.apiRequest(
        'PUT',
        `/projects/${projectId}/merge_requests/${pullNumber}/merge`,
        mergeParams
      );

      return true;
    } catch {
      return false;
    }
  }

  /**
   * Find MR by branch name
   */
  async findPRByBranch(
    owner: string,
    repo: string,
    branch: string
  ): Promise<PRCreateResult | null> {
    const projectId = this.encodeProject(owner, repo);

    const mrs = await this.apiRequest<GitLabMergeRequest[]>(
      'GET',
      `/projects/${projectId}/merge_requests?source_branch=${encodeURIComponent(branch)}&state=opened`
    );

    if (mrs.length > 0) {
      return {
        number: mrs[0].iid,
        url: mrs[0].web_url,
      };
    }
    return null;
  }

  /**
   * Check if MR is approved
   */
  async isPullRequestApproved(
    owner: string,
    repo: string,
    pullNumber: number
  ): Promise<boolean> {
    const projectId = this.encodeProject(owner, repo);

    try {
      const approval = await this.apiRequest<GitLabApproval>(
        'GET',
        `/projects/${projectId}/merge_requests/${pullNumber}/approvals`
      );
      return approval.approved;
    } catch {
      // Approvals API might not be available (requires license)
      // Fall back to checking if MR has any approvals
      return false;
    }
  }

  /**
   * Get MR reviews/approvals
   */
  async getPullRequestReviews(
    owner: string,
    repo: string,
    pullNumber: number
  ): Promise<PRReview[]> {
    const projectId = this.encodeProject(owner, repo);

    try {
      const approval = await this.apiRequest<GitLabApproval>(
        'GET',
        `/projects/${projectId}/merge_requests/${pullNumber}/approvals`
      );

      return approval.approved_by.map((a) => ({
        state: 'APPROVED',
        user: a.user.username,
      }));
    } catch {
      return [];
    }
  }

  /**
   * Get pipeline status for MR
   */
  async getStatusChecks(
    owner: string,
    repo: string,
    ref: string
  ): Promise<StatusCheckResult> {
    const projectId = this.encodeProject(owner, repo);

    try {
      // Get pipelines for this ref
      const pipelines = await this.apiRequest<GitLabPipeline[]>(
        'GET',
        `/projects/${projectId}/pipelines?sha=${ref}&per_page=1`
      );

      if (pipelines.length === 0) {
        return { state: 'success', statuses: [] };
      }

      const pipeline = pipelines[0];

      // Map GitLab pipeline status to our unified status
      let state: 'success' | 'failure' | 'pending';
      switch (pipeline.status) {
        case 'success':
          state = 'success';
          break;
        case 'failed':
        case 'canceled':
          state = 'failure';
          break;
        default:
          state = 'pending';
      }

      return {
        state,
        statuses: [{ context: 'gitlab-pipeline', state: pipeline.status }],
      };
    } catch {
      // No pipeline or API error
      return { state: 'success', statuses: [] };
    }
  }

  /**
   * Parse GitLab URL to extract owner/repo (group/project)
   */
  parseRepoUrl(url: string): ParsedRepoInfo | null {
    // Extract hostname from baseUrl for matching
    const baseHost = new URL(this.baseUrl).host;
    const escapedHost = baseHost.replace(/\./g, '\\.');

    // SSH format: git@gitlab.com:owner/repo.git or git@gitlab.com:group/subgroup/repo.git
    const sshRegex = new RegExp(`git@${escapedHost}:(.+?)(?:\\.git)?$`);
    const sshMatch = url.match(sshRegex);
    if (sshMatch) {
      const path = sshMatch[1];
      const parts = path.split('/');
      // Last part is repo, everything else is the namespace (owner)
      const repo = parts.pop()!;
      const owner = parts.join('/');
      return { owner, repo };
    }

    // HTTPS format: https://gitlab.com/owner/repo.git
    const httpsRegex = new RegExp(`https?://${escapedHost}/(.+?)(?:\\.git)?$`);
    const httpsMatch = url.match(httpsRegex);
    if (httpsMatch) {
      const path = httpsMatch[1];
      const parts = path.split('/');
      const repo = parts.pop()!;
      const owner = parts.join('/');
      return { owner, repo };
    }

    // Also check for generic gitlab patterns if no baseUrl match
    if (this.baseUrl === 'https://gitlab.com') {
      const genericSshMatch = url.match(/git@gitlab\.com:(.+?)(?:\.git)?$/);
      if (genericSshMatch) {
        const path = genericSshMatch[1];
        const parts = path.split('/');
        const repo = parts.pop()!;
        const owner = parts.join('/');
        return { owner, repo };
      }

      const genericHttpsMatch = url.match(/https?:\/\/gitlab\.com\/(.+?)(?:\.git)?$/);
      if (genericHttpsMatch) {
        const path = genericHttpsMatch[1];
        const parts = path.split('/');
        const repo = parts.pop()!;
        const owner = parts.join('/');
        return { owner, repo };
      }
    }

    return null;
  }

  /**
   * Check if URL matches GitLab
   */
  matchesUrl(url: string): boolean {
    // Check for gitlab.com (specific match)
    if (url.includes('gitlab.com')) return true;

    // Check against configured base URL
    if (this.config.baseUrl) {
      const host = new URL(this.config.baseUrl).host;
      if (url.includes(host)) return true;
    }

    // Check if URL appears to be GitLab (contains gitlab in the hostname, not path)
    // Match patterns like git@gitlab.company.com or https://gitlab.company.com
    if (/(?:@|:\/\/)gitlab\./i.test(url)) return true;

    return false;
  }

  /**
   * Generate HTML comment for linked MR tracking
   */
  generateLinkedPRComment(links: { repoName: string; number: number }[]): string {
    const prLinks = links.map((pr) => `${pr.repoName}!${pr.number}`).join(',');
    return `<!-- codi-repo:links:${prLinks} -->`;
  }

  /**
   * Parse linked MRs from MR description
   */
  parseLinkedPRComment(body: string): { repoName: string; number: number }[] {
    const match = body.match(/<!-- codi-repo:links:(.+?) -->/);
    if (!match) {
      return [];
    }

    const links = match[1].split(',');
    return links.map((link) => {
      // GitLab uses ! for MR references
      const [repoName, numStr] = link.split(/[#!]/);
      return { repoName, number: parseInt(numStr, 10) };
    });
  }
}

/**
 * Create a new GitLab platform instance
 */
export function createGitLabPlatform(config?: PlatformConfig): GitLabPlatform {
  return new GitLabPlatform(config);
}
