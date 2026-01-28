# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 0.2.x   | :white_check_mark: |
| 0.1.x   | :x:                |

## Reporting a Vulnerability

If you discover a security vulnerability, please report it privately:

1. **Do not** open a public issue
2. Email the maintainers or use GitHub's private vulnerability reporting
3. Include:
   - Description of the vulnerability
   - Steps to reproduce
   - Potential impact
   - Suggested fix (if any)

We aim to respond within 48 hours and will work with you to understand and address the issue.

## Security Considerations

gitgrip interacts with:
- **Git repositories** - Uses your local git credentials
- **GitHub API** - Uses `gh` CLI authentication
- **File system** - Reads/writes to workspace directories

The tool does not:
- Store credentials
- Send telemetry
- Execute arbitrary remote code
