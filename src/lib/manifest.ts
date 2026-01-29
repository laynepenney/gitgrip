import { readFile, writeFile, access } from 'fs/promises';
import { resolve, dirname, join, normalize } from 'path';
import YAML from 'yaml';
import type { Manifest, RepoInfo, StateFile, GitHubRepoInfo, CopyFileConfig, LinkFileConfig, WorkspaceScript, PlatformType, ParsedRepoInfo } from '../types.js';
import { parseRepoUrl as platformParseRepoUrl, detectPlatform } from './platform/index.js';

// AOSP-style: manifest lives in .gitgrip/manifests/manifest.yaml
const GITGRIP_DIR = '.gitgrip';
const MANIFESTS_DIR = 'manifests';
const MANIFEST_FILENAME = 'manifest.yaml';
const STATE_FILENAME = 'state.json';

/**
 * Default manifest settings
 */
const DEFAULT_SETTINGS = {
  pr_prefix: '[cross-repo]',
  merge_strategy: 'all-or-nothing' as const,
};

/**
 * Check if a relative path would escape its parent directory
 */
function pathEscapesBoundary(relativePath: string): boolean {
  const normalized = normalize(relativePath);
  // Check for path traversal attempts
  if (normalized.startsWith('..') || normalized.startsWith('/') || normalized.includes('/../')) {
    return true;
  }
  return false;
}

/**
 * Validate copyfile/linkfile config
 */
function validateFileConfig(
  config: CopyFileConfig | LinkFileConfig,
  type: 'copyfile' | 'linkfile',
  repoName: string
): void {
  if (!config.src || typeof config.src !== 'string') {
    throw new Error(`${type} in repo '${repoName}' is missing 'src'`);
  }
  if (!config.dest || typeof config.dest !== 'string') {
    throw new Error(`${type} in repo '${repoName}' is missing 'dest'`);
  }
  if (pathEscapesBoundary(config.src)) {
    throw new Error(`${type} in repo '${repoName}': src path '${config.src}' escapes repo boundary`);
  }
  if (pathEscapesBoundary(config.dest)) {
    throw new Error(`${type} in repo '${repoName}': dest path '${config.dest}' escapes workspace boundary`);
  }
}

/**
 * Validate workspace script config
 */
function validateScript(script: WorkspaceScript, scriptName: string): void {
  if (!script.command && !script.steps) {
    throw new Error(`Script '${scriptName}' must have either 'command' or 'steps'`);
  }
  if (script.command && script.steps) {
    throw new Error(`Script '${scriptName}' cannot have both 'command' and 'steps'`);
  }
  if (script.steps) {
    for (let i = 0; i < script.steps.length; i++) {
      const step = script.steps[i];
      if (!step.name) {
        throw new Error(`Script '${scriptName}' step ${i + 1} is missing 'name'`);
      }
      if (!step.command) {
        throw new Error(`Script '${scriptName}' step '${step.name}' is missing 'command'`);
      }
    }
  }
}

/**
 * Get the path to the gitgrip directory (.gitgrip)
 */
export function getGitgripDir(workspaceRoot: string): string {
  return join(workspaceRoot, GITGRIP_DIR);
}

/**
 * Get the path to the manifests directory
 */
export function getManifestsDir(workspaceRoot: string): string {
  return join(getGitgripDir(workspaceRoot), MANIFESTS_DIR);
}

/**
 * Get the path to the manifest file
 */
export function getManifestPath(workspaceRoot: string): string {
  return join(getManifestsDir(workspaceRoot), MANIFEST_FILENAME);
}

/**
 * Find the manifest file by walking up the directory tree
 * Looks for .codi-repo/manifests/manifest.yaml (new format)
 */
export async function findManifestPath(startDir: string = process.cwd()): Promise<string | null> {
  let currentDir = resolve(startDir);

  while (currentDir !== dirname(currentDir)) {
    const manifestPath = getManifestPath(currentDir);
    try {
      await access(manifestPath);
      return manifestPath;
    } catch {
      currentDir = dirname(currentDir);
    }
  }

  return null;
}

/**
 * Load and parse the manifest file
 * Returns the workspace root (parent of .gitgrip, not the manifests dir)
 */
