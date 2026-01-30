import type { LinkedPR, ManifestPR, RepoInfo, CheckStatusDetails } from '../types.js';
import { getPlatformAdapter } from './platform/index.js';
import { loadState, saveState, getAllRepoInfo } from './manifest.js';
import type { Manifest } from '../types.js';

/**
 * Link a branch to a manifest PR in state
 */
export async function linkBranchToManifestPR(
  rootDir: string,
  branchName: string,
  manifestPRNumber: number
): Promise<void> {
  const state = await loadState(rootDir);
  state.branchToPR[branchName] = manifestPRNumber;
  state.currentManifestPR = manifestPRNumber;
  await saveState(rootDir, state);
}

/**
 * Save linked PRs for a manifest PR
 */
export async function saveLinkedPRs(
  rootDir: string,
  manifestPRNumber: number,
  linkedPRs: LinkedPR[]
): Promise<void> {
  const state = await loadState(rootDir);
  state.prLinks[manifestPRNumber] = linkedPRs;
  await saveState(rootDir, state);
}

/**
 * Get the manifest PR number for a branch
 */
export async function getManifestPRForBranch(
  rootDir: string,
  branchName: string
): Promise<number | undefined> {
  const state = await loadState(rootDir);
  return state.branchToPR[branchName];
}

/**
 * Get linked PRs for a manifest PR from state
 */
export async function getLinkedPRsFromState(
  rootDir: string,
  manifestPRNumber: number
): Promise<LinkedPR[] | undefined> {
  const state = await loadState(rootDir);
  return state.prLinks[manifestPRNumber];
}

/**
 * Get linked PR info using the appropriate platform adapter
 */
export async function getLinkedPRInfo(
  repoInfo: RepoInfo,
  prNumber: number
): Promise<LinkedPR> {
  const platform = getPlatformAdapter(repoInfo.platformType, repoInfo.platform);
  const pr = await platform.getPullRequest(repoInfo.owner, repoInfo.repo, prNumber);
  const approved = await platform.isPullRequestApproved(repoInfo.owner, repoInfo.repo, prNumber);
  const checks = await platform.getStatusChecks(repoInfo.owner, repoInfo.repo, pr.head.sha);

  let state: 'open' | 'closed' | 'merged';
  if (pr.merged) {
    state = 'merged';
  } else {
    state = pr.state;
  }

  // Calculate detailed check status
  const checkDetails: CheckStatusDetails = {
    state: checks.state,
    passed: 0,
    failed: 0,
    pending: 0,
    skipped: 0,
    total: checks.statuses.length,
  };

  for (const status of checks.statuses) {
    if (status.state === 'success') {
      checkDetails.passed++;
    } else if (status.state === 'failure') {
      checkDetails.failed++;
    } else if (status.state === 'pending') {
      checkDetails.pending++;
    } else if (status.state === 'skipped') {
      checkDetails.skipped++;
    }
  }

  return {
    repoName: repoInfo.name,
    owner: repoInfo.owner,
    repo: repoInfo.repo,
    number: pr.number,
    url: pr.url,
    state,
    approved,
    checksPass: checks.state === 'success',
    mergeable: pr.mergeable ?? false,
    platformType: repoInfo.platformType,
    checkDetails,
  };
}

/**
 * Refresh linked PR status from their respective platforms
 */
export async function refreshLinkedPRStatus(
  manifest: Manifest,
  rootDir: string,
  linkedPRs: LinkedPR[]
): Promise<LinkedPR[]> {
  const repos = getAllRepoInfo(manifest, rootDir);
  const repoMap = new Map(repos.map((r) => [r.name, r]));

  const refreshed = await Promise.all(
    linkedPRs.map(async (pr) => {
      const repoInfo = repoMap.get(pr.repoName);
      if (!repoInfo) {
        return pr; // Keep old info if repo not found
      }
      return getLinkedPRInfo(repoInfo, pr.number);
    })
  );

  return refreshed;
}

/**
 * Get full manifest PR info with refreshed linked PR status
 */
