import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { mkdir, rm, writeFile } from 'fs/promises';
import { join } from 'path';
import { tmpdir } from 'os';
import {
  parseGitHubUrl,
  generateSampleManifest,
  findManifestPath,
  findLegacyManifestPath,
  loadManifest,
  getCodiRepoDir,
  getManifestsDir,
  getManifestPath,
} from '../manifest.js';

describe('parseGitHubUrl', () => {
  it('parses SSH URLs', () => {
    const result = parseGitHubUrl('git@github.com:owner/repo.git');
    expect(result).toEqual({ owner: 'owner', repo: 'repo' });
  });

  it('parses SSH URLs without .git suffix', () => {
    const result = parseGitHubUrl('git@github.com:owner/repo');
    expect(result).toEqual({ owner: 'owner', repo: 'repo' });
  });

  it('parses HTTPS URLs', () => {
    const result = parseGitHubUrl('https://github.com/owner/repo.git');
    expect(result).toEqual({ owner: 'owner', repo: 'repo' });
  });

  it('parses HTTPS URLs without .git suffix', () => {
    const result = parseGitHubUrl('https://github.com/owner/repo');
    expect(result).toEqual({ owner: 'owner', repo: 'repo' });
  });

  it('throws on invalid URLs', () => {
    expect(() => parseGitHubUrl('not-a-url')).toThrow();
    expect(() => parseGitHubUrl('https://gitlab.com/owner/repo')).toThrow();
  });
});

describe('generateSampleManifest', () => {
  it('returns a valid manifest structure', () => {
    const manifest = generateSampleManifest();

    expect(manifest.version).toBe(1);
    expect(manifest.repos).toBeDefined();
    expect(Object.keys(manifest.repos).length).toBeGreaterThan(0);
    expect(manifest.settings).toBeDefined();
    expect(manifest.settings.pr_prefix).toBe('[cross-repo]');
    expect(manifest.settings.merge_strategy).toBe('all-or-nothing');
  });

  it('includes required fields for each repo', () => {
    const manifest = generateSampleManifest();

    for (const [name, repo] of Object.entries(manifest.repos)) {
      expect(repo.url).toBeDefined();
      expect(repo.path).toBeDefined();
      expect(repo.default_branch).toBeDefined();
    }
  });
});

describe('path helpers', () => {
  it('getCodiRepoDir returns correct path', () => {
    expect(getCodiRepoDir('/workspace')).toBe('/workspace/.codi-repo');
  });

  it('getManifestsDir returns correct path', () => {
    expect(getManifestsDir('/workspace')).toBe('/workspace/.codi-repo/manifests');
  });

  it('getManifestPath returns correct path', () => {
    expect(getManifestPath('/workspace')).toBe('/workspace/.codi-repo/manifests/manifest.yaml');
  });
});

describe('findManifestPath', () => {
  let testDir: string;

  beforeEach(async () => {
    testDir = join(tmpdir(), `codi-repo-test-${Date.now()}`);
    await mkdir(testDir, { recursive: true });
  });

  afterEach(async () => {
    await rm(testDir, { recursive: true, force: true });
  });

  it('finds manifest in .codi-repo/manifests/', async () => {
    const manifestsDir = join(testDir, '.codi-repo', 'manifests');
    await mkdir(manifestsDir, { recursive: true });
    await writeFile(join(manifestsDir, 'manifest.yaml'), 'version: 1\nrepos: {}');

    const found = await findManifestPath(testDir);
    expect(found).toBe(join(manifestsDir, 'manifest.yaml'));
  });

  it('finds manifest from subdirectory', async () => {
    const manifestsDir = join(testDir, '.codi-repo', 'manifests');
    const subDir = join(testDir, 'some', 'nested', 'dir');
    await mkdir(manifestsDir, { recursive: true });
    await mkdir(subDir, { recursive: true });
    await writeFile(join(manifestsDir, 'manifest.yaml'), 'version: 1\nrepos: {}');

    const found = await findManifestPath(subDir);
    expect(found).toBe(join(manifestsDir, 'manifest.yaml'));
  });

  it('returns null when no manifest exists', async () => {
    const found = await findManifestPath(testDir);
    expect(found).toBeNull();
  });
});

