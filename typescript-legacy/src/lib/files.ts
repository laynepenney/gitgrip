import { copyFile as fsCopyFile, symlink, readlink, unlink, stat, mkdir, access, rm } from 'fs/promises';
import { resolve, dirname, relative, join, isAbsolute, normalize } from 'path';
import type { Manifest, RepoConfig, LinkStatus, CopyFileConfig, LinkFileConfig } from '../types.js';

/**
 * Check if a path exists
 */
async function pathExists(path: string): Promise<boolean> {
  try {
    await access(path);
    return true;
  } catch {
    return false;
  }
}

/**
 * Check if a path is a symlink
 */
async function isSymlink(path: string): Promise<boolean> {
  try {
    // Use lstat to detect symlink (stat follows the link)
    const { lstat } = await import('fs/promises');
    const stats = await lstat(path);
    return stats.isSymbolicLink();
  } catch {
    return false;
  }
}

/**
 * Validate that a path does not escape its boundary
 */
export function validatePath(basePath: string, targetPath: string): boolean {
  const normalizedBase = normalize(resolve(basePath));
  const normalizedTarget = normalize(resolve(basePath, targetPath));
  return normalizedTarget.startsWith(normalizedBase);
}

/**
 * Ensure directory exists for a file path
 */
async function ensureDir(filePath: string): Promise<void> {
  const dir = dirname(filePath);
  await mkdir(dir, { recursive: true });
}

export interface CopyFileOptions {
  /** Create backup of existing file */
  backup?: boolean;
  /** Overwrite existing file */
  force?: boolean;
  /** Preview only, don't actually copy */
  dryRun?: boolean;
}

/**
 * Copy a file from source to destination
 */
export async function copyFile(
  src: string,
  dest: string,
  options: CopyFileOptions = {}
): Promise<{ copied: boolean; backupPath?: string; message?: string }> {
  const { backup = false, force = false, dryRun = false } = options;

  // Check source exists
  if (!(await pathExists(src))) {
    return { copied: false, message: `Source does not exist: ${src}` };
  }

  // Check if destination exists
  const destExists = await pathExists(dest);

  if (destExists && !force) {
    return { copied: false, message: `Destination exists: ${dest} (use --force to overwrite)` };
  }

  if (dryRun) {
    return { copied: true, message: `Would copy ${src} -> ${dest}` };
  }

  // Create backup if needed
  let backupPath: string | undefined;
  if (destExists && backup) {
    backupPath = `${dest}.backup.${Date.now()}`;
    await fsCopyFile(dest, backupPath);
  }

  // Ensure destination directory exists
  await ensureDir(dest);

  // Copy the file
  await fsCopyFile(src, dest);

  return { copied: true, backupPath };
}

export interface CreateSymlinkOptions {
  /** Overwrite existing link/file */
  force?: boolean;
  /** Preview only, don't actually create */
  dryRun?: boolean;
}

/**
 * Create a relative symlink from dest pointing to src
 */
export async function createSymlink(
  src: string,
  dest: string,
  options: CreateSymlinkOptions = {}
): Promise<{ created: boolean; message?: string }> {
  const { force = false, dryRun = false } = options;

  // Check source exists
  if (!(await pathExists(src))) {
    return { created: false, message: `Source does not exist: ${src}` };
  }

  // Check if destination exists
  const destExists = await pathExists(dest);
  const destIsLink = await isSymlink(dest);

  if (destExists || destIsLink) {
    if (!force) {
      return { created: false, message: `Destination exists: ${dest} (use --force to overwrite)` };
    }

    if (!dryRun) {
      await unlink(dest);
    }
  }

  if (dryRun) {
    return { created: true, message: `Would link ${dest} -> ${src}` };
  }

  // Ensure destination directory exists
  await ensureDir(dest);

  // Calculate relative path from dest to src
  const destDir = dirname(dest);
  const relativePath = relative(destDir, src);

  // Create symlink
  await symlink(relativePath, dest);

  return { created: true };
}

/**
 * Get the status of a single link
 */
export async function getLinkStatus(
  type: 'copyfile' | 'linkfile',
  repoName: string,
  src: string,
  dest: string
): Promise<LinkStatus> {
  const srcExists = await pathExists(src);
  const destExists = await pathExists(dest);
  const destIsLink = await isSymlink(dest);

  if (!srcExists) {
    return {
      type,
      repoName,
      src,
      dest,
      status: 'broken',
      message: 'Source does not exist',
    };
  }

  if (!destExists && !destIsLink) {
    return {
      type,
      repoName,
      src,
      dest,
      status: 'missing',
      message: 'Destination not created',
    };
  }

  if (type === 'linkfile') {
    if (!destIsLink) {
      return {
        type,
        repoName,
        src,
        dest,
        status: 'conflict',
        message: 'Destination exists but is not a symlink',
      };
    }

    // Check if symlink points to correct location
    try {
      const linkTarget = await readlink(dest);
      const destDir = dirname(dest);
      const resolvedTarget = resolve(destDir, linkTarget);
      const resolvedSrc = resolve(src);

      if (resolvedTarget !== resolvedSrc) {
        return {
          type,
          repoName,
          src,
          dest,
          status: 'broken',
          message: `Symlink points to wrong target: ${linkTarget}`,
        };
      }
    } catch {
      return {
        type,
        repoName,
        src,
        dest,
        status: 'broken',
        message: 'Cannot read symlink target',
      };
    }
  }

  return {
    type,
    repoName,
    src,
    dest,
    status: 'valid',
  };
}