export async function getManifestPRInfo(
  manifest: Manifest,
  rootDir: string,
  manifestRepoInfo: RepoInfo,
  manifestPRNumber: number
): Promise<ManifestPR> {
  const platform = getPlatformAdapter(manifestRepoInfo.platformType, manifestRepoInfo.platform);
  const pr = await platform.getPullRequest(manifestRepoInfo.owner, manifestRepoInfo.repo, manifestPRNumber);

  // Parse linked PRs from body
  const parsedLinks = platform.parseLinkedPRComment(pr.body);
  const repos = getAllRepoInfo(manifest, rootDir);
  const repoMap = new Map(repos.map((r) => [r.name, r]));

  // Get fresh status for each linked PR
  const linkedPRs = await Promise.all(
    parsedLinks.map(async ({ repoName, number }) => {
      const repoInfo = repoMap.get(repoName);
      if (!repoInfo) {
        // Return placeholder if repo not in manifest
        return {
          repoName,
          owner: '',
          repo: '',
          number,
          url: '',
          state: 'closed' as const,
          approved: false,
          checksPass: false,
          mergeable: false,
        };
      }
      return getLinkedPRInfo(repoInfo, number);
    })
  );

  // Determine overall state
  let state: 'open' | 'closed' | 'merged';
  if (pr.merged) {
    state = 'merged';
  } else {
    state = pr.state;
  }

  // Check if ready to merge (all linked PRs approved and checks pass)
  const readyToMerge =
    state === 'open' &&
    linkedPRs.every((p) => p.approved && p.checksPass && p.mergeable && p.state === 'open');

  return {
    number: pr.number,
    url: pr.url,
    title: pr.title,
    linkedPRs,
    state,
    readyToMerge,
  };
}

/**
 * Generate manifest PR body with linked PR table
 */
export function generateManifestPRBody(
  title: string,
  linkedPRs: LinkedPR[],
  additionalBody?: string
): string {
  const prTable = linkedPRs
    .map((pr) => {
      const statusIcon = pr.state === 'merged' ? ':white_check_mark:' : pr.state === 'open' ? ':hourglass:' : ':x:';
      const approvalIcon = pr.approved ? ':white_check_mark:' : ':hourglass:';
      const checksIcon = pr.checksPass ? ':white_check_mark:' : ':hourglass:';
      return `| ${pr.repoName} | [#${pr.number}](${pr.url}) | ${statusIcon} ${pr.state} | ${approvalIcon} | ${checksIcon} |`;
    })
    .join('\n');

  // Generate linked PR comment (platform-agnostic format)
  const prLinks = linkedPRs.map((pr) => `${pr.repoName}#${pr.number}`).join(',');

  return `## Cross-Repository PR

${additionalBody ?? ''}

### Linked Pull Requests

| Repository | PR | Status | Approved | Checks |
|------------|-----|--------|----------|--------|
${prTable}

**Merge Policy:** All-or-nothing - all linked PRs must be approved before merge.

---
<!-- codi-repo:links:${prLinks} -->
`;
}

/**
 * Parse linked PRs from manifest PR body (platform-agnostic)
 */
