import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { mkdir, rm, writeFile, readFile, readdir } from 'fs/promises';
import { join } from 'path';
import { tmpdir } from 'os';
import {
  sanitizeBranchName,
  getGriptreesDir,
  getGriptreeConfigDir,
  getGriptreeConfigPath,
  getGriptreePointerPath,
  readGriptreeConfig,
  writeGriptreeConfig,
  removeGriptreeConfig,
  readGriptreeRegistry,
  readGriptreePointer,
  writeGriptreePointer,
  findLegacyGriptrees,
  registerLegacyGriptree,
  isGriptreePathValid,
  findGriptreeByBranch,
  getDefaultGriptreePath,
} from '../griptree.js';
import type { GriptreeConfig, GriptreePointer } from '../../types.js';

describe('griptree', () => {
  let testDir: string;
  let workspaceDir: string;

  beforeEach(async () => {
    testDir = join(tmpdir(), `gitgrip-griptree-test-${Date.now()}`);
    workspaceDir = join(testDir, 'workspace');
    await mkdir(join(workspaceDir, '.gitgrip'), { recursive: true });
  });

  afterEach(async () => {
    try {
      await rm(testDir, { recursive: true, force: true });
    } catch {
      // Ignore cleanup errors
    }
  });

  describe('sanitizeBranchName', () => {
    it('converts slashes to hyphens', () => {
      expect(sanitizeBranchName('feat/auth')).toBe('feat-auth');
      expect(sanitizeBranchName('feat/api/v2')).toBe('feat-api-v2');
    });

    it('handles names without slashes', () => {
      expect(sanitizeBranchName('main')).toBe('main');
      expect(sanitizeBranchName('develop')).toBe('develop');
    });

    it('handles empty string', () => {
      expect(sanitizeBranchName('')).toBe('');
    });

    it('handles multiple consecutive slashes', () => {
      expect(sanitizeBranchName('feat//double')).toBe('feat--double');
    });
  });

  describe('path helpers', () => {
    it('getGriptreesDir returns correct path', () => {
      expect(getGriptreesDir('/workspace')).toBe('/workspace/.gitgrip/griptrees');
    });

    it('getGriptreeConfigDir returns correct path', () => {
      expect(getGriptreeConfigDir('/workspace', 'feat/auth')).toBe('/workspace/.gitgrip/griptrees/feat-auth');
    });

    it('getGriptreeConfigPath returns correct path', () => {
      expect(getGriptreeConfigPath('/workspace', 'feat/auth')).toBe('/workspace/.gitgrip/griptrees/feat-auth/config.json');
    });

    it('getGriptreePointerPath returns correct path', () => {
      expect(getGriptreePointerPath('/griptree/feat-auth')).toBe('/griptree/feat-auth/.griptree');
    });

    it('getDefaultGriptreePath returns sibling directory', () => {
      expect(getDefaultGriptreePath('/parent/workspace', 'feat/auth')).toBe('/parent/feat-auth');
    });
  });

  describe('writeGriptreeConfig / readGriptreeConfig', () => {
    it('writes and reads config correctly', async () => {
      const config: GriptreeConfig = {
        branch: 'feat/auth',
        path: '/path/to/griptree',
        createdAt: '2026-01-29T12:00:00Z',
        locked: false,
      };

      await writeGriptreeConfig(workspaceDir, 'feat/auth', config);
      const result = await readGriptreeConfig(workspaceDir, 'feat/auth');

      expect(result).toEqual(config);
    });

    it('creates directory structure if needed', async () => {
      const config: GriptreeConfig = {
        branch: 'feat/deep/nested/branch',
        path: '/path/to/griptree',
        createdAt: '2026-01-29T12:00:00Z',
        locked: false,
      };

      await writeGriptreeConfig(workspaceDir, 'feat/deep/nested/branch', config);
      const configPath = getGriptreeConfigPath(workspaceDir, 'feat/deep/nested/branch');
      const content = await readFile(configPath, 'utf-8');

      expect(JSON.parse(content)).toEqual(config);
    });

    it('returns null for non-existent config', async () => {
      const result = await readGriptreeConfig(workspaceDir, 'nonexistent');
      expect(result).toBeNull();
    });

    it('handles optional fields', async () => {
      const config: GriptreeConfig = {
        branch: 'feat/full',
        path: '/path/to/griptree',
        createdAt: '2026-01-29T12:00:00Z',
        createdBy: 'user',
        locked: true,
        lockedAt: '2026-01-29T13:00:00Z',
        lockedReason: 'In progress',
      };

      await writeGriptreeConfig(workspaceDir, 'feat/full', config);
      const result = await readGriptreeConfig(workspaceDir, 'feat/full');

      expect(result).toEqual(config);
      expect(result?.createdBy).toBe('user');
      expect(result?.lockedAt).toBe('2026-01-29T13:00:00Z');
      expect(result?.lockedReason).toBe('In progress');
    });
  });

  describe('removeGriptreeConfig', () => {
    it('removes existing config', async () => {
      const config: GriptreeConfig = {
        branch: 'feat/to-remove',
        path: '/path/to/griptree',
        createdAt: '2026-01-29T12:00:00Z',
        locked: false,
      };

      await writeGriptreeConfig(workspaceDir, 'feat/to-remove', config);
      expect(await readGriptreeConfig(workspaceDir, 'feat/to-remove')).not.toBeNull();

      await removeGriptreeConfig(workspaceDir, 'feat/to-remove');
      expect(await readGriptreeConfig(workspaceDir, 'feat/to-remove')).toBeNull();
    });

    it('does not throw for non-existent config', async () => {
      await expect(removeGriptreeConfig(workspaceDir, 'nonexistent')).resolves.not.toThrow();
    });
  });

  describe('readGriptreeRegistry', () => {
    it('returns empty array when no griptrees exist', async () => {
      const result = await readGriptreeRegistry(workspaceDir);
      expect(result).toEqual([]);
    });

    it('returns all registered griptrees', async () => {
      const configs: GriptreeConfig[] = [
        { branch: 'feat/one', path: '/path/one', createdAt: '2026-01-29T12:00:00Z', locked: false },
        { branch: 'feat/two', path: '/path/two', createdAt: '2026-01-29T13:00:00Z', locked: true },
        { branch: 'fix/three', path: '/path/three', createdAt: '2026-01-29T14:00:00Z', locked: false },
      ];

      for (const config of configs) {
        await writeGriptreeConfig(workspaceDir, config.branch, config);
      }

      const result = await readGriptreeRegistry(workspaceDir);

      expect(result.length).toBe(3);
      expect(result.map(c => c.branch).sort()).toEqual(['feat/one', 'feat/two', 'fix/three']);
    });

    it('skips invalid config files', async () => {
      // Create valid config
      await writeGriptreeConfig(workspaceDir, 'feat/valid', {
        branch: 'feat/valid',
        path: '/path/valid',
        createdAt: '2026-01-29T12:00:00Z',
        locked: false,
      });

      // Create invalid config (malformed JSON)
      const invalidDir = join(getGriptreesDir(workspaceDir), 'invalid-branch');
      await mkdir(invalidDir, { recursive: true });
      await writeFile(join(invalidDir, 'config.json'), 'not valid json');

      const result = await readGriptreeRegistry(workspaceDir);

      expect(result.length).toBe(1);
      expect(result[0].branch).toBe('feat/valid');
    });
  });

  describe('writeGriptreePointer / readGriptreePointer', () => {
    it('writes and reads pointer correctly', async () => {
      const griptreePath = join(testDir, 'feat-auth');
      await mkdir(griptreePath, { recursive: true });

      const pointer: GriptreePointer = {
        mainWorkspace: workspaceDir,
        branch: 'feat/auth',
      };

      await writeGriptreePointer(griptreePath, pointer);
      const result = await readGriptreePointer(griptreePath);

      expect(result).toEqual(pointer);
    });

    it('returns null for non-existent pointer', async () => {
      const result = await readGriptreePointer('/nonexistent/path');
      expect(result).toBeNull();
    });
  });

  describe('findLegacyGriptrees', () => {
    it('finds legacy griptrees with old format', async () => {
      // Create a sibling directory with legacy .griptree format
      const legacyPath = join(testDir, 'feat-legacy');
      await mkdir(legacyPath, { recursive: true });
      await writeFile(join(legacyPath, '.griptree'), JSON.stringify({
        branch: 'feat/legacy',
        locked: false,
        createdAt: '2026-01-29T12:00:00Z',
      }));

      const result = await findLegacyGriptrees(workspaceDir);

      expect(result.length).toBe(1);
      expect(result[0].path).toBe(legacyPath);
      expect(result[0].config.branch).toBe('feat/legacy');
    });

    it('skips already registered griptrees', async () => {
      // Register a griptree
      const registeredPath = join(testDir, 'feat-registered');
      await mkdir(registeredPath, { recursive: true });
      await writeGriptreeConfig(workspaceDir, 'feat/registered', {
        branch: 'feat/registered',
        path: registeredPath,
        createdAt: '2026-01-29T12:00:00Z',
        locked: false,
      });

      // Create pointer in registered griptree (new format, already registered)
      await writeFile(join(registeredPath, '.griptree'), JSON.stringify({
        mainWorkspace: workspaceDir,
        branch: 'feat/registered',
      }));

      // Create a legacy griptree
      const legacyPath = join(testDir, 'feat-legacy');
      await mkdir(legacyPath, { recursive: true });
      await writeFile(join(legacyPath, '.griptree'), JSON.stringify({
        branch: 'feat/legacy',
        locked: false,
        createdAt: '2026-01-29T12:00:00Z',
      }));

      const result = await findLegacyGriptrees(workspaceDir);

      expect(result.length).toBe(1);
      expect(result[0].config.branch).toBe('feat/legacy');
    });

    it('skips the main workspace directory', async () => {
      // Create .griptree in workspace (shouldn't be found)
      await writeFile(join(workspaceDir, '.griptree'), JSON.stringify({
        branch: 'main',
        locked: false,
        createdAt: '2026-01-29T12:00:00Z',
      }));

      const result = await findLegacyGriptrees(workspaceDir);

      expect(result.length).toBe(0);
    });

    it('skips directories that belong to different workspaces', async () => {
      // Create a griptree pointing to a different workspace
      const otherGriptreePath = join(testDir, 'other-griptree');
      await mkdir(otherGriptreePath, { recursive: true });
      await writeFile(join(otherGriptreePath, '.griptree'), JSON.stringify({
        mainWorkspace: '/some/other/workspace',
        branch: 'feat/other',
      }));

      const result = await findLegacyGriptrees(workspaceDir);

      expect(result.length).toBe(0);
    });
  });

  describe('registerLegacyGriptree', () => {
    it('registers legacy griptree in central registry', async () => {
      const legacyPath = join(testDir, 'feat-legacy');
      await mkdir(legacyPath, { recursive: true });

      const legacyConfig = {
        branch: 'feat/legacy',
        locked: true,
        createdAt: '2026-01-29T12:00:00Z',
      };

      const config = await registerLegacyGriptree(workspaceDir, legacyPath, legacyConfig);

      expect(config.branch).toBe('feat/legacy');
      expect(config.path).toBe(legacyPath);
      expect(config.locked).toBe(true);

      // Verify registry entry
      const registryConfig = await readGriptreeConfig(workspaceDir, 'feat/legacy');
      expect(registryConfig).toEqual(config);

      // Verify pointer was updated
      const pointer = await readGriptreePointer(legacyPath);
      expect(pointer?.mainWorkspace).toBe(workspaceDir);
      expect(pointer?.branch).toBe('feat/legacy');
    });
  });

  describe('isGriptreePathValid', () => {
    it('returns true for existing path', async () => {
      const griptreePath = join(testDir, 'feat-exists');
      await mkdir(griptreePath, { recursive: true });

      const config: GriptreeConfig = {
        branch: 'feat/exists',
        path: griptreePath,
        createdAt: '2026-01-29T12:00:00Z',
        locked: false,
      };

      const result = await isGriptreePathValid(config);
      expect(result).toBe(true);
    });

    it('returns false for non-existent path', async () => {
      const config: GriptreeConfig = {
        branch: 'feat/gone',
        path: join(testDir, 'nonexistent'),
        createdAt: '2026-01-29T12:00:00Z',
        locked: false,
      };

      const result = await isGriptreePathValid(config);
      expect(result).toBe(false);
    });
  });

  describe('findGriptreeByBranch', () => {
    it('finds existing griptree by branch name', async () => {
      await writeGriptreeConfig(workspaceDir, 'feat/findme', {
        branch: 'feat/findme',
        path: '/path/to/findme',
        createdAt: '2026-01-29T12:00:00Z',
        locked: false,
      });

      const result = await findGriptreeByBranch(workspaceDir, 'feat/findme');

      expect(result).not.toBeNull();
      expect(result?.branch).toBe('feat/findme');
    });

    it('returns null for non-existent branch', async () => {
      const result = await findGriptreeByBranch(workspaceDir, 'feat/nonexistent');
      expect(result).toBeNull();
    });
  });
});