export async function loadManifest(manifestPath?: string): Promise<{ manifest: Manifest; rootDir: string }> {
  const path = manifestPath ?? (await findManifestPath());
  if (!path) {
    throw new Error(`Manifest file not found. Run 'gr init <manifest-url>' first.`);
  }

  const content = await readFile(path, 'utf-8');
  const parsed = YAML.parse(content) as Partial<Manifest>;

  // Validate and apply defaults
  if (!parsed.version) {
    parsed.version = 1;
  }
  if (!parsed.repos || Object.keys(parsed.repos).length === 0) {
    throw new Error('Manifest must define at least one repository');
  }
  if (!parsed.settings) {
    parsed.settings = DEFAULT_SETTINGS;
  } else {
    parsed.settings = { ...DEFAULT_SETTINGS, ...parsed.settings };
  }

  // Validate each repo config
  for (const [name, repo] of Object.entries(parsed.repos)) {
    if (!repo.url) {
      throw new Error(`Repository '${name}' is missing 'url'`);
    }
    if (!repo.path) {
      throw new Error(`Repository '${name}' is missing 'path'`);
    }
    if (!repo.default_branch) {
      repo.default_branch = 'main';
    }

    // Validate copyfile entries
    if (repo.copyfile) {
      if (!Array.isArray(repo.copyfile)) {
        throw new Error(`Repository '${name}': copyfile must be an array`);
      }
      for (const config of repo.copyfile) {
        validateFileConfig(config, 'copyfile', name);
      }
    }

    // Validate linkfile entries
    if (repo.linkfile) {
      if (!Array.isArray(repo.linkfile)) {
        throw new Error(`Repository '${name}': linkfile must be an array`);
      }
      for (const config of repo.linkfile) {
        validateFileConfig(config, 'linkfile', name);
      }
    }
  }

  // Validate manifest-level config
  if (parsed.manifest) {
    // Default manifest branch to 'main'
    if (!parsed.manifest.default_branch) {
      parsed.manifest.default_branch = 'main';
    }

    if (parsed.manifest.copyfile) {
      if (!Array.isArray(parsed.manifest.copyfile)) {
        throw new Error('manifest.copyfile must be an array');
      }
      for (const config of parsed.manifest.copyfile) {
        validateFileConfig(config, 'copyfile', 'manifest');
      }
    }
    if (parsed.manifest.linkfile) {
      if (!Array.isArray(parsed.manifest.linkfile)) {
        throw new Error('manifest.linkfile must be an array');
      }
      for (const config of parsed.manifest.linkfile) {
        validateFileConfig(config, 'linkfile', 'manifest');
      }
    }
  }

  // Validate workspace config
  if (parsed.workspace) {
    // Validate env
    if (parsed.workspace.env) {
      if (typeof parsed.workspace.env !== 'object') {
        throw new Error('workspace.env must be an object');
      }
    }

    // Validate scripts
    if (parsed.workspace.scripts) {
      if (typeof parsed.workspace.scripts !== 'object') {
        throw new Error('workspace.scripts must be an object');
      }
      for (const [scriptName, script] of Object.entries(parsed.workspace.scripts)) {
        validateScript(script, scriptName);
      }
    }

    // Validate hooks
    if (parsed.workspace.hooks) {
      if (typeof parsed.workspace.hooks !== 'object') {
        throw new Error('workspace.hooks must be an object');
      }
      const validHooks = ['post-sync', 'post-checkout'];
      for (const hookName of Object.keys(parsed.workspace.hooks)) {
        if (!validHooks.includes(hookName)) {
          throw new Error(`Unknown hook '${hookName}'. Valid hooks: ${validHooks.join(', ')}`);
        }
        const hooks = parsed.workspace.hooks[hookName as keyof typeof parsed.workspace.hooks];
        if (hooks && !Array.isArray(hooks)) {
          throw new Error(`workspace.hooks.${hookName} must be an array`);
        }
      }
    }
  }

  // rootDir is the workspace root (parent of .codi-repo/manifests/)
  // Path is: <workspace>/.codi-repo/manifests/manifest.yaml
  const manifestsDir = dirname(path);
  const codiRepoDir = dirname(manifestsDir);
  const workspaceRoot = dirname(codiRepoDir);

  return {
    manifest: parsed as Manifest,
    rootDir: workspaceRoot,
  };
}

/**
 * Create a new manifest file in the manifests directory
 */
export async function createManifest(manifestsDir: string, manifest: Manifest): Promise<void> {
  const manifestPath = join(manifestsDir, MANIFEST_FILENAME);
  const content = YAML.stringify(manifest, {
    indent: 2,
    lineWidth: 0,
  });
  await writeFile(manifestPath, content, 'utf-8');
}

/**
 * Parse GitHub owner/repo from a git URL
 * @deprecated Use parseRepoUrl for multi-platform support
 */
export function parseGitHubUrl(url: string): GitHubRepoInfo {
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

  throw new Error(`Unable to parse GitHub URL: ${url}`);
}

/**
 * Parse repository info from a git URL (supports GitHub, GitLab, Azure DevOps)
 */
