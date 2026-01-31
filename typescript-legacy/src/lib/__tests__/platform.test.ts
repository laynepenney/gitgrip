import { describe, it, expect } from 'vitest';
import { detectPlatform, getPlatformAdapter, parseRepoUrl, isSupportedUrl } from '../platform/index.js';

describe('Platform Detection', () => {
  describe('detectPlatform', () => {
    it('should detect GitHub URLs', () => {
      expect(detectPlatform('git@github.com:owner/repo.git')).toBe('github');
      expect(detectPlatform('https://github.com/owner/repo.git')).toBe('github');
      expect(detectPlatform('https://github.com/owner/repo')).toBe('github');
    });

    it('should detect GitLab URLs', () => {
      expect(detectPlatform('git@gitlab.com:owner/repo.git')).toBe('gitlab');
      expect(detectPlatform('https://gitlab.com/owner/repo.git')).toBe('gitlab');
      expect(detectPlatform('https://gitlab.com/group/subgroup/repo.git')).toBe('gitlab');
    });

    it('should detect Azure DevOps URLs', () => {
      expect(detectPlatform('https://dev.azure.com/org/project/_git/repo')).toBe('azure-devops');
      expect(detectPlatform('git@ssh.dev.azure.com:v3/org/project/repo')).toBe('azure-devops');
      expect(detectPlatform('https://org.visualstudio.com/project/_git/repo')).toBe('azure-devops');
    });

    it('should return null for unknown URLs', () => {
      expect(detectPlatform('git@bitbucket.org:owner/repo.git')).toBe(null);
      expect(detectPlatform('https://custom.server.com/owner/repo.git')).toBe(null);
    });
  });

  describe('parseRepoUrl', () => {
    it('should parse GitHub SSH URLs', () => {
      const result = parseRepoUrl('git@github.com:owner/repo.git');
      expect(result).toEqual({
        owner: 'owner',
        repo: 'repo',
        platform: 'github',
      });
    });

    it('should parse GitHub HTTPS URLs', () => {
      const result = parseRepoUrl('https://github.com/owner/repo.git');
      expect(result).toEqual({
        owner: 'owner',
        repo: 'repo',
        platform: 'github',
      });
    });

    it('should parse GitLab URLs with nested groups', () => {
      const result = parseRepoUrl('https://gitlab.com/group/subgroup/repo.git');
      expect(result).toEqual({
        owner: 'group/subgroup',
        repo: 'repo',
        platform: 'gitlab',
      });
    });

    it('should parse Azure DevOps HTTPS URLs', () => {
      const result = parseRepoUrl('https://dev.azure.com/org/project/_git/repo');
      expect(result).toEqual({
        owner: 'org/project',
        repo: 'repo',
        project: 'project',
        platform: 'azure-devops',
      });
    });

    it('should parse Azure DevOps SSH URLs', () => {
      const result = parseRepoUrl('git@ssh.dev.azure.com:v3/org/project/repo');
      expect(result).toEqual({
        owner: 'org/project',
        repo: 'repo',
        project: 'project',
        platform: 'azure-devops',
      });
    });

    it('should return null for unknown URLs', () => {
      const result = parseRepoUrl('git@bitbucket.org:owner/repo.git');
      expect(result).toBe(null);
    });
  });

  describe('isSupportedUrl', () => {
    it('should return true for supported URLs', () => {
      expect(isSupportedUrl('git@github.com:owner/repo.git')).toBe(true);
      expect(isSupportedUrl('git@gitlab.com:owner/repo.git')).toBe(true);
      expect(isSupportedUrl('https://dev.azure.com/org/project/_git/repo')).toBe(true);
    });

    it('should return false for unsupported URLs', () => {
      expect(isSupportedUrl('git@bitbucket.org:owner/repo.git')).toBe(false);
    });
  });

  describe('getPlatformAdapter', () => {
    it('should return GitHub adapter', () => {
      const adapter = getPlatformAdapter('github');
      expect(adapter.type).toBe('github');
    });

    it('should return GitLab adapter', () => {
      const adapter = getPlatformAdapter('gitlab');
      expect(adapter.type).toBe('gitlab');
    });

    it('should return Azure DevOps adapter', () => {
      const adapter = getPlatformAdapter('azure-devops');
      expect(adapter.type).toBe('azure-devops');
    });

    it('should cache platform instances', () => {
      const adapter1 = getPlatformAdapter('github');
      const adapter2 = getPlatformAdapter('github');
      expect(adapter1).toBe(adapter2);
    });

    it('should create different instances for different base URLs', () => {
      const adapter1 = getPlatformAdapter('gitlab');
      const adapter2 = getPlatformAdapter('gitlab', { type: 'gitlab', baseUrl: 'https://gitlab.company.com' });
      expect(adapter1).not.toBe(adapter2);
    });
  });
});

describe('Platform URL Matching', () => {
  describe('GitHub', () => {
    it('should match GitHub URLs', () => {
      const adapter = getPlatformAdapter('github');
      expect(adapter.matchesUrl('git@github.com:owner/repo.git')).toBe(true);
      expect(adapter.matchesUrl('https://github.com/owner/repo.git')).toBe(true);
    });

    it('should not match non-GitHub URLs', () => {
      const adapter = getPlatformAdapter('github');
      expect(adapter.matchesUrl('git@gitlab.com:owner/repo.git')).toBe(false);
    });
  });

  describe('GitLab', () => {
    it('should match GitLab URLs', () => {
      const adapter = getPlatformAdapter('gitlab');
      expect(adapter.matchesUrl('git@gitlab.com:owner/repo.git')).toBe(true);
      expect(adapter.matchesUrl('https://gitlab.com/owner/repo.git')).toBe(true);
    });
  });

  describe('Azure DevOps', () => {
    it('should match Azure DevOps URLs', () => {
      const adapter = getPlatformAdapter('azure-devops');
      expect(adapter.matchesUrl('https://dev.azure.com/org/project/_git/repo')).toBe(true);
      expect(adapter.matchesUrl('git@ssh.dev.azure.com:v3/org/project/repo')).toBe(true);
      expect(adapter.matchesUrl('https://org.visualstudio.com/project/_git/repo')).toBe(true);
    });
  });
});

describe('Linked PR Comment Format', () => {
  it('should generate and parse GitHub linked PR comments', () => {
    const adapter = getPlatformAdapter('github');
    const links = [
      { repoName: 'frontend', number: 123 },
      { repoName: 'backend', number: 456 },
    ];
    const comment = adapter.generateLinkedPRComment(links);
    expect(comment).toContain('frontend#123');
    expect(comment).toContain('backend#456');

    const parsed = adapter.parseLinkedPRComment(comment);
    expect(parsed).toEqual(links);
  });

  it('should generate and parse GitLab linked PR comments', () => {
    const adapter = getPlatformAdapter('gitlab');
    const links = [
      { repoName: 'frontend', number: 123 },
      { repoName: 'backend', number: 456 },
    ];
    const comment = adapter.generateLinkedPRComment(links);
    expect(comment).toContain('frontend!123');
    expect(comment).toContain('backend!456');

    const parsed = adapter.parseLinkedPRComment(comment);
    expect(parsed).toEqual(links);
  });
});
