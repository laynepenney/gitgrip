/**
 * Griptree E2E tests
 *
 * Tests the full griptree workflow with real git operations:
 * - Creating griptrees with worktrees
 * - File links (copyfile/linkfile) in griptrees
 * - Listing griptrees
 * - Locking/unlocking
 * - Removing griptrees
 * - Legacy migration
 * - Orphan detection/cleanup
 *
 * Run with: GRIPTREE_E2E=1 npx vitest run src/lib/__tests__/griptree.e2e.test.ts
 */

import { describe, it, expect, beforeAll, afterAll, beforeEach, afterEach } from 'vitest';
import { mkdir, rm, writeFile, readFile, access, readlink, symlink } from 'fs/promises';
import { join, relative } from 'path';
import { tmpdir } from 'os';
import { execSync } from 'child_process';
import {
  readGriptreeConfig,
  readGriptreeRegistry,
  readGriptreePointer,
  writeGriptreeConfig,
  removeGriptreeConfig,
  findLegacyGriptrees,
} from '../griptree.js';
import type { GriptreeConfig } from '../../types.js';

const runE2E = process.env.GRIPTREE_E2E === '1';

// Helper to run git commands
function git(cwd: string, args: string): string {
  return execSync(`git ${args}`, { cwd, encoding: 'utf-8' }).trim();
}

// Helper to check if path exists
async function pathExists(p: string): Promise<boolean> {
  try {
    await access(p);
    return true;
  } catch {
    return false;
  }
}

