import { describe, it, expect } from 'vitest';
import { generateManifestPRBody, parseLinkedPRsFromBody } from '../github.js';
import type { LinkedPR } from '../../types.js';

describe('generateManifestPRBody', () => {
  it('generates a body with PR table', () => {
    const linkedPRs: LinkedPR[] = [
      {
        repoName: 'public',
        owner: 'org',
        repo: 'public-repo',
        number: 42,
        url: 'https://github.com/org/public-repo/pull/42',
        state: 'open',
        approved: true,
        checksPass: true,
        mergeable: true,
      },
      {
        repoName: 'private',
        owner: 'org',
        repo: 'private-repo',
        number: 15,
        url: 'https://github.com/org/private-repo/pull/15',
        state: 'open',
        approved: false,
        checksPass: true,
        mergeable: true,
      },
    ];

    const body = generateManifestPRBody('Add feature', linkedPRs);

    expect(body).toContain('Cross-Repository PR');
    expect(body).toContain('public');
    expect(body).toContain('private');
    expect(body).toContain('#42');
    expect(body).toContain('#15');
    expect(body).toContain('codi-repo:links:public#42,private#15');
  });

  it('includes additional body content', () => {
    const linkedPRs: LinkedPR[] = [
      {
        repoName: 'test',
        owner: 'org',
        repo: 'test',
        number: 1,
        url: 'https://github.com/org/test/pull/1',
        state: 'open',
        approved: true,
        checksPass: true,
        mergeable: true,
      },
    ];

    const body = generateManifestPRBody('Title', linkedPRs, 'Additional description');

    expect(body).toContain('Additional description');
  });
});

describe('parseLinkedPRsFromBody', () => {
  it('parses linked PRs from body', () => {
    const body = `
## Cross-Repository PR

| Repository | PR | Status |
|------------|-----|--------|
| public | #42 | open |
| private | #15 | open |

<!-- codi-repo:links:public#42,private#15 -->
    `;

    const result = parseLinkedPRsFromBody(body);

    expect(result).toEqual([
      { repoName: 'public', number: 42 },
      { repoName: 'private', number: 15 },
    ]);
  });

  it('returns empty array if no links found', () => {
    const body = 'Just a regular PR body';
    const result = parseLinkedPRsFromBody(body);
    expect(result).toEqual([]);
  });

  it('handles single PR link', () => {
    const body = '<!-- codi-repo:links:repo#123 -->';
    const result = parseLinkedPRsFromBody(body);
    expect(result).toEqual([{ repoName: 'repo', number: 123 }]);
  });
});
