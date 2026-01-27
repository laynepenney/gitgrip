/**
 * Configuration for a single repository in the manifest
 */
export interface RepoConfig {
  /** Git URL (SSH or HTTPS) */
  url: string;
  /** Local path relative to manifest root */
  path: string;
  /** Default branch name (e.g., main, master) */
  default_branch: string;
}

/**
 * Configuration for the manifest repository itself
 */
export interface ManifestRepoConfig {
  /** Git URL for the manifest repository */
  url: string;
}

/**
 * Global settings for the manifest
 */
export interface ManifestSettings {
  /** Prefix for cross-repo PR titles */
  pr_prefix: string;
  /** Merge strategy: all-or-nothing means all linked PRs must merge together */
  merge_strategy: 'all-or-nothing' | 'independent';
}

/**
 * The full manifest file structure (codi-repos.yaml)
 */
export interface Manifest {
  version: number;
  /** Optional manifest repository configuration for self-tracking */
  manifest?: ManifestRepoConfig;
  repos: Record<string, RepoConfig>;
  settings: ManifestSettings;
}

/**
 * Parsed repository info with computed fields
 */
export interface RepoInfo extends RepoConfig {
  /** Repository name (key from manifest) */
  name: string;
  /** Absolute path on disk */
  absolutePath: string;
  /** Owner from GitHub URL */
  owner: string;
  /** Repo name from GitHub URL */
  repo: string;
}

/**
 * Status of a single repository
 */
export interface RepoStatus {
  /** Repository name */
  name: string;
  /** Current branch */
  branch: string;
  /** Whether working directory is clean */
  clean: boolean;
  /** Number of staged files */
  staged: number;
  /** Number of modified files */
  modified: number;
  /** Number of untracked files */
  untracked: number;
  /** Commits ahead of remote */
  ahead: number;
  /** Commits behind remote */
  behind: number;
  /** Whether repo exists on disk */
  exists: boolean;
}

/**
 * A linked PR in a child repository
 */
export interface LinkedPR {
  /** Repository name (from manifest) */
  repoName: string;
  /** Owner on GitHub */
  owner: string;
  /** Repo name on GitHub */
  repo: string;
  /** PR number */
  number: number;
  /** PR URL */
  url: string;
  /** PR state: open, closed, merged */
  state: 'open' | 'closed' | 'merged';
  /** Whether PR is approved */
  approved: boolean;
  /** Whether all checks passed */
  checksPass: boolean;
  /** Whether PR is mergeable */
  mergeable: boolean;
}

/**
 * A manifest PR that tracks linked child PRs
 */
export interface ManifestPR {
  /** Manifest PR number */
  number: number;
  /** Manifest PR URL */
  url: string;
  /** PR title */
  title: string;
  /** Linked child PRs */
  linkedPRs: LinkedPR[];
  /** Overall state */
  state: 'open' | 'closed' | 'merged';
  /** Whether all linked PRs are ready to merge */
  readyToMerge: boolean;
}

/**
 * State file for tracking cross-repo work (.codi-repo/state.json)
 */
export interface StateFile {
  /** Current manifest PR being worked on */
  currentManifestPR?: number;
  /** Map of branch names to manifest PR numbers */
  branchToPR: Record<string, number>;
  /** Map of manifest PR numbers to linked PRs */
  prLinks: Record<number, LinkedPR[]>;
}

/**
 * Result of a git operation across repos
 */
export interface MultiRepoResult<T> {
  /** Repository name */
  repoName: string;
  /** Whether operation succeeded */
  success: boolean;
  /** Result data if successful */
  data?: T;
  /** Error message if failed */
  error?: string;
}

/**
 * Options for PR creation
 */
export interface PRCreateOptions {
  /** PR title */
  title: string;
  /** PR body/description */
  body?: string;
  /** Base branch to merge into */
  base?: string;
  /** Whether to create as draft */
  draft?: boolean;
  /** Only create PRs for repos with changes */
  changesOnly?: boolean;
}

/**
 * Options for PR merge
 */
export interface PRMergeOptions {
  /** Merge method: merge, squash, or rebase */
  method?: 'merge' | 'squash' | 'rebase';
  /** Whether to delete branches after merge */
  deleteBranch?: boolean;
  /** Whether to skip confirmation */
  force?: boolean;
}

/**
 * GitHub repository info extracted from URL
 */
export interface GitHubRepoInfo {
  owner: string;
  repo: string;
}
