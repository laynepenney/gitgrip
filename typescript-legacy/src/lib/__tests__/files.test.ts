import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { mkdir, writeFile, rm, readFile, readlink, stat } from 'fs/promises';
import { join, resolve } from 'path';
import { tmpdir } from 'os';
import {
  copyFile,
  createSymlink,
  getLinkStatus,
  processRepoLinks,
  validatePath,
} from '../files.js';
import type { RepoConfig } from '../../types.js';

describe('files', () => {
  let testDir: string;
  let repoDir: string;
  let workspaceDir: string;

  beforeEach(async () => {
    testDir = join(tmpdir(), `codi-repo-test-${Date.now()}`);
    repoDir = join(testDir, 'repo');
    workspaceDir = join(testDir, 'workspace');

    await mkdir(repoDir, { recursive: true });
    await mkdir(workspaceDir, { recursive: true });
  });

  afterEach(async () => {
    try {
      await rm(testDir, { recursive: true, force: true });
    } catch {
      // Ignore cleanup errors
    }
  });

  describe('validatePath', () => {
    it('should return true for valid paths', () => {
      expect(validatePath('/base', 'sub/dir')).toBe(true);
      expect(validatePath('/base', './sub/dir')).toBe(true);
      expect(validatePath('/base', 'file.txt')).toBe(true);
    });

    it('should return false for paths that escape boundary', () => {
      expect(validatePath('/base', '../outside')).toBe(false);
      expect(validatePath('/base', 'sub/../../outside')).toBe(false);
    });
  });

  describe('copyFile', () => {
    it('should copy a file', async () => {
      const srcPath = join(repoDir, 'source.txt');
      const destPath = join(workspaceDir, 'dest.txt');

      await writeFile(srcPath, 'test content');

      const result = await copyFile(srcPath, destPath, { force: true });

      expect(result.copied).toBe(true);
      const content = await readFile(destPath, 'utf-8');
      expect(content).toBe('test content');
    });

    it('should fail if source does not exist', async () => {
      const srcPath = join(repoDir, 'nonexistent.txt');
      const destPath = join(workspaceDir, 'dest.txt');

      const result = await copyFile(srcPath, destPath);

      expect(result.copied).toBe(false);
      expect(result.message).toContain('Source does not exist');
    });

    it('should not overwrite without force flag', async () => {
      const srcPath = join(repoDir, 'source.txt');
      const destPath = join(workspaceDir, 'dest.txt');

      await writeFile(srcPath, 'new content');
      await writeFile(destPath, 'existing content');

      const result = await copyFile(srcPath, destPath, { force: false });

      expect(result.copied).toBe(false);
      expect(result.message).toContain('Destination exists');

      const content = await readFile(destPath, 'utf-8');
      expect(content).toBe('existing content');
    });

    it('should preview with dry-run', async () => {
      const srcPath = join(repoDir, 'source.txt');
      const destPath = join(workspaceDir, 'dest.txt');

      await writeFile(srcPath, 'test content');

      const result = await copyFile(srcPath, destPath, { dryRun: true });

      expect(result.copied).toBe(true);
      expect(result.message).toContain('Would copy');

      // File should not exist
      await expect(readFile(destPath, 'utf-8')).rejects.toThrow();
    });
  });

  describe('createSymlink', () => {
    it('should create a relative symlink', async () => {
      const srcPath = join(repoDir, 'source.txt');
      const destPath = join(workspaceDir, 'link.txt');

      await writeFile(srcPath, 'test content');

      const result = await createSymlink(srcPath, destPath, { force: true });

      expect(result.created).toBe(true);

      const linkTarget = await readlink(destPath);
      expect(linkTarget).toContain('repo');

      const content = await readFile(destPath, 'utf-8');
      expect(content).toBe('test content');
    });

    it('should fail if source does not exist', async () => {
      const srcPath = join(repoDir, 'nonexistent.txt');
      const destPath = join(workspaceDir, 'link.txt');

      const result = await createSymlink(srcPath, destPath);

      expect(result.created).toBe(false);
      expect(result.message).toContain('Source does not exist');
    });

    it('should create parent directories', async () => {
      const srcPath = join(repoDir, 'source.txt');
      const destPath = join(workspaceDir, 'nested', 'dir', 'link.txt');

      await writeFile(srcPath, 'test content');

      const result = await createSymlink(srcPath, destPath, { force: true });

      expect(result.created).toBe(true);
    });
  });

  describe('getLinkStatus', () => {
    it('should return valid for a working symlink', async () => {
      const srcPath = join(repoDir, 'source.txt');
      const destPath = join(workspaceDir, 'link.txt');

      await writeFile(srcPath, 'test content');
      await createSymlink(srcPath, destPath, { force: true });

      const status = await getLinkStatus('linkfile', 'test-repo', srcPath, destPath);

      expect(status.status).toBe('valid');
      expect(status.repoName).toBe('test-repo');
    });

    it('should return missing when destination does not exist', async () => {
      const srcPath = join(repoDir, 'source.txt');
      const destPath = join(workspaceDir, 'link.txt');

      await writeFile(srcPath, 'test content');

      const status = await getLinkStatus('linkfile', 'test-repo', srcPath, destPath);

      expect(status.status).toBe('missing');
    });

    it('should return broken when source does not exist', async () => {
      const srcPath = join(repoDir, 'nonexistent.txt');
      const destPath = join(workspaceDir, 'link.txt');

      const status = await getLinkStatus('linkfile', 'test-repo', srcPath, destPath);

      expect(status.status).toBe('broken');
    });
  });

  describe('processRepoLinks', () => {
    it('should process copyfile entries', async () => {
      const srcPath = join(repoDir, 'file.txt');
      await writeFile(srcPath, 'content');

      const repoConfig: RepoConfig = {
        url: 'git@github.com:test/repo.git',
        path: './repo',
        default_branch: 'main',
        copyfile: [{ src: 'file.txt', dest: 'copied.txt' }],
      };

      const result = await processRepoLinks('test', repoConfig, repoDir, workspaceDir, { force: true });

      expect(result.copyfiles.length).toBe(1);
      expect(result.copyfiles[0].success).toBe(true);

      const content = await readFile(join(workspaceDir, 'copied.txt'), 'utf-8');
      expect(content).toBe('content');
    });

    it('should process linkfile entries', async () => {
      const srcPath = join(repoDir, 'file.txt');
      await writeFile(srcPath, 'content');

      const repoConfig: RepoConfig = {
        url: 'git@github.com:test/repo.git',
        path: './repo',
        default_branch: 'main',
        linkfile: [{ src: 'file.txt', dest: 'linked.txt' }],
      };

      const result = await processRepoLinks('test', repoConfig, repoDir, workspaceDir, { force: true });

      expect(result.linkfiles.length).toBe(1);
      expect(result.linkfiles[0].success).toBe(true);

      const content = await readFile(join(workspaceDir, 'linked.txt'), 'utf-8');
      expect(content).toBe('content');
    });

    it('should validate paths do not escape boundaries', async () => {
      const repoConfig: RepoConfig = {
        url: 'git@github.com:test/repo.git',
        path: './repo',
        default_branch: 'main',
        copyfile: [{ src: '../escape.txt', dest: 'copied.txt' }],
      };

      const result = await processRepoLinks('test', repoConfig, repoDir, workspaceDir);

      expect(result.copyfiles.length).toBe(1);
      expect(result.copyfiles[0].success).toBe(false);
      expect(result.copyfiles[0].message).toContain('escapes');
    });
  });
});