describe.skipIf(!runE2E)('Griptree E2E Tests', () => {
  let testDir: string;
  let workspaceDir: string;
  let repo1Dir: string;
  let repo2Dir: string;
  let manifestDir: string;

  beforeAll(async () => {
    // Create a complete test workspace structure
    testDir = join(tmpdir(), `gitgrip-griptree-e2e-${Date.now()}`);
    workspaceDir = join(testDir, 'main-workspace');
    repo1Dir = join(workspaceDir, 'repo1');
    repo2Dir = join(workspaceDir, 'repo2');
    manifestDir = join(workspaceDir, '.gitgrip', 'manifests');

    // Create workspace structure
    await mkdir(workspaceDir, { recursive: true });
    await mkdir(join(workspaceDir, '.gitgrip'), { recursive: true });

    // Initialize repo1
    await mkdir(repo1Dir, { recursive: true });
    git(repo1Dir, 'init');
    git(repo1Dir, 'config user.email "test@test.com"');
    git(repo1Dir, 'config user.name "Test User"');
    await writeFile(join(repo1Dir, 'README.md'), '# Repo 1');
    await writeFile(join(repo1Dir, 'SHARED.md'), '# Shared file for linking');
    git(repo1Dir, 'add .');
    git(repo1Dir, 'commit -m "Initial commit"');

    // Initialize repo2
    await mkdir(repo2Dir, { recursive: true });
    git(repo2Dir, 'init');
    git(repo2Dir, 'config user.email "test@test.com"');
    git(repo2Dir, 'config user.name "Test User"');
    await writeFile(join(repo2Dir, 'README.md'), '# Repo 2');
    git(repo2Dir, 'add .');
    git(repo2Dir, 'commit -m "Initial commit"');

    // Initialize manifest repo
    await mkdir(manifestDir, { recursive: true });
    git(manifestDir, 'init');
    git(manifestDir, 'config user.email "test@test.com"');
    git(manifestDir, 'config user.name "Test User"');

    // Create manifest.yaml with linkfile config
    const manifest = `
version: 1
manifest:
  url: git@github.com:test/manifests.git
  default_branch: main
  linkfile:
    - src: CLAUDE.md
      dest: CLAUDE.md
repos:
  repo1:
    url: git@github.com:test/repo1.git
    path: ./repo1
    default_branch: main
    linkfile:
      - src: SHARED.md
        dest: SHARED.md
  repo2:
    url: git@github.com:test/repo2.git
    path: ./repo2
    default_branch: main
settings:
  pr_prefix: "[test]"
  merge_strategy: all-or-nothing
`;
    await writeFile(join(manifestDir, 'manifest.yaml'), manifest);
    await writeFile(join(manifestDir, 'CLAUDE.md'), '# Claude Instructions');
    git(manifestDir, 'add .');
    git(manifestDir, 'commit -m "Initial manifest"');

    // Rename default branch to main if needed (git init might create master)
    try {
      git(repo1Dir, 'branch -M main');
      git(repo2Dir, 'branch -M main');
      git(manifestDir, 'branch -M main');
    } catch {
      // Branch might already be main
    }

    console.log(`Test workspace created at: ${workspaceDir}`);
  });

  afterAll(async () => {
    try {
      await rm(testDir, { recursive: true, force: true });
    } catch {
      // Ignore cleanup errors
    }
  });

  describe('Creating Griptrees', () => {
    const branch = 'feat/create-test';
    let griptreePath: string;

    beforeEach(() => {
      griptreePath = join(testDir, 'feat-create-test');
    });

    afterEach(async () => {
      // Cleanup: remove worktrees and griptree directory
      try {
        const worktree1 = join(griptreePath, 'repo1');
        const worktree2 = join(griptreePath, 'repo2');
        const worktreeManifest = join(griptreePath, '.gitgrip', 'manifests');

        if (await pathExists(worktree1)) {
          git(repo1Dir, `worktree remove "${worktree1}" --force`);
        }
        if (await pathExists(worktree2)) {
          git(repo2Dir, `worktree remove "${worktree2}" --force`);
        }
        if (await pathExists(worktreeManifest)) {
          git(manifestDir, `worktree remove "${worktreeManifest}" --force`);
        }

        // Delete branches
        try { git(repo1Dir, `branch -D ${branch}`); } catch { /* ignore */ }
        try { git(repo2Dir, `branch -D ${branch}`); } catch { /* ignore */ }
        try { git(manifestDir, `branch -D ${branch}`); } catch { /* ignore */ }

        if (await pathExists(griptreePath)) {
          await rm(griptreePath, { recursive: true, force: true });
        }
      } catch {
        // Ignore cleanup errors
      }

      await removeGriptreeConfig(workspaceDir, branch);
    });

    it('creates worktrees for all repos', async () => {
      // Create griptree directory first
      await mkdir(griptreePath, { recursive: true });
      await mkdir(join(griptreePath, '.gitgrip'), { recursive: true });

      // Create worktrees with new branch (stay on main in repos)
      // Use -b to create and checkout branch in worktree only
      git(repo1Dir, `worktree add -b ${branch} "${join(griptreePath, 'repo1')}"`);
      git(repo2Dir, `worktree add -b ${branch} "${join(griptreePath, 'repo2')}"`);
      git(manifestDir, `worktree add -b ${branch} "${join(griptreePath, '.gitgrip', 'manifests')}"`);

      // Write registry config
      const config: GriptreeConfig = {
        branch,
        path: griptreePath,
        createdAt: new Date().toISOString(),
        locked: false,
      };
      await writeGriptreeConfig(workspaceDir, branch, config);

      // Write pointer
      await writeFile(join(griptreePath, '.griptree'), JSON.stringify({
        mainWorkspace: workspaceDir,
        branch,
      }, null, 2));

      // Verify worktrees exist
      expect(await pathExists(join(griptreePath, 'repo1'))).toBe(true);
      expect(await pathExists(join(griptreePath, 'repo2'))).toBe(true);
      expect(await pathExists(join(griptreePath, '.gitgrip', 'manifests'))).toBe(true);

      // Verify files are accessible in worktrees
      const readme1 = await readFile(join(griptreePath, 'repo1', 'README.md'), 'utf-8');
      expect(readme1).toContain('Repo 1');

      const readme2 = await readFile(join(griptreePath, 'repo2', 'README.md'), 'utf-8');
      expect(readme2).toContain('Repo 2');

      // Verify registry entry
      const registryConfig = await readGriptreeConfig(workspaceDir, branch);
      expect(registryConfig).not.toBeNull();
      expect(registryConfig?.path).toBe(griptreePath);

      // Verify pointer
      const pointer = await readGriptreePointer(griptreePath);
      expect(pointer?.mainWorkspace).toBe(workspaceDir);
      expect(pointer?.branch).toBe(branch);
    });

    it('worktrees are on the correct branch', async () => {
      await mkdir(griptreePath, { recursive: true });

      // Create worktrees with new branch
      git(repo1Dir, `worktree add -b ${branch} "${join(griptreePath, 'repo1')}"`);
      git(repo2Dir, `worktree add -b ${branch} "${join(griptreePath, 'repo2')}"`);

      // Verify branches in worktrees
      const branch1 = git(join(griptreePath, 'repo1'), 'rev-parse --abbrev-ref HEAD');
      const branch2 = git(join(griptreePath, 'repo2'), 'rev-parse --abbrev-ref HEAD');

      expect(branch1).toBe(branch);
      expect(branch2).toBe(branch);

      // Verify main repos are still on main
      const mainBranch1 = git(repo1Dir, 'rev-parse --abbrev-ref HEAD');
      const mainBranch2 = git(repo2Dir, 'rev-parse --abbrev-ref HEAD');

      expect(mainBranch1).toBe('main');
      expect(mainBranch2).toBe('main');
    });
  });

  describe('File Links in Griptrees', () => {
    const branch = 'feat/links-test';
    let griptreePath: string;

    beforeEach(async () => {
      griptreePath = join(testDir, 'feat-links-test');

      // Create griptree directory
      await mkdir(griptreePath, { recursive: true });
      await mkdir(join(griptreePath, '.gitgrip'), { recursive: true });

      // Create worktrees
      git(repo1Dir, `worktree add -b ${branch} "${join(griptreePath, 'repo1')}"`);
      git(repo2Dir, `worktree add -b ${branch} "${join(griptreePath, 'repo2')}"`);
      git(manifestDir, `worktree add -b ${branch} "${join(griptreePath, '.gitgrip', 'manifests')}"`);

      // Write registry config
      await writeGriptreeConfig(workspaceDir, branch, {
        branch,
        path: griptreePath,
        createdAt: new Date().toISOString(),
        locked: false,
      });

      // Write pointer
      await writeFile(join(griptreePath, '.griptree'), JSON.stringify({
        mainWorkspace: workspaceDir,
        branch,
      }, null, 2));
    });

    afterEach(async () => {
      try {
        const worktree1 = join(griptreePath, 'repo1');
        const worktree2 = join(griptreePath, 'repo2');
        const worktreeManifest = join(griptreePath, '.gitgrip', 'manifests');

        if (await pathExists(worktree1)) {
          git(repo1Dir, `worktree remove "${worktree1}" --force`);
        }
        if (await pathExists(worktree2)) {
          git(repo2Dir, `worktree remove "${worktree2}" --force`);
        }
        if (await pathExists(worktreeManifest)) {
          git(manifestDir, `worktree remove "${worktreeManifest}" --force`);
        }

        try { git(repo1Dir, `branch -D ${branch}`); } catch { /* ignore */ }
        try { git(repo2Dir, `branch -D ${branch}`); } catch { /* ignore */ }
        try { git(manifestDir, `branch -D ${branch}`); } catch { /* ignore */ }

        if (await pathExists(griptreePath)) {
          await rm(griptreePath, { recursive: true, force: true });
        }

        await removeGriptreeConfig(workspaceDir, branch);
      } catch {
        // Ignore cleanup errors
      }
    });

    it('can create symlinks in griptree workspace', async () => {
      // Create a symlink from griptree to its repo1 worktree
      const srcFile = join(griptreePath, 'repo1', 'SHARED.md');
      const destFile = join(griptreePath, 'SHARED-LINK.md');

      // Verify source exists in worktree
      expect(await pathExists(srcFile)).toBe(true);

      // Create relative symlink
      const relPath = relative(griptreePath, srcFile);
      await symlink(relPath, destFile);

      // Verify symlink works
      const content = await readFile(destFile, 'utf-8');
      expect(content).toContain('Shared file');

      // Verify it's a symlink
      const linkTarget = await readlink(destFile);
      expect(linkTarget).toContain('repo1');
    });

    it('symlinks point to worktree files, not main repo', async () => {
      // Modify the file in the worktree
      const worktreeFile = join(griptreePath, 'repo1', 'SHARED.md');
      await writeFile(worktreeFile, '# Modified in worktree');

      // Create symlink
      const destFile = join(griptreePath, 'WORKTREE-SHARED.md');
      const relPath = relative(griptreePath, worktreeFile);
      await symlink(relPath, destFile);

      // Symlink should show worktree content
      const linkContent = await readFile(destFile, 'utf-8');
      expect(linkContent).toContain('Modified in worktree');

      // Main repo should still have original content
      const mainContent = await readFile(join(repo1Dir, 'SHARED.md'), 'utf-8');
      expect(mainContent).toContain('Shared file for linking');
    });

    it('changes in griptree worktree are independent of main', async () => {
      // Modify file in griptree worktree
      const worktreeFile = join(griptreePath, 'repo1', 'README.md');
      await writeFile(worktreeFile, '# Modified in griptree');
      git(join(griptreePath, 'repo1'), 'add README.md');
      git(join(griptreePath, 'repo1'), 'commit -m "Griptree change"');

      // Main repo should still have original
      const mainContent = await readFile(join(repo1Dir, 'README.md'), 'utf-8');
      expect(mainContent).toContain('Repo 1');

      // Griptree should have modified
      const worktreeContent = await readFile(worktreeFile, 'utf-8');
      expect(worktreeContent).toContain('Modified in griptree');
    });
  });

  describe('Listing Griptrees', () => {
    afterEach(async () => {
      await removeGriptreeConfig(workspaceDir, 'feat/one');
      await removeGriptreeConfig(workspaceDir, 'feat/two');
    });

    it('lists all registered griptrees', async () => {
      // Create multiple registry entries
      await writeGriptreeConfig(workspaceDir, 'feat/one', {
        branch: 'feat/one',
        path: join(testDir, 'feat-one'),
        createdAt: '2026-01-29T12:00:00Z',
        locked: false,
      });

      await writeGriptreeConfig(workspaceDir, 'feat/two', {
        branch: 'feat/two',
        path: join(testDir, 'feat-two'),
        createdAt: '2026-01-29T13:00:00Z',
        locked: true,
      });

      const configs = await readGriptreeRegistry(workspaceDir);

      expect(configs.length).toBe(2);
      expect(configs.find(c => c.branch === 'feat/one')).toBeDefined();
      expect(configs.find(c => c.branch === 'feat/two')?.locked).toBe(true);
    });
  });

  describe('Locking/Unlocking Griptrees', () => {
    const branch = 'feat/lock-test';

    afterEach(async () => {
      await removeGriptreeConfig(workspaceDir, branch);
    });

    it('updates lock status in registry', async () => {
      await writeGriptreeConfig(workspaceDir, branch, {
        branch,
        path: join(testDir, 'feat-lock-test'),
        createdAt: '2026-01-29T12:00:00Z',
        locked: false,
      });

      // Lock
      const config = await readGriptreeConfig(workspaceDir, branch);
      config!.locked = true;
      config!.lockedAt = new Date().toISOString();
      config!.lockedReason = 'Testing lock';
      await writeGriptreeConfig(workspaceDir, branch, config!);

      // Verify lock
      const locked = await readGriptreeConfig(workspaceDir, branch);
      expect(locked?.locked).toBe(true);
      expect(locked?.lockedReason).toBe('Testing lock');

      // Unlock
      locked!.locked = false;
      locked!.lockedAt = undefined;
      locked!.lockedReason = undefined;
      await writeGriptreeConfig(workspaceDir, branch, locked!);

      // Verify unlock
      const unlocked = await readGriptreeConfig(workspaceDir, branch);
      expect(unlocked?.locked).toBe(false);
      expect(unlocked?.lockedAt).toBeUndefined();
    });
  });

  describe('Legacy Griptree Migration', () => {
    let legacyPath: string;

    beforeEach(async () => {
      legacyPath = join(testDir, 'legacy-griptree');
    });

    afterEach(async () => {
      try {
        if (await pathExists(legacyPath)) {
          await rm(legacyPath, { recursive: true, force: true });
        }
      } catch {
        // Ignore
      }
    });

    it('detects legacy griptrees', async () => {
      // Create a legacy-format griptree
      await mkdir(legacyPath, { recursive: true });
      await writeFile(join(legacyPath, '.griptree'), JSON.stringify({
        branch: 'feat/legacy',
        locked: false,
        createdAt: '2026-01-29T10:00:00Z',
      }));

      const legacies = await findLegacyGriptrees(workspaceDir);

      expect(legacies.length).toBe(1);
      expect(legacies[0].config.branch).toBe('feat/legacy');
    });
  });

  describe('Orphan Detection', () => {
    const branch = 'feat/orphan';

    afterEach(async () => {
      await removeGriptreeConfig(workspaceDir, branch);
    });

    it('detects orphaned registry entries', async () => {
      // Create a registry entry for non-existent griptree
      await writeGriptreeConfig(workspaceDir, branch, {
        branch,
        path: join(testDir, 'nonexistent-griptree'),
        createdAt: '2026-01-29T12:00:00Z',
        locked: false,
      });

      // Registry should have the entry
      const configs = await readGriptreeRegistry(workspaceDir);
      expect(configs.find(c => c.branch === branch)).toBeDefined();

      // But the path doesn't exist
      const orphanConfig = await readGriptreeConfig(workspaceDir, branch);
      const exists = await pathExists(orphanConfig!.path);
      expect(exists).toBe(false);
    });
  });

  describe('Removing Griptrees', () => {
    const branch = 'feat/remove-test';
    let griptreePath: string;

    beforeEach(() => {
      griptreePath = join(testDir, 'feat-remove-test');
    });

    afterEach(async () => {
      try {
        try { git(repo1Dir, `branch -D ${branch}`); } catch { /* ignore */ }
        try { git(repo2Dir, `branch -D ${branch}`); } catch { /* ignore */ }
        await removeGriptreeConfig(workspaceDir, branch);
      } catch {
        // Ignore
      }
    });

    it('removes worktrees and registry entry', async () => {
      // Setup: create worktrees
      await mkdir(griptreePath, { recursive: true });
      git(repo1Dir, `worktree add -b ${branch} "${join(griptreePath, 'repo1')}"`);
      git(repo2Dir, `worktree add -b ${branch} "${join(griptreePath, 'repo2')}"`);

      await writeGriptreeConfig(workspaceDir, branch, {
        branch,
        path: griptreePath,
        createdAt: new Date().toISOString(),
        locked: false,
      });

      // Verify setup
      expect(await pathExists(griptreePath)).toBe(true);
      expect(await readGriptreeConfig(workspaceDir, branch)).not.toBeNull();

      // Remove: simulate what treeRemove does
      const worktree1 = join(griptreePath, 'repo1');
      const worktree2 = join(griptreePath, 'repo2');

      if (await pathExists(worktree1)) {
        git(repo1Dir, `worktree remove "${worktree1}" --force`);
      }
      if (await pathExists(worktree2)) {
        git(repo2Dir, `worktree remove "${worktree2}" --force`);
      }

      await rm(griptreePath, { recursive: true, force: true });
      await removeGriptreeConfig(workspaceDir, branch);

      // Verify removal
      expect(await pathExists(griptreePath)).toBe(false);
      expect(await readGriptreeConfig(workspaceDir, branch)).toBeNull();
    });
  });
});
