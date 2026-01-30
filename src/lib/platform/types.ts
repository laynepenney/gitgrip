/**
 * Platform types for multi-platform hosting support (GitHub, GitLab, Azure DevOps)
 */

export type PlatformType = 'github' | 'gitlab' | 'azure-devops';

/**
 * Configuration for a hosting platform, including self-hosted instances
 */
export interface PlatformConfig {
  type: PlatformType;
  /** Base URL for self-hosted instances (e.g., https://gitlab.company.com) */
  baseUrl?: string;
}

/**
 * Parsed repository information from a git URL
 */
export interface ParsedRepoInfo {
  owner: string;
  repo: string;
  /** For Azure DevOps: the project name */
  project?: string;
}

/**
 * Pull request state across all platforms
 */
export type PRState = 'open' | 'closed' | 'merged';

/**
 * Normalized pull request information across platforms
 */
export interface PullRequest {
  number: number;
  url: string;
  title: string;
  body: string;
  state: PRState;
  merged: boolean;
  mergeable: boolean | null;
  head: { ref: string; sha: string };
  base: { ref: string };
}

/**
 * Options for creating a pull request
 */
export interface PRCreateOptions {
  title: string;
  body?: string;
  base?: string;
  draft?: boolean;
}

/**
 * Options for merging a pull request
 */
export interface PRMergeOptions {
  method?: 'merge' | 'squash' | 'rebase';
  deleteBranch?: boolean;
}

/**
 * Result of creating a pull request
 */
export interface PRCreateResult {
  number: number;
  url: string;
}

/**
 * Review information
 */
export interface PRReview {
  state: string;
  user: string;
}

/**
 * Status check result
 */
export interface StatusCheckResult {
  state: 'success' | 'failure' | 'pending';
  statuses: { context: string; state: string }[];
}

/**
 * Allowed merge methods for a repository
 */
export interface AllowedMergeMethods {
  merge: boolean;
  squash: boolean;
  rebase: boolean;
}

/**
 * Interface for hosting platform adapters
 * Each platform (GitHub, GitLab, Azure DevOps) implements this interface
 */
export interface HostingPlatform {
  /** Platform type identifier */
  readonly type: PlatformType;

  // Authentication
  /**
   * Get authentication token for API calls
   * @throws Error if token is not available
   */
  getToken(): Promise<string>;

  // PR Operations
  /**
   * Create a pull request
   */
  createPullRequest(
    owner: string,
    repo: string,
    head: string,
    base: string,
    title: string,
    body?: string,
    draft?: boolean
  ): Promise<PRCreateResult>;

  /**
   * Get pull request details
   */
  getPullRequest(
    owner: string,
    repo: string,
    pullNumber: number
  ): Promise<PullRequest>;

  /**
   * Update pull request body
   */
  updatePullRequestBody(
    owner: string,
    repo: string,
    pullNumber: number,
    body: string
  ): Promise<void>;

  /**
   * Merge a pull request
   * @returns true if merge succeeded, false otherwise
   */
  mergePullRequest(
    owner: string,
    repo: string,
    pullNumber: number,
    options?: PRMergeOptions
  ): Promise<boolean>;

  /**
   * Find an open PR by branch name
   */
  findPRByBranch(
    owner: string,
    repo: string,
    branch: string
  ): Promise<PRCreateResult | null>;

  // Review & Status
  /**
   * Check if PR is approved (has approval, no changes requested)
   */
  isPullRequestApproved(
    owner: string,
    repo: string,
    pullNumber: number
  ): Promise<boolean>;

  /**
   * Get reviews for a PR
   */
  getPullRequestReviews(
    owner: string,
    repo: string,
    pullNumber: number
  ): Promise<PRReview[]>;

  /**
   * Get CI/CD status checks for a commit
   */
  getStatusChecks(
    owner: string,
    repo: string,
    ref: string
  ): Promise<StatusCheckResult>;

  /**
   * Get allowed merge methods for a repository
   * Used to determine fallback methods when merge fails
   */
  getAllowedMergeMethods?(
    owner: string,
    repo: string
  ): Promise<AllowedMergeMethods>;

  // URL Parsing
  /**
   * Parse a git URL to extract owner/repo information
   * @returns null if URL doesn't match this platform
   */
  parseRepoUrl(url: string): ParsedRepoInfo | null;

  /**
   * Check if a URL belongs to this platform
   */
  matchesUrl(url: string): boolean;

  // PR Body Linking (for cross-repo PR tracking)
  /**
   * Generate HTML comment for linked PR tracking
   */
  generateLinkedPRComment(links: { repoName: string; number: number }[]): string;

  /**
   * Parse linked PR references from PR body
   */
  parseLinkedPRComment(body: string): { repoName: string; number: number }[];
}

/**
 * Options for Azure DevOps that require project context
 */
export interface AzureDevOpsContext {
  organization: string;
  project: string;
  repository: string;
}