describe('findLegacyManifestPath', () => {
  let testDir: string;

  beforeEach(async () => {
    testDir = join(tmpdir(), `codi-repo-legacy-test-${Date.now()}`);
    await mkdir(testDir, { recursive: true });
  });

  afterEach(async () => {
    await rm(testDir, { recursive: true, force: true });
  });

  it('finds legacy codi-repos.yaml', async () => {
    await writeFile(join(testDir, 'codi-repos.yaml'), 'version: 1\nrepos: {}');

    const found = await findLegacyManifestPath(testDir);
    expect(found).toBe(join(testDir, 'codi-repos.yaml'));
  });

  it('finds legacy manifest from subdirectory', async () => {
    const subDir = join(testDir, 'some', 'nested', 'dir');
    await mkdir(subDir, { recursive: true });
    await writeFile(join(testDir, 'codi-repos.yaml'), 'version: 1\nrepos: {}');

    const found = await findLegacyManifestPath(subDir);
    expect(found).toBe(join(testDir, 'codi-repos.yaml'));
  });

  it('returns null when no legacy manifest exists', async () => {
    const found = await findLegacyManifestPath(testDir);
    expect(found).toBeNull();
  });
});

describe('loadManifest', () => {
  let testDir: string;

  beforeEach(async () => {
    testDir = join(tmpdir(), `codi-repo-load-test-${Date.now()}`);
    await mkdir(testDir, { recursive: true });
  });

  afterEach(async () => {
    await rm(testDir, { recursive: true, force: true });
  });

  it('loads manifest and returns workspace root', async () => {
    const manifestsDir = join(testDir, '.codi-repo', 'manifests');
    await mkdir(manifestsDir, { recursive: true });

    const manifestContent = `
version: 1
repos:
  myrepo:
    url: git@github.com:owner/repo.git
    path: ./myrepo
    default_branch: main
settings:
  pr_prefix: "[test]"
  merge_strategy: all-or-nothing
`;
    await writeFile(join(manifestsDir, 'manifest.yaml'), manifestContent);

    const { manifest, rootDir } = await loadManifest(join(manifestsDir, 'manifest.yaml'));

    expect(rootDir).toBe(testDir);
    expect(manifest.version).toBe(1);
    expect(manifest.repos.myrepo).toBeDefined();
    expect(manifest.repos.myrepo.url).toBe('git@github.com:owner/repo.git');
  });

  it('applies default settings', async () => {
    const manifestsDir = join(testDir, '.codi-repo', 'manifests');
    await mkdir(manifestsDir, { recursive: true });

    const manifestContent = `
version: 1
repos:
  myrepo:
    url: git@github.com:owner/repo.git
    path: ./myrepo
`;
    await writeFile(join(manifestsDir, 'manifest.yaml'), manifestContent);

    const { manifest } = await loadManifest(join(manifestsDir, 'manifest.yaml'));

    expect(manifest.repos.myrepo.default_branch).toBe('main');
    expect(manifest.settings.pr_prefix).toBe('[cross-repo]');
    expect(manifest.settings.merge_strategy).toBe('all-or-nothing');
  });

  it('throws on missing repos', async () => {
    const manifestsDir = join(testDir, '.codi-repo', 'manifests');
    await mkdir(manifestsDir, { recursive: true });

    const manifestContent = 'version: 1\nrepos: {}';
    await writeFile(join(manifestsDir, 'manifest.yaml'), manifestContent);

    await expect(loadManifest(join(manifestsDir, 'manifest.yaml'))).rejects.toThrow(
      'Manifest must define at least one repository'
    );
  });

  it('throws on missing url', async () => {
    const manifestsDir = join(testDir, '.codi-repo', 'manifests');
    await mkdir(manifestsDir, { recursive: true });

    const manifestContent = `
version: 1
repos:
  myrepo:
    path: ./myrepo
`;
    await writeFile(join(manifestsDir, 'manifest.yaml'), manifestContent);

    await expect(loadManifest(join(manifestsDir, 'manifest.yaml'))).rejects.toThrow(
      "Repository 'myrepo' is missing 'url'"
    );
  });
});