export interface ProcessLinksOptions {
  force?: boolean;
  dryRun?: boolean;
}

export interface ProcessLinksResult {
  repoName: string;
  copyfiles: { src: string; dest: string; success: boolean; message?: string }[];
  linkfiles: { src: string; dest: string; success: boolean; message?: string }[];
}

/**
 * Process all copyfile and linkfile entries for a repository
 */
export async function processRepoLinks(
  repoName: string,
  repoConfig: RepoConfig,
  repoPath: string,
  rootDir: string,
  options: ProcessLinksOptions = {}
): Promise<ProcessLinksResult> {
  const result: ProcessLinksResult = {
    repoName,
    copyfiles: [],
    linkfiles: [],
  };

  // Process copyfiles
  if (repoConfig.copyfile) {
    for (const config of repoConfig.copyfile) {
      const src = resolve(repoPath, config.src);
      const dest = resolve(rootDir, config.dest);

      // Validate paths
      if (!validatePath(repoPath, config.src)) {
        result.copyfiles.push({
          src,
          dest,
          success: false,
          message: 'Source path escapes repository boundary',
        });
        continue;
      }

      if (!validatePath(rootDir, config.dest)) {
        result.copyfiles.push({
          src,
          dest,
          success: false,
          message: 'Destination path escapes workspace boundary',
        });
        continue;
      }

      const copyResult = await copyFile(src, dest, {
        force: options.force,
        dryRun: options.dryRun,
      });

      result.copyfiles.push({
        src,
        dest,
        success: copyResult.copied,
        message: copyResult.message,
      });
    }
  }

  // Process linkfiles
  if (repoConfig.linkfile) {
    for (const config of repoConfig.linkfile) {
      const src = resolve(repoPath, config.src);
      const dest = resolve(rootDir, config.dest);

      // Validate paths
      if (!validatePath(repoPath, config.src)) {
        result.linkfiles.push({
          src,
          dest,
          success: false,
          message: 'Source path escapes repository boundary',
        });
        continue;
      }

      if (!validatePath(rootDir, config.dest)) {
        result.linkfiles.push({
          src,
          dest,
          success: false,
          message: 'Destination path escapes workspace boundary',
        });
        continue;
      }

      const linkResult = await createSymlink(src, dest, {
        force: options.force,
        dryRun: options.dryRun,
      });

      result.linkfiles.push({
        src,
        dest,
        success: linkResult.created,
        message: linkResult.message,
      });
    }
  }

  return result;
}

/**
 * Process links for manifest-level copyfile/linkfile entries
 */
export async function processManifestLinks(
  manifest: Manifest,
  manifestsDir: string,
  rootDir: string,
  options: ProcessLinksOptions = {}
): Promise<ProcessLinksResult> {
  const result: ProcessLinksResult = {
    repoName: 'manifest',
    copyfiles: [],
    linkfiles: [],
  };

  if (!manifest.manifest) {
    return result;
  }

  // Process manifest copyfiles
  if (manifest.manifest.copyfile) {
    for (const config of manifest.manifest.copyfile) {
      const src = resolve(manifestsDir, config.src);
      const dest = resolve(rootDir, config.dest);

      // Validate paths
      if (!validatePath(manifestsDir, config.src)) {
        result.copyfiles.push({
          src,
          dest,
          success: false,
          message: 'Source path escapes manifest boundary',
        });
        continue;
      }

      if (!validatePath(rootDir, config.dest)) {
        result.copyfiles.push({
          src,
          dest,
          success: false,
          message: 'Destination path escapes workspace boundary',
        });
        continue;
      }

      const copyResult = await copyFile(src, dest, {
        force: options.force,
        dryRun: options.dryRun,
      });

      result.copyfiles.push({
        src,
        dest,
        success: copyResult.copied,
        message: copyResult.message,
      });
    }
  }

  // Process manifest linkfiles
  if (manifest.manifest.linkfile) {
    for (const config of manifest.manifest.linkfile) {
      const src = resolve(manifestsDir, config.src);
      const dest = resolve(rootDir, config.dest);

      // Validate paths
      if (!validatePath(manifestsDir, config.src)) {
        result.linkfiles.push({
          src,
          dest,
          success: false,
          message: 'Source path escapes manifest boundary',
        });
        continue;
      }

      if (!validatePath(rootDir, config.dest)) {
        result.linkfiles.push({
          src,
          dest,
          success: false,
          message: 'Destination path escapes workspace boundary',
        });
        continue;
      }

      const linkResult = await createSymlink(src, dest, {
        force: options.force,
        dryRun: options.dryRun,
      });

      result.linkfiles.push({
        src,
        dest,
        success: linkResult.created,
        message: linkResult.message,
      });
    }
  }

  return result;
}

