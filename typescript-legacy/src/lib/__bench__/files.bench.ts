import { describe, bench, beforeAll, afterAll } from 'vitest';
import { mkdir, rm, writeFile, symlink } from 'fs/promises';
import { join, relative, dirname } from 'path';
import { tmpdir } from 'os';
import { validatePath, getLinkStatus } from '../files.js';

describe('Path Validation', () => {
  bench('validatePath - valid path', () => {
    validatePath('/workspace', './src/index.ts');
  });

  bench('validatePath - nested path', () => {
    validatePath('/workspace', './src/lib/utils/helpers.ts');
  });

  bench('validatePath - path with dots', () => {
    validatePath('/workspace', './src/../src/index.ts');
  });
});

describe('Link Status', () => {
  let testDir: string;
  let srcFile: string;
  let destCopy: string;
  let destLink: string;

  beforeAll(async () => {
    testDir = join(tmpdir(), `codi-repo-files-bench-${Date.now()}`);
    const srcDir = join(testDir, 'repo');
    const destDir = join(testDir, 'workspace');
    await mkdir(srcDir, { recursive: true });
    await mkdir(destDir, { recursive: true });

    // Create source file
    srcFile = join(srcDir, 'file.txt');
    await writeFile(srcFile, 'test content');

    // Create destination copy
    destCopy = join(destDir, 'copy.txt');
    await writeFile(destCopy, 'test content');

    // Create destination symlink
    destLink = join(destDir, 'link.txt');
    const relativePath = relative(dirname(destLink), srcFile);
    await symlink(relativePath, destLink);
  });

  afterAll(async () => {
    await rm(testDir, { recursive: true, force: true });
  });

  bench('getLinkStatus - copyfile valid', async () => {
    await getLinkStatus('copyfile', 'repo', srcFile, destCopy);
  });

  bench('getLinkStatus - linkfile valid', async () => {
    await getLinkStatus('linkfile', 'repo', srcFile, destLink);
  });

  bench('getLinkStatus - missing dest', async () => {
    await getLinkStatus('copyfile', 'repo', srcFile, join(testDir, 'nonexistent.txt'));
  });
});