export function parseRepoUrl(url: string): ParsedRepoInfo {
  const parsed = platformParseRepoUrl(url);
  if (!parsed) {
    throw new Error(
      `Unable to parse git URL: ${url}. ` +
      `Supported platforms: GitHub, GitLab, Azure DevOps`
    );
  }
  return {
    owner: parsed.owner,
    repo: parsed.repo,
    project: parsed.project,
    platform: parsed.platform,
  };
}

/**
 * Detect platform type from URL or config
 */
export function getPlatformType(url: string, configPlatform?: { type: PlatformType }): PlatformType {
  // Use explicit config if provided
  if (configPlatform?.type) {
    return configPlatform.type;
  }

  // Auto-detect from URL
  const detected = detectPlatform(url);
  if (!detected) {
    // Default to github for backward compatibility
    return 'github';
  }
  return detected;
}

/**
 * Get full repo info with computed fields
 */
export function getRepoInfo(name: string, config: Manifest['repos'][string], rootDir: string): RepoInfo {
  const parsed = parseRepoUrl(config.url);
  const platformType = getPlatformType(config.url, config.platform);

  return {
    ...config,
    name,
    absolutePath: resolve(rootDir, config.path),
    owner: parsed.owner,
    repo: parsed.repo,
    platformType,
    project: parsed.project,
  };
}

/**
 * Get all repos as RepoInfo array
 */
export function getAllRepoInfo(manifest: Manifest, rootDir: string): RepoInfo[] {
  return Object.entries(manifest.repos).map(([name, config]) => getRepoInfo(name, config, rootDir));
}

/**
 * Get manifest repo as RepoInfo (if manifest.url is configured)
 * Returns null if manifest section is not configured, has no URL, or URL is invalid
 */
export function getManifestRepoInfo(manifest: Manifest, rootDir: string): RepoInfo | null {
  if (!manifest.manifest?.url) {
    return null;
  }

  const manifestsDir = getManifestsDir(rootDir);

  try {
    const parsed = parseRepoUrl(manifest.manifest.url);
    const platformType = getPlatformType(manifest.manifest.url, manifest.manifest.platform);

    return {
      name: 'manifest',
      url: manifest.manifest.url,
      path: `${GITGRIP_DIR}/manifests`,
      absolutePath: manifestsDir,
      default_branch: manifest.manifest.default_branch ?? 'main',
      owner: parsed.owner,
      repo: parsed.repo,
      platformType,
      project: parsed.project,
    };
  } catch {
    // Invalid URL format
    return null;
  }
}

/**
 * Get the state file path
 */
function getStatePath(rootDir: string): string {
  return join(getGitgripDir(rootDir), STATE_FILENAME);
}

/**
 * Load the state file
 */
export async function loadState(rootDir: string): Promise<StateFile> {
  const statePath = getStatePath(rootDir);
  try {
    const content = await readFile(statePath, 'utf-8');
    return JSON.parse(content) as StateFile;
  } catch {
    return {
      branchToPR: {},
      prLinks: {},
    };
  }
}

/**
 * Save the state file
 */
export async function saveState(rootDir: string, state: StateFile): Promise<void> {
  const statePath = getStatePath(rootDir);
  const stateDir = dirname(statePath);

  // Ensure state directory exists
  const { mkdir } = await import('fs/promises');
  await mkdir(stateDir, { recursive: true });

  await writeFile(statePath, JSON.stringify(state, null, 2), 'utf-8');
}

/**
 * Generate a sample manifest for init command
 */
export function generateSampleManifest(): Manifest {
  return {
    version: 1,
    repos: {
      public: {
        url: 'git@github.com:your-org/your-repo.git',
        path: './public',
        default_branch: 'main',
      },
      private: {
        url: 'git@github.com:your-org/your-private-repo.git',
        path: './private',
        default_branch: 'main',
      },
    },
    settings: {
      pr_prefix: '[cross-repo]',
      merge_strategy: 'all-or-nothing',
    },
  };
}

/**
 * Configuration for adding a new repo to the manifest
 */
export interface AddRepoConfig {
  url: string;
  path: string;
  default_branch: string;
}

/**
 * Add a repository to the manifest file
 * Note: Re-serializes the YAML, which may change formatting
 */
export async function addRepoToManifest(
  manifestPath: string,
  name: string,
  config: AddRepoConfig
): Promise<void> {
  const content = await readFile(manifestPath, 'utf-8');
  const manifest = YAML.parse(content) as Manifest;

  // Check if repo already exists
  if (manifest.repos[name]) {
    throw new Error(`Repository '${name}' already exists in manifest`);
  }

  // Add the new repo
  manifest.repos[name] = {
    url: config.url,
    path: config.path,
    default_branch: config.default_branch,
  };

  // Write back with consistent formatting
  const newContent = YAML.stringify(manifest, {
    indent: 2,
    lineWidth: 0,
  });
  await writeFile(manifestPath, newContent, 'utf-8');
}
