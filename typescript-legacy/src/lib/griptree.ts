import { readFile, writeFile, mkdir, readdir, rm, access } from 'fs/promises';
import path from 'path';
import type { GriptreeConfig, GriptreePointer } from '../types.js';
import { getGitgripDir } from './manifest.js';

const GRIPTREES_DIR = 'griptrees';
const GRIPTREE_CONFIG_FILE = 'config.json';
const GRIPTREE_POINTER_FILE = '.griptree';

/**
 * Sanitize branch name for use as directory name
 * Converts slashes to hyphens (e.g., feat/auth -> feat-auth)
 */
export function sanitizeBranchName(branch: string): string {
  return branch.replace(/\//g, '-');
}

/**
 * Get the path to the griptrees directory (.gitgrip/griptrees/)
 */
export function getGriptreesDir(rootDir: string): string {
  return path.join(getGitgripDir(rootDir), GRIPTREES_DIR);
}

/**
 * Get the path to a specific griptree's config directory
 */
export function getGriptreeConfigDir(rootDir: string, branch: string): string {
  return path.join(getGriptreesDir(rootDir), sanitizeBranchName(branch));
}

/**
 * Get the path to a specific griptree's config file
 */
export function getGriptreeConfigPath(rootDir: string, branch: string): string {
  return path.join(getGriptreeConfigDir(rootDir, branch), GRIPTREE_CONFIG_FILE);
}

/**
 * Get the path to a griptree's pointer file
 */
export function getGriptreePointerPath(treePath: string): string {
  return path.join(treePath, GRIPTREE_POINTER_FILE);
}

/**
 * Check if a path exists
 */
async function pathExists(p: string): Promise<boolean> {
  try {
    await access(p);
    return true;
  } catch {
    return false;
  }
}

/**
 * Read a griptree config from the central registry
 */
export async function readGriptreeConfig(rootDir: string, branch: string): Promise<GriptreeConfig | null> {
  const configPath = getGriptreeConfigPath(rootDir, branch);
  try {
    const content = await readFile(configPath, 'utf-8');
    return JSON.parse(content) as GriptreeConfig;
  } catch {
    return null;
  }
}

/**
 * Write a griptree config to the central registry
 */
export async function writeGriptreeConfig(rootDir: string, branch: string, config: GriptreeConfig): Promise<void> {
  const configDir = getGriptreeConfigDir(rootDir, branch);
  await mkdir(configDir, { recursive: true });
  const configPath = path.join(configDir, GRIPTREE_CONFIG_FILE);
  await writeFile(configPath, JSON.stringify(config, null, 2));
}

/**
 * Remove a griptree config from the central registry
 */
export async function removeGriptreeConfig(rootDir: string, branch: string): Promise<void> {
  const configDir = getGriptreeConfigDir(rootDir, branch);
  try {
    await rm(configDir, { recursive: true, force: true });
  } catch {
    // Ignore errors if already removed
  }
}

/**
 * Read all griptree configs from the central registry
 */
export async function readGriptreeRegistry(rootDir: string): Promise<GriptreeConfig[]> {
  const griptreesDir = getGriptreesDir(rootDir);
  const configs: GriptreeConfig[] = [];

  try {
    const entries = await readdir(griptreesDir, { withFileTypes: true });

    for (const entry of entries) {
      if (!entry.isDirectory()) continue;

      const configPath = path.join(griptreesDir, entry.name, GRIPTREE_CONFIG_FILE);
      try {
        const content = await readFile(configPath, 'utf-8');
        const config = JSON.parse(content) as GriptreeConfig;
        configs.push(config);
      } catch {
        // Skip invalid entries
      }
    }
  } catch {
    // Directory doesn't exist yet
  }

  return configs;
}

/**
 * Read a griptree pointer file from a griptree directory
 */
export async function readGriptreePointer(treePath: string): Promise<GriptreePointer | null> {
  const pointerPath = getGriptreePointerPath(treePath);
  try {
    const content = await readFile(pointerPath, 'utf-8');
    return JSON.parse(content) as GriptreePointer;
  } catch {
    return null;
  }
}

/**
 * Write a griptree pointer file to a griptree directory
 */
export async function writeGriptreePointer(treePath: string, pointer: GriptreePointer): Promise<void> {
  const pointerPath = getGriptreePointerPath(treePath);
  await writeFile(pointerPath, JSON.stringify(pointer, null, 2));
}

/**
 * Remove a griptree pointer file from a griptree directory
 */
export async function removeGriptreePointer(treePath: string): Promise<void> {
  const pointerPath = getGriptreePointerPath(treePath);
  try {
    await rm(pointerPath, { force: true });
  } catch {
    // Ignore errors if already removed
  }
}

/**
 * Legacy griptree config (old format stored in .griptree file in griptree directory)
 */
interface LegacyTreeConfig {
  branch: string;
  locked: boolean;
  createdAt: string;
}

/**
 * Find legacy griptrees by scanning sibling directories for .griptree files
 * Returns griptrees that are not in the central registry
 */
export async function findLegacyGriptrees(rootDir: string): Promise<{ path: string; config: LegacyTreeConfig }[]> {
  const parentDir = path.dirname(rootDir);
  const legacyTrees: { path: string; config: LegacyTreeConfig }[] = [];

  // Get registered branches to skip them
  const registeredConfigs = await readGriptreeRegistry(rootDir);
  const registeredPaths = new Set(registeredConfigs.map(c => c.path));

  try {
    const entries = await readdir(parentDir, { withFileTypes: true });

    for (const entry of entries) {
      if (!entry.isDirectory()) continue;

      const dirPath = path.join(parentDir, entry.name);

      // Skip if already registered
      if (registeredPaths.has(dirPath)) continue;

      // Skip the main workspace itself
      if (dirPath === rootDir) continue;

      const pointerPath = path.join(dirPath, GRIPTREE_POINTER_FILE);
      try {
        const content = await readFile(pointerPath, 'utf-8');
        const parsed = JSON.parse(content);

        // Check if it's a legacy format (has branch and locked, but no mainWorkspace)
        // OR if it's a new pointer format pointing to this workspace
        if (parsed.branch) {
          if (parsed.mainWorkspace === rootDir) {
            // New format pointer pointing to this workspace but not in registry
            // This shouldn't happen normally, but handle it
            legacyTrees.push({
              path: dirPath,
              config: {
                branch: parsed.branch,
                locked: false,
                createdAt: new Date().toISOString(),
              },
            });
          } else if (!parsed.mainWorkspace) {
            // Legacy format
            legacyTrees.push({
              path: dirPath,
              config: parsed as LegacyTreeConfig,
            });
          }
        }
      } catch {
        // Not a griptree directory
      }
    }
  } catch {
    // Parent directory read failed
  }

  return legacyTrees;
}

/**
 * Register a legacy griptree in the central registry
 */
export async function registerLegacyGriptree(
  rootDir: string,
  treePath: string,
  legacyConfig: LegacyTreeConfig
): Promise<GriptreeConfig> {
  const config: GriptreeConfig = {
    branch: legacyConfig.branch,
    path: treePath,
    createdAt: legacyConfig.createdAt,
    locked: legacyConfig.locked,
  };

  // Write to central registry
  await writeGriptreeConfig(rootDir, legacyConfig.branch, config);

  // Update the .griptree file to new pointer format
  const pointer: GriptreePointer = {
    mainWorkspace: rootDir,
    branch: legacyConfig.branch,
  };
  await writeGriptreePointer(treePath, pointer);

  return config;
}

/**
 * Check if a griptree's path still exists (detect orphans)
 */
export async function isGriptreePathValid(config: GriptreeConfig): Promise<boolean> {
  return pathExists(config.path);
}

/**
 * Find a griptree by branch name in the central registry
 */
export async function findGriptreeByBranch(
  rootDir: string,
  branch: string
): Promise<GriptreeConfig | null> {
  return readGriptreeConfig(rootDir, branch);
}

/**
 * Get the default griptree path for a branch
 */
export function getDefaultGriptreePath(rootDir: string, branch: string): string {
  const parentDir = path.dirname(rootDir);
  const sanitized = sanitizeBranchName(branch);
  return path.join(parentDir, sanitized);
}