/**
 * Process all links for all repositories and manifest
 */
export async function processAllLinks(
  manifest: Manifest,
  rootDir: string,
  options: ProcessLinksOptions = {},
  manifestsDir?: string
): Promise<ProcessLinksResult[]> {
  const results: ProcessLinksResult[] = [];

  // Process manifest-level links first
  if (manifestsDir) {
    const manifestResult = await processManifestLinks(manifest, manifestsDir, rootDir, options);
    if (manifestResult.copyfiles.length > 0 || manifestResult.linkfiles.length > 0) {
      results.push(manifestResult);
    }
  }

  // Process repo-level links
  for (const [repoName, repoConfig] of Object.entries(manifest.repos)) {
    const repoPath = resolve(rootDir, repoConfig.path);
    const result = await processRepoLinks(repoName, repoConfig, repoPath, rootDir, options);
    results.push(result);
  }

  return results;
}

/**
 * Get status of all links (including manifest-level links)
 */
export async function getAllLinkStatus(
  manifest: Manifest,
  rootDir: string,
  manifestsDir?: string
): Promise<LinkStatus[]> {
  const statuses: LinkStatus[] = [];

  // Get manifest-level link statuses
  if (manifestsDir && manifest.manifest) {
    if (manifest.manifest.copyfile) {
      for (const config of manifest.manifest.copyfile) {
        const src = resolve(manifestsDir, config.src);
        const dest = resolve(rootDir, config.dest);
        const status = await getLinkStatus('copyfile', 'manifest', src, dest);
        statuses.push(status);
      }
    }

    if (manifest.manifest.linkfile) {
      for (const config of manifest.manifest.linkfile) {
        const src = resolve(manifestsDir, config.src);
        const dest = resolve(rootDir, config.dest);
        const status = await getLinkStatus('linkfile', 'manifest', src, dest);
        statuses.push(status);
      }
    }
  }

  // Get repo-level link statuses
  for (const [repoName, repoConfig] of Object.entries(manifest.repos)) {
    const repoPath = resolve(rootDir, repoConfig.path);

    if (repoConfig.copyfile) {
      for (const config of repoConfig.copyfile) {
        const src = resolve(repoPath, config.src);
        const dest = resolve(rootDir, config.dest);
        const status = await getLinkStatus('copyfile', repoName, src, dest);
        statuses.push(status);
      }
    }

    if (repoConfig.linkfile) {
      for (const config of repoConfig.linkfile) {
        const src = resolve(repoPath, config.src);
        const dest = resolve(rootDir, config.dest);
        const status = await getLinkStatus('linkfile', repoName, src, dest);
        statuses.push(status);
      }
    }
  }

  return statuses;
}

/**
 * Find and remove orphaned links (links that exist but are no longer in manifest)
 */
export async function cleanOrphanedLinks(
  manifest: Manifest,
  rootDir: string,
  options: { dryRun?: boolean } = {}
): Promise<{ path: string; removed: boolean; message?: string }[]> {
  const results: { path: string; removed: boolean; message?: string }[] = [];

  // Get all currently defined destinations
  const definedDests = new Set<string>();

  // Add manifest-level destinations
  if (manifest.manifest) {
    if (manifest.manifest.copyfile) {
      for (const config of manifest.manifest.copyfile) {
        definedDests.add(resolve(rootDir, config.dest));
      }
    }
    if (manifest.manifest.linkfile) {
      for (const config of manifest.manifest.linkfile) {
        definedDests.add(resolve(rootDir, config.dest));
      }
    }
  }

  // Add repo-level destinations
  for (const repoConfig of Object.values(manifest.repos)) {
    if (repoConfig.copyfile) {
      for (const config of repoConfig.copyfile) {
        definedDests.add(resolve(rootDir, config.dest));
      }
    }
    if (repoConfig.linkfile) {
      for (const config of repoConfig.linkfile) {
        definedDests.add(resolve(rootDir, config.dest));
      }
    }
  }

  // Check common link locations for orphans
  // This is a simplified implementation - in a full impl you'd track links in state
  const linkDirs = [
    join(rootDir, '.bin'),
  ];

  for (const linkDir of linkDirs) {
    if (!(await pathExists(linkDir))) continue;

    const { readdir } = await import('fs/promises');
    try {
      const entries = await readdir(linkDir, { withFileTypes: true });
      for (const entry of entries) {
        const fullPath = join(linkDir, entry.name);
        if (await isSymlink(fullPath)) {
          if (!definedDests.has(fullPath)) {
            if (options.dryRun) {
              results.push({
                path: fullPath,
                removed: false,
                message: `Would remove orphaned link: ${fullPath}`,
              });
            } else {
              try {
                await unlink(fullPath);
                results.push({ path: fullPath, removed: true });
              } catch (error) {
                results.push({
                  path: fullPath,
                  removed: false,
                  message: `Failed to remove: ${error instanceof Error ? error.message : String(error)}`,
                });
              }
            }
          }
        }
      }
    } catch {
      // Directory may not be readable
    }
  }

  return results;
}
