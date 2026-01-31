/**
 * Platform abstraction for multi-platform hosting support
 *
 * This module provides a unified interface for working with different
 * git hosting platforms (GitHub, GitLab, Azure DevOps).
 */

export * from './types.js';
export { GitHubPlatform, getGitHubPlatform, createGitHubPlatform } from './github.js';
export { GitLabPlatform, createGitLabPlatform } from './gitlab.js';
export { AzureDevOpsPlatform, createAzureDevOpsPlatform } from './azure-devops.js';

import type { HostingPlatform, PlatformType, PlatformConfig, ParsedRepoInfo } from './types.js';
import { GitHubPlatform } from './github.js';
import { GitLabPlatform } from './gitlab.js';
import { AzureDevOpsPlatform } from './azure-devops.js';

// Cache of platform instances by type and baseUrl
const platformCache = new Map<string, HostingPlatform>();

/**
 * Detect the platform type from a git URL
 *
 * @param url - Git URL (SSH or HTTPS format)
 * @returns The detected platform type, or null if unknown
 */
export function detectPlatform(url: string): PlatformType | null {
  // GitHub detection (most common, check first)
  if (url.includes('github.com')) {
    return 'github';
  }

  // Azure DevOps detection (check before GitLab to avoid false positives)
  if (
    url.includes('dev.azure.com') ||
    url.includes('visualstudio.com') ||
    url.includes('ssh.dev.azure.com')
  ) {
    return 'azure-devops';
  }

  // GitLab detection - check for gitlab.com or gitlab in hostname (not in path)
  // This avoids false positives like "git@myserver.com:my-gitlab-clone/repo.git"
  if (url.includes('gitlab.com')) {
    return 'gitlab';
  }
  // Match URLs where "gitlab" appears in the hostname portion
  // e.g., git@gitlab.company.com: or https://gitlab.company.com/
  if (/(?:@|:\/\/)gitlab\./i.test(url)) {
    return 'gitlab';
  }

  return null;
}

/**
 * Get a platform adapter for the specified type
 *
 * Uses caching to return the same instance for identical configurations.
 *
 * @param type - Platform type
 * @param config - Optional platform configuration (for self-hosted instances)
 * @returns Platform adapter instance
 */
export function getPlatformAdapter(
  type: PlatformType,
  config?: PlatformConfig
): HostingPlatform {
  // Create cache key based on type and baseUrl
  const cacheKey = `${type}:${config?.baseUrl ?? 'default'}`;

  // Check cache first
  let platform = platformCache.get(cacheKey);
  if (platform) {
    return platform;
  }

  // Create new instance
  const platformConfig: PlatformConfig = { type, ...config };

  switch (type) {
    case 'github':
      platform = new GitHubPlatform(platformConfig);
      break;
    case 'gitlab':
      platform = new GitLabPlatform(platformConfig);
      break;
    case 'azure-devops':
      platform = new AzureDevOpsPlatform(platformConfig);
      break;
    default:
      throw new Error(`Unknown platform type: ${type}`);
  }

  // Cache and return
  platformCache.set(cacheKey, platform);
  return platform;
}

/**
 * Get a platform adapter for a specific git URL
 *
 * Auto-detects the platform from the URL.
 *
 * @param url - Git URL (SSH or HTTPS format)
 * @param config - Optional platform configuration (for self-hosted instances)
 * @returns Platform adapter instance
 * @throws Error if platform cannot be detected
 */
export function getPlatformForUrl(
  url: string,
  config?: PlatformConfig
): HostingPlatform {
  const type = detectPlatform(url);
  if (!type) {
    throw new Error(
      `Unable to detect hosting platform from URL: ${url}. ` +
      `Supported platforms: GitHub, GitLab, Azure DevOps`
    );
  }

  return getPlatformAdapter(type, config);
}

/**
 * Parse a git URL using the appropriate platform adapter
 *
 * @param url - Git URL (SSH or HTTPS format)
 * @returns Parsed repository info, or null if URL format is not recognized
 */
export function parseRepoUrl(url: string): (ParsedRepoInfo & { platform: PlatformType }) | null {
  const type = detectPlatform(url);
  if (!type) {
    return null;
  }

  const platform = getPlatformAdapter(type);
  const parsed = platform.parseRepoUrl(url);

  if (!parsed) {
    return null;
  }

  return { ...parsed, platform: type };
}

/**
 * Check if a URL belongs to a supported hosting platform
 *
 * @param url - Git URL to check
 * @returns true if the URL is from a supported platform
 */
export function isSupportedUrl(url: string): boolean {
  return detectPlatform(url) !== null;
}

/**
 * Clear the platform cache (useful for testing)
 */
export function clearPlatformCache(): void {
  platformCache.clear();
}