export function parseLinkedPRsFromBody(body: string): { repoName: string; number: number }[] {
  const match = body.match(/<!-- codi-repo:links:(.+?) -->/);
  if (!match) {
    return [];
  }

  const links = match[1].split(',');
  return links.map((link) => {
    // Handle both # (GitHub) and ! (GitLab) separators
    const [repoName, numStr] = link.split(/[#!]/);
    return { repoName, number: parseInt(numStr, 10) };
  });
}

/**
 * Update manifest PR body with current linked PR status
 */
export async function syncManifestPRBody(
  manifest: Manifest,
  rootDir: string,
  manifestRepoInfo: RepoInfo,
  manifestPRNumber: number
): Promise<void> {
  const manifestPR = await getManifestPRInfo(
    manifest,
    rootDir,
    manifestRepoInfo,
    manifestPRNumber
  );

  const platform = getPlatformAdapter(manifestRepoInfo.platformType, manifestRepoInfo.platform);

  // Get original PR for title
  const pr = await platform.getPullRequest(manifestRepoInfo.owner, manifestRepoInfo.repo, manifestPRNumber);

  // Generate updated body
  const newBody = generateManifestPRBody(pr.title, manifestPR.linkedPRs);

  // Update PR
  await platform.updatePullRequestBody(manifestRepoInfo.owner, manifestRepoInfo.repo, manifestPRNumber, newBody);
}

/**
 * Merge all linked PRs in order, then merge manifest PR
 */
export async function mergeAllLinkedPRs(
  manifest: Manifest,
  rootDir: string,
  manifestRepoInfo: RepoInfo,
  manifestPRNumber: number,
  options: { method?: 'merge' | 'squash' | 'rebase'; deleteBranch?: boolean } = {}
): Promise<{
  success: boolean;
  mergedPRs: { repoName: string; number: number }[];
  failedPR?: { repoName: string; number: number; error: string };
}> {
  const manifestPR = await getManifestPRInfo(
    manifest,
    rootDir,
    manifestRepoInfo,
    manifestPRNumber
  );

  if (!manifestPR.readyToMerge) {
    const notReady = manifestPR.linkedPRs.find(
      (p) => !p.approved || !p.checksPass || !p.mergeable || p.state !== 'open'
    );
    return {
      success: false,
      mergedPRs: [],
      failedPR: notReady
        ? {
            repoName: notReady.repoName,
            number: notReady.number,
            error: !notReady.approved
              ? 'Not approved'
              : !notReady.checksPass
                ? 'Checks not passing'
                : !notReady.mergeable
                  ? 'Not mergeable'
                  : 'PR not open',
          }
        : undefined,
    };
  }

  const repos = getAllRepoInfo(manifest, rootDir);
  const repoMap = new Map(repos.map((r) => [r.name, r]));

  const mergedPRs: { repoName: string; number: number }[] = [];

  // Merge each linked PR using the appropriate platform
  for (const linkedPR of manifestPR.linkedPRs) {
    const repoInfo = repoMap.get(linkedPR.repoName);
    if (!repoInfo) {
      return {
        success: false,
        mergedPRs,
        failedPR: {
          repoName: linkedPR.repoName,
          number: linkedPR.number,
          error: 'Repository not found in manifest',
        },
      };
    }

    const platform = getPlatformAdapter(repoInfo.platformType, repoInfo.platform);
    const merged = await platform.mergePullRequest(linkedPR.owner, linkedPR.repo, linkedPR.number, options);
    if (!merged) {
      return {
        success: false,
        mergedPRs,
        failedPR: {
          repoName: linkedPR.repoName,
          number: linkedPR.number,
          error: 'Merge failed',
        },
      };
    }
    mergedPRs.push({ repoName: linkedPR.repoName, number: linkedPR.number });
  }

  // Merge manifest PR
  const manifestPlatform = getPlatformAdapter(manifestRepoInfo.platformType, manifestRepoInfo.platform);
  const manifestMerged = await manifestPlatform.mergePullRequest(
    manifestRepoInfo.owner,
    manifestRepoInfo.repo,
    manifestPRNumber,
    options
  );
  if (!manifestMerged) {
    return {
      success: false,
      mergedPRs,
      failedPR: {
        repoName: 'manifest',
        number: manifestPRNumber,
        error: 'Manifest PR merge failed',
      },
    };
  }

  mergedPRs.push({ repoName: 'manifest', number: manifestPRNumber });

  return {
    success: true,
    mergedPRs,
  };
}

/**
 * Check if all linked PRs are in sync (same branch name exists)
 */
export async function checkBranchSync(
  repos: RepoInfo[],
  branchName: string
): Promise<{ inSync: boolean; missing: string[] }> {
  const { branchExists } = await import('./git.js');

  const results = await Promise.all(
    repos.map(async (repo) => {
      const exists = await branchExists(repo.absolutePath, branchName);
      return { name: repo.name, exists };
    })
  );

  const missing = results.filter((r) => !r.exists).map((r) => r.name);

  return {
    inSync: missing.length === 0,
    missing,
  };
}
