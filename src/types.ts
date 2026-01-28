/**
 * Configuration for copying a file from repo to workspace
 */
export interface CopyFileConfig {
  /** Source path relative to repo */
  src: string;
  /** Destination path relative to workspace root */
  dest: string;
}

/**
 * Configuration for creating a symlink from repo to workspace
 */
export interface LinkFileConfig {
  /** Source path relative to repo */
  src: string;
  /** Destination path relative to workspace root */
  dest: string;
}

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
  /** Files to copy from repo to workspace */
  copyfile?: CopyFileConfig[];
  /** Symlinks to create from repo to workspace */
  linkfile?: LinkFileConfig[];
}

/**
 * Configuration for the manifest repository itself
 */
export interface ManifestRepoConfig {
  /** Git URL for the manifest repository */
  url: string;
  /** Default branch name (e.g., main, master) */
  default_branch?: string;
  /** Files to copy from manifest repo to workspace */
  copyfile?: CopyFileConfig[];
  /** Symlinks to create from manifest repo to workspace */
  linkfile?: LinkFileConfig[];
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
 * A step in a multi-step script
 */
export interface ScriptStep {
  /** Step name for display */
  name: string;
  /** Command to execute */
  command: string;
  /** Working directory relative to workspace root */
  cwd?: string;
}

/**
 * A workspace script definition
 */
export interface WorkspaceScript {
  /** Description of what the script does */
  description?: string;
  /** Single command to run (mutually exclusive with steps) */
  command?: string;
  /** Working directory for single command */
  cwd?: string;
  /** Multi-step commands (mutually exclusive with command) */
  steps?: ScriptStep[];
}

/**
 * A hook command to run
 */
export interface HookCommand {
  /** Command to execute */
  command: string;
  /** Working directory relative to workspace root */
  cwd?: string;
}

/**
 * Workspace hooks configuration
 */
export interface WorkspaceHooks {
  /** Hooks to run after sync */
  'post-sync'?: HookCommand[];
  /** Hooks to run after checkout */
  'post-checkout'?: HookCommand[];
}

/**
 * Workspace configuration section
 */
export interface WorkspaceConfig {
  /** Environment variables to set */
  env?: Record<string, string>;
  /** Named scripts */
  scripts?: Record<string, WorkspaceScript>;
  /** Lifecycle hooks */
  hooks?: WorkspaceHooks;
}

/**
 * The full manifest file structure (manifest.yaml)
 */
export interface Manifest {
  version: number;
  /** Optional manifest repository configuration for self-tracking */
  manifest?: ManifestRepoConfig;
  repos: Record<string, RepoConfig>;
  settings: ManifestSettings;
  /** Workspace configuration for scripts, hooks, and env */
  workspace?: WorkspaceConfig;
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
 * State file for tracking cross-repo work (.gitgrip/state.json)
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

/**
 * Status of a file link (copyfile or linkfile)
 */
export interface LinkStatus {
  /** Type of link */
  type: 'copyfile' | 'linkfile';
  /** Repository name */
  repoName: string;
  /** Source path (absolute) */
  src: string;
  /** Destination path (absolute) */
  dest: string;
  /** Status of the link */
  status: 'valid' | 'broken' | 'missing' | 'conflict';
  /** Additional message */
  message?: string;
}

/**
 * A single timing entry in a timing report
 */
export interface TimingEntry {
  /** Label for this timing phase */
  label: string;
  /** Duration in milliseconds */
  duration: number;
  /** Nested timing entries */
  children?: TimingEntry[];
}

/**
 * A complete timing report with all phases
 */
export interface TimingReport {
  /** Total duration in milliseconds */
  total: number;
  /** Individual timing entries */
  entries: TimingEntry[];
}

/**
 * Result of a benchmark run
 */
export interface BenchmarkResult {
  /** Benchmark name */
  name: string;
  /** Number of iterations run */
  iterations: number;
  /** Minimum duration in milliseconds */
  min: number;
  /** Maximum duration in milliseconds */
  max: number;
  /** Average duration in milliseconds */
  avg: number;
  /** 50th percentile (median) in milliseconds */
  p50: number;
  /** 95th percentile in milliseconds */
  p95: number;
  /** Standard deviation in milliseconds */
  stdDev: number;
}
